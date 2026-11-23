"""Offline tests for safe_download.py. Run: python3 -m unittest discover -s tests

Integration tests serve tiny PNGs from a local HTTP server and need the pinned
gallery-dl; set TEST_GALLERY_DL=/path/to/gallery-dl or they are skipped.
"""
import base64
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import safe_download as sd  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def fake_getaddrinfo(address):
    return lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


class UrlValidation(unittest.TestCase):
    def setUp(self):
        os.environ.pop(sd.ALLOW_LOCAL_ENV, None)

    def test_accepts_public_https(self):
        self.assertEqual(sd.validate_url("https://commons.wikimedia.org/wiki/File:X.jpg"),
                         "https://commons.wikimedia.org/wiki/File:X.jpg")

    def test_rejects_unsafe(self):
        for url in ["file:///etc/passwd", "ftp://example.com/a.jpg", "http://localhost/a.jpg",
                    "http://127.0.0.1/a.jpg", "http://192.168.1.5/a.jpg", "http://[::1]/a.jpg",
                    "http://169.254.169.254/latest/meta-data", "https://user:pw@example.com/a.jpg",
                    "https://example.com/a.jpg;rm -rf ~", "https://printer.local/a.jpg",
                    "https://router.home.arpa/a.jpg"]:
            with self.assertRaises(sd.WrapperError, msg=url):
                sd.validate_url(url)

    def test_hostname_resolving_to_private_address_is_refused(self):
        for private in ["127.0.0.1", "10.0.0.8", "192.168.1.1", "169.254.169.254"]:
            with mock.patch.object(sd.socket, "getaddrinfo", fake_getaddrinfo(private)):
                with self.assertRaises(sd.WrapperError, msg=private):
                    sd.resolve_host("https://looks-public.example.com/a.jpg")

    def test_hostname_resolving_to_public_address_is_allowed(self):
        with mock.patch.object(sd.socket, "getaddrinfo", fake_getaddrinfo("93.184.216.34")):
            self.assertEqual(sd.resolve_host("https://example.com/a.jpg")["addresses"], ["93.184.216.34"])

    def test_unresolvable_host_is_recorded_not_refused(self):
        with mock.patch.object(sd.socket, "getaddrinfo", side_effect=socket.gaierror("no dns")):
            self.assertEqual(sd.resolve_host("https://example.com/a.jpg")["addresses"], [])


class CommandBuilding(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.run = self.out / "runs" / "r1"

    def test_download_command_is_locked_down(self):
        cmd = sd.build_command("gdl", "download", self.out, self.run, ["https://example.com/a.jpg"], 5, 2.0,
                               "2M", "50M", None)
        for required in ["--config-ignore", "--no-input", "--write-metadata", "--download-archive", "--limit-rate",
                         "--filesize-max", "--sleep-request"]:
            self.assertIn(required, cmd)
        self.assertEqual(cmd[cmd.index("--range") + 1], "1-5")
        self.assertEqual(cmd[cmd.index("--destination") + 1], str(self.run / "files"))
        for banned in ["-U", "--update", "--cookies-from-browser", "--exec", "--exec-after", "-c", "--config"]:
            self.assertNotIn(banned, cmd)
        self.assertEqual(cmd[-2:], ["--", "https://example.com/a.jpg"])

    def test_metadata_mode_saves_nothing(self):
        cmd = sd.build_command("gdl", "metadata", self.out, self.run, ["https://example.com/a.jpg"], 3, 2.0,
                               "2M", "50M", None)
        self.assertIn("--dump-json", cmd)
        self.assertNotIn("--destination", cmd)

    def test_cookie_path_redacted(self):
        cmd = sd.build_command("gdl", "download", self.out, self.run, ["https://example.com/a.jpg"], 3, 2.0,
                               "2M", "50M", Path("/secret/cookies.txt"))
        self.assertNotIn("/secret/cookies.txt", json.dumps(sd.redact_command(cmd)))


class FolderGuards(unittest.TestCase):
    def test_refuses_nonempty_foreign_folder(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "important.txt").write_text("keep me")
        with self.assertRaises(sd.WrapperError):
            sd.prepare_out_dir(folder)

    def test_refuses_home(self):
        with self.assertRaises(sd.WrapperError):
            sd.prepare_out_dir(Path.home())

    def test_refuses_symlinked_output_folder(self):
        target = Path(tempfile.mkdtemp())
        link = Path(tempfile.mkdtemp()) / "out"
        link.symlink_to(target)
        with self.assertRaises(sd.WrapperError):
            sd.prepare_out_dir(link)

    def test_refuses_symlinked_runs_or_marker_inside(self):
        for name in ("runs", sd.MARKER, "manifest.json", ".download-archive.sqlite3"):
            out = Path(tempfile.mkdtemp())
            if name != sd.MARKER:
                (out / sd.MARKER).write_text("x")
            elsewhere = Path(tempfile.mkdtemp()) / "elsewhere"
            elsewhere.mkdir()
            (out / name).symlink_to(elsewhere)
            with self.assertRaises(sd.WrapperError, msg=name):
                sd.prepare_out_dir(out)

    def test_each_run_gets_a_fresh_folder(self):
        out = sd.prepare_out_dir(Path(tempfile.mkdtemp()) / "out")
        a, b = sd.new_run_dir(out), sd.new_run_dir(out)
        self.assertNotEqual(a, b)
        self.assertTrue(a.is_dir() and b.is_dir())

    def test_collect_ignores_symlinked_files(self):
        out = sd.prepare_out_dir(Path(tempfile.mkdtemp()) / "out")
        run = sd.new_run_dir(out)
        (run / "files").mkdir()
        outside = Path(tempfile.mkdtemp()) / "secret.png"
        outside.write_bytes(PNG)
        (run / "files" / "link.png").symlink_to(outside)
        (run / "files" / "real.png").write_bytes(PNG)
        items = sd.collect_files(run, out)
        self.assertEqual([i["file"].split("/")[-1] for i in items], ["real.png"])
        self.assertEqual(items[0]["input_url"], "UNKNOWN")

    def test_cli_refuses_too_many_files(self):
        out = tempfile.mkdtemp()
        self.assertEqual(sd.main(["--mode", "download", "--max-files", "500", "--out", out,
                                  "https://example.com/a.jpg"]), 2)


class Parsing(unittest.TestCase):
    def test_parse_dump_json(self):
        stdout = json.dumps([[2, {"category": "x"}], [3, "https://example.com/a.jpg",
                                                        {"category": "directlink", "author": "A", "license": "CC BY 4.0"}],
                             [6, "https://example.com/child", {}]])
        found, errors = sd.parse_dump_json(stdout)
        self.assertEqual(errors, [])
        self.assertEqual(found[0]["media_url"], "https://example.com/a.jpg")
        self.assertEqual(found[0]["license"], "CC BY 4.0")
        self.assertEqual(found[1]["queued_url"], "https://example.com/child")

    def test_blocked_run_is_not_reported_as_success(self):
        stdout = json.dumps([[-1, {"error": "HttpError", "message": " ProxyError: 403 Forbidden"}]])
        found, errors = sd.parse_dump_json(stdout)
        self.assertEqual(found, [])
        self.assertEqual(sd.outcome(0, 0, errors, ""), "ACCESS_BLOCKED")

    def test_outcome_states(self):
        self.assertEqual(sd.outcome(0, 3, [], ""), "OK")
        self.assertEqual(sd.outcome(1, 2, ["HttpError: 500"], ""), "PARTIAL")
        self.assertEqual(sd.outcome(1, 0, ["HttpError: 500 Server Error"], ""), "FAILED")
        self.assertEqual(sd.outcome(0, 0, [], ""), "NOTHING_FOUND")
        self.assertEqual(sd.outcome(0, 0, [], "", skipped=2), "NOTHING_NEW")
        self.assertEqual(sd.outcome(1, 0, [], "[instagram][error] login required"), "ACCESS_BLOCKED")


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gdl = os.environ.get("TEST_GALLERY_DL")
        if not cls.gdl:
            raise unittest.SkipTest("TEST_GALLERY_DL not set")
        cls.root = Path(tempfile.mkdtemp())
        for i in range(6):
            (cls.root / f"p{i}.png").write_bytes(PNG + bytes([i]))
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(cls.root), **k)
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        os.environ[sd.ALLOW_LOCAL_ENV] = "1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop(sd.ALLOW_LOCAL_ENV, None)

    def run_tool(self, *args):
        return sd.main(["--gallery-dl", self.gdl, "--sleep-request", "1", *args])

    def manifest(self, out):
        return json.loads((out / "manifest.json").read_text())

    def test_metadata_then_download(self):
        out = Path(tempfile.mkdtemp()) / "run"
        url = f"{self.base}/p0.png"
        self.assertEqual(self.run_tool("--mode", "metadata", "--out", str(out), url), 0)
        manifest = self.manifest(out)
        self.assertEqual(manifest["found"][0]["media_url"], url)
        self.assertEqual(manifest["outcome"], "OK")
        self.assertEqual(self.run_tool("--mode", "download", "--out", str(out), url), 0)
        manifest = self.manifest(out)
        self.assertEqual(len(manifest["files"]), 1)
        self.assertEqual(manifest["files"][0]["rights_status"], "NOT_CLEARED")
        self.assertEqual(manifest["files"][0]["bytes"], len(PNG) + 1)
        self.assertTrue((out / manifest["run_folder"] / "manifest.md").exists())

    def test_stale_files_from_earlier_run_are_not_counted(self):
        # Reproduces the reported defect: a failed second run must not report earlier files.
        out = Path(tempfile.mkdtemp()) / "run"
        self.assertEqual(self.run_tool("--mode", "download", "--out", str(out), f"{self.base}/p1.png"), 0)
        code = self.run_tool("--mode", "download", "--out", str(out), "http://127.0.0.1:9/missing.png")
        manifest = self.manifest(out)
        self.assertEqual(code, 1)
        self.assertEqual(manifest["files"], [])
        self.assertIn(manifest["outcome"], ("ACCESS_BLOCKED", "FAILED"))

    def test_repeat_download_is_nothing_new(self):
        out = Path(tempfile.mkdtemp()) / "run"
        url = f"{self.base}/p2.png"
        self.assertEqual(self.run_tool("--mode", "download", "--out", str(out), url), 0)
        self.assertEqual(self.run_tool("--mode", "download", "--out", str(out), url), 1)
        manifest = self.manifest(out)
        self.assertEqual(manifest["outcome"], "NOTHING_NEW")
        self.assertEqual(manifest["files"], [])
        self.assertEqual(len(manifest["already_downloaded"]), 1)
        self.assertEqual(manifest["already_downloaded"][0]["input_url"], url)

    def test_file_limit_applies_across_urls(self):
        out = Path(tempfile.mkdtemp()) / "run"
        urls = [f"{self.base}/p{i}.png" for i in range(5)]
        self.run_tool("--mode", "download", "--max-files", "2", "--out", str(out), *urls)
        manifest = self.manifest(out)
        self.assertEqual(len(manifest["files"]), 2)
        self.assertTrue(manifest["capped"])

    def test_each_file_records_its_own_input_url(self):
        out = Path(tempfile.mkdtemp()) / "run"
        urls = [f"{self.base}/p{i}.png" for i in (3, 4, 5)]
        self.assertEqual(self.run_tool("--mode", "download", "--out", str(out), *urls), 0)
        files = self.manifest(out)["files"]
        self.assertEqual(len(files), 3)
        for item in files:
            stem = item["file"].rsplit("__", 1)[-1]  # directlink names files <host>__<name>
            self.assertEqual(item["input_url"], f"{self.base}/{stem}", item)
        self.assertEqual(sorted(i["input_url"] for i in files), sorted(urls))
        self.assertIn(urls[0], (out / "manifest.md").read_text())

    def test_metadata_entries_record_input_url(self):
        out = Path(tempfile.mkdtemp()) / "run"
        urls = [f"{self.base}/p3.png", f"{self.base}/p4.png"]
        self.assertEqual(self.run_tool("--mode", "metadata", "--out", str(out), *urls), 0)
        found = self.manifest(out)["found"]
        self.assertEqual([(e["input_url"], e["media_url"]) for e in found], [(u, u) for u in urls])

    def test_unreachable_host_is_flagged(self):
        out = Path(tempfile.mkdtemp()) / "run"
        code = self.run_tool("--mode", "download", "--out", str(out), "http://127.0.0.1:9/missing.png")
        self.assertEqual(code, 1)
        self.assertIn(self.manifest(out)["outcome"], ("ACCESS_BLOCKED", "FAILED"))


if __name__ == "__main__":
    unittest.main()

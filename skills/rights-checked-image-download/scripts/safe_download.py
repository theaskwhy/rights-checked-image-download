#!/usr/bin/env python3
"""Rights-Checked Image Download: run gallery-dl with safe, fixed options and write a source manifest.

Usage:
  safe_download.py --check
  safe_download.py --mode metadata --out DIR URL [URL ...]
  safe_download.py --mode urls     --out DIR URL [URL ...]
  safe_download.py --mode download --out DIR [--max-files N] [--cookies FILE] URL [URL ...]

The wrapper never self-updates gallery-dl, never reads browser cookies, ignores all
gallery-dl config files (so no exec post-processors run) and records every file as
rights_status NOT_CLEARED. It makes network requests only through gallery-dl.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

PINNED_VERSION = "1.32.19"
DEFAULT_MAX_FILES = 25
HARD_MAX_FILES = 100
DEFAULT_SLEEP = 2.0
DEFAULT_RATE = "2M"
DEFAULT_FILESIZE_MAX = "50M"
RUN_TIMEOUT_SECONDS = 900
MARKER = ".rights-image-download"
PROTECTED_NAMES = (MARKER, "runs", "manifest.json", "manifest.md", ".download-archive.sqlite3")
# Tests-only escape hatch so the suite can use a local HTTP server.
ALLOW_LOCAL_ENV = "RIGHTS_IMAGE_DOWNLOAD_ALLOW_LOCAL_FOR_TESTS"
META_KEYS = ("category", "subcategory", "title", "description", "date", "author", "username",
             "uploader", "user", "owner", "license", "license_name", "license_url", "copyright",
             "credit", "post_url", "url", "width", "height", "extension")


class WrapperError(Exception):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def find_gallery_dl(explicit: str | None) -> str | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path.home() / ".local" / "tools" / "gallery-dl" / "bin" / "gallery-dl")
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    if explicit:
        return None
    return shutil.which("gallery-dl")


def gallery_dl_version(executable: str) -> str:
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=60)
    return (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr) else ""


def _non_global(address: str) -> bool:
    return not ipaddress.ip_address(address.split("%")[0]).is_global


def validate_url(raw: str) -> str:
    """Check the *starting* URL only. gallery-dl follows HTTP redirects itself, so a
    public URL that redirects to a private address is not caught here (see SKILL.md)."""
    url = raw.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise WrapperError(f"Only http(s) URLs are allowed: {raw!r}")
    if not parts.hostname or parts.username or parts.password:
        raise WrapperError(f"URL must have a host and no embedded credentials: {raw!r}")
    host = parts.hostname.lower().rstrip(".")
    allow_local = os.environ.get(ALLOW_LOCAL_ENV) == "1"
    local_names = host in ("localhost",) or host.endswith((".local", ".localhost", ".internal", ".lan", ".home.arpa"))
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if not allow_local and (local_names or (address is not None and not address.is_global)):
        raise WrapperError(f"Local, private or reserved addresses are not allowed: {raw!r}")
    if re.search(r"[\s\"'`$;|&<>]", url):
        raise WrapperError(f"URL contains characters that are not allowed: {raw!r}")
    return url


def resolve_host(url: str) -> dict:
    """Refuse a hostname that currently resolves to a private/reserved address.

    Best effort: DNS can change between this check and gallery-dl's own lookup
    (DNS rebinding), and redirects are not re-checked."""
    host = urlsplit(url).hostname.rstrip(".")
    try:
        ipaddress.ip_address(host)
        return {"host": host, "addresses": [host]}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return {"host": host, "addresses": [], "note": "did not resolve here"}
    addresses = sorted({info[4][0] for info in infos})
    if os.environ.get(ALLOW_LOCAL_ENV) != "1" and any(_non_global(a) for a in addresses):
        raise WrapperError(f"{host} resolves to a private or reserved address ({', '.join(addresses)})")
    return {"host": host, "addresses": addresses}


def prepare_out_dir(out: Path) -> Path:
    raw = out.expanduser()
    if raw.is_symlink():
        raise WrapperError(f"Output folder must not be a symlink: {raw}")
    out = raw.resolve()
    if out == Path.home().resolve() or out == Path(out.anchor):
        raise WrapperError("Choose a dedicated output folder, not your home or root folder")
    if out.exists():
        if not out.is_dir():
            raise WrapperError(f"Output path is not a folder: {out}")
        if any(out.iterdir()) and not (out / MARKER).exists():
            raise WrapperError(f"Output folder is not empty and was not created by this tool: {out}")
    for name in PROTECTED_NAMES:
        if (out / name).is_symlink():
            raise WrapperError(f"Refusing to follow a symlink inside the output folder: {out / name}")
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Created by this tool. Files here are NOT_CLEARED for publication.\n")
    return out


def new_run_dir(out: Path) -> Path:
    """Every run gets its own fresh folder, so files from earlier runs are never counted."""
    runs = out / "runs"
    if runs.is_symlink():
        raise WrapperError(f"Refusing to follow a symlink: {runs}")
    runs.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = runs / f"{stamp}-{secrets.token_hex(3)}"
    run_dir.mkdir(exist_ok=False)
    if not run_dir.resolve().is_relative_to(out):
        raise WrapperError("Run folder escaped the output folder")
    return run_dir


def base_command(executable: str, max_files: int, sleep: float) -> list[str]:
    return [executable, "--config-ignore", "--no-input", "--range", f"1-{max_files}",
            "--sleep-request", str(sleep), "--http-timeout", "30"]


def build_command(executable: str, mode: str, out: Path, run_dir: Path, urls: list[str], max_files: int,
                  sleep: float, rate: str, filesize_max: str, cookies: Path | None) -> list[str]:
    cmd = base_command(executable, max_files, sleep)
    if mode == "metadata":
        cmd.append("--dump-json")
    elif mode == "urls":
        cmd.append("--get-urls")
    elif mode == "download":
        cmd += ["--destination", str(run_dir / "files"), "--write-metadata",
                "--download-archive", str(out / ".download-archive.sqlite3"),
                "--limit-rate", rate, "--filesize-max", filesize_max]
    else:
        raise WrapperError(f"Unknown mode: {mode}")
    if cookies is not None:
        cmd += ["--cookies", str(cookies)]
    cmd.append("--")
    cmd += urls
    return cmd


def redact_command(cmd: list[str]) -> list[str]:
    redacted = []
    skip_next = False
    for part in cmd:
        if skip_next:
            redacted.append("<cookies file withheld>")
            skip_next = False
            continue
        redacted.append(part)
        if part == "--cookies":
            skip_next = True
    return redacted


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pick_metadata(meta: dict) -> dict:
    picked = {}
    for key in META_KEYS:
        value = meta.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            value = value.get("name") or value.get("username") or value.get("nick") or json.dumps(value)[:200]
        if isinstance(value, str):
            value = re.sub(r"\s+", " ", value).strip()[:500]
        picked[key] = value
    return picked


def collect_files(run_dir: Path, out: Path, origins: dict[str, str] | None = None) -> list[dict]:
    """List files saved in this run. `origins` maps a file's path (relative to `out`)
    to the input URL whose gallery-dl job produced it."""
    files_root = run_dir / "files"
    items = []
    if not files_root.exists() or files_root.is_symlink():
        return items
    root_resolved = files_root.resolve()
    for path in sorted(files_root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() == ".json" or path.name.endswith(".part"):
            continue
        if not path.resolve().is_relative_to(root_resolved):
            continue
        sidecar = Path(str(path) + ".json")
        meta = {}
        if sidecar.exists() and not sidecar.is_symlink():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        picked = pick_metadata(meta) if isinstance(meta, dict) else {}
        relative = str(path.relative_to(out))
        items.append({
            "file": relative,
            "input_url": (origins or {}).get(relative, "UNKNOWN"),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "source": picked,
            "licence_reported_by_site": picked.get("license") or picked.get("license_name") or "UNKNOWN",
            "rights_status": "NOT_CLEARED",
            "allowed_use": "Reference only until a rights review records a licence, permission or public-domain basis.",
        })
    return items


def run_gallery_dl(cmd: list[str], cwd: Path, budget: int | None) -> dict:
    """Run gallery-dl, streaming stdout so a download run can be stopped once `budget`
    new files have been reported. Lines starting with '# ' are files skipped because
    an earlier run already downloaded them."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            text=True, cwd=str(cwd), bufsize=1)
    stderr_parts: list[str] = []
    reader = threading.Thread(target=lambda: stderr_parts.append(proc.stderr.read()), daemon=True)
    reader.start()
    timer = threading.Timer(RUN_TIMEOUT_SECONDS, proc.kill)
    timer.start()
    stdout_lines, new, skipped, capped = [], [], [], False
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            stdout_lines.append(line)
            if budget is None:
                continue
            if line.startswith("# "):
                skipped.append(line[2:])
            elif line.strip() and not line.startswith(("[", "{")):
                new.append(line)
                if len(new) >= budget:
                    capped = True
                    proc.terminate()
                    break
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    finally:
        timer.cancel()
        reader.join(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()
    timed_out = not capped and proc.returncode is not None and proc.returncode < 0
    return {"exit_code": 0 if capped else (124 if timed_out else proc.returncode),
            "stdout": "\n".join(stdout_lines), "stderr": "".join(stderr_parts),
            "reported_new": new, "skipped": skipped, "capped": capped}


def parse_dump_json(stdout: str) -> tuple[list[dict], list[str]]:
    """Summarise gallery-dl --dump-json output (a JSON list of [type, ...] messages).

    Returns (entries, errors). gallery-dl exits 0 even when every request failed,
    so error messages (type -1) must be surfaced explicitly.
    """
    entries, errors = [], []
    try:
        messages = json.loads(stdout)
    except ValueError:
        return entries, (["Could not parse gallery-dl output"] if stdout.strip() else [])
    if not isinstance(messages, list):
        return entries, errors
    for message in messages:
        if not isinstance(message, list) or len(message) < 2:
            continue
        kind = message[0]
        if kind == 3 and len(message) >= 3 and isinstance(message[2], dict):  # Url message
            entries.append({"media_url": message[1], **pick_metadata(message[2])})
        elif kind == 6 and len(message) >= 2:  # Queue (child page)
            entries.append({"queued_url": message[1]})
        elif kind == -1 and isinstance(message[1], dict):  # Error
            errors.append(f"{message[1].get('error', 'Error')}: {str(message[1].get('message', '')).strip()}"[:300])
    return entries, errors


BLOCK_PATTERNS = re.compile(r"(?i)proxyerror|403|401|429|forbidden|unauthorized|too many requests|login|"
                            r"authenticat|checkpoint|rate.?limit|name or service not known|connection refused")


def outcome(exit_code: int, items: int, errors: list[str], stderr: str, skipped: int = 0) -> str:
    problems = " ".join(errors) + " " + stderr
    if items and not errors and exit_code == 0:
        return "OK"
    if items:
        return "PARTIAL"
    if skipped and not errors and exit_code == 0:
        return "NOTHING_NEW"
    if BLOCK_PATTERNS.search(problems):
        return "ACCESS_BLOCKED"
    if errors or exit_code != 0:
        return "FAILED"
    return "NOTHING_FOUND"


def write_manifest(out: Path, run_dir: Path, record: dict) -> None:
    payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    (run_dir / "manifest.json").write_text(payload, encoding="utf-8")
    (out / "manifest.json").write_text(payload, encoding="utf-8")
    lines = [
        "# Rights-Checked Image Download manifest", "",
        f"Mode: {record['mode']} | gallery-dl {record['gallery_dl_version']} | retrieved {record['finished_at']}",
        f"Sources: {', '.join(record['urls'])}",
        f"Outcome: {record['outcome']} (exit code {record['exit_code']})", "",
        "**All files are NOT_CLEARED: reference only until a rights review clears them.**", "",
    ]
    if record.get("capped"):
        lines += [f"Stopped at the {record['max_files']}-file limit for this run.", ""]
    if record.get("already_downloaded"):
        lines += [f"Already downloaded in an earlier run (not counted): {len(record['already_downloaded'])}", ""]
    if record.get("files"):
        lines += ["| File | From input URL | SHA-256 | Site-reported licence | Author | Date |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for item in record["files"]:
            src = item["source"]
            author = src.get("author") or src.get("username") or src.get("uploader") or src.get("user") or "unknown"
            lines.append(f"| {item['file']} | {item['input_url']} | `{item['sha256'][:16]}…` | {item['licence_reported_by_site']} | {author} | {src.get('date', 'unknown')} |")
    if record.get("found"):
        lines += ["", f"Items found (no files saved): {len(record['found'])}"]
        for entry in record["found"][:50]:
            lines.append(f"- {entry.get('media_url') or entry.get('queued_url')} (from {entry.get('input_url', 'UNKNOWN')})")
    if record.get("errors"):
        lines += ["", "Errors reported by gallery-dl:"] + [f"- {e}" for e in record["errors"][:10]]
    if record.get("stderr_tail"):
        lines += ["", "Tool messages (last lines):", "```", record["stderr_tail"], "```"]
    text = "\n".join(lines) + "\n"
    (run_dir / "manifest.md").write_text(text, encoding="utf-8")
    (out / "manifest.md").write_text(text, encoding="utf-8")


def tail(text: str, lines: int = 15) -> str:
    cleaned = [re.sub(r"(?i)(cookie|session|token|auth)[^\s]*\s*[:=]\s*\S+", r"\1=<redacted>", line)
               for line in text.strip().splitlines()]
    return "\n".join(cleaned[-lines:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safe gallery-dl wrapper with a source manifest.")
    parser.add_argument("urls", nargs="*", help="Public page or post URLs")
    parser.add_argument("--check", action="store_true", help="Report gallery-dl install status and exit")
    parser.add_argument("--mode", choices=("metadata", "urls", "download"), default="metadata",
                        help="metadata (default) and urls save no images; download saves files")
    parser.add_argument("--out", type=Path, help="Dedicated output folder for this run")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--sleep-request", type=float, default=DEFAULT_SLEEP)
    parser.add_argument("--limit-rate", default=DEFAULT_RATE)
    parser.add_argument("--filesize-max", default=DEFAULT_FILESIZE_MAX)
    parser.add_argument("--cookies", type=Path, help="cookies.txt from a throwaway-account browser profile (owner-approved)")
    parser.add_argument("--gallery-dl", dest="gallery_dl", help="Path to the gallery-dl executable")
    parser.add_argument("--allow-version-mismatch", action="store_true",
                        help="Run even if gallery-dl is not the pinned version (owner-approved only)")
    args = parser.parse_args(argv)

    executable = find_gallery_dl(args.gallery_dl)
    if args.check:
        if not executable:
            print(json.dumps({"installed": False, "pinned_version": PINNED_VERSION,
                              "next_step": "Ask the owner, then follow references/install.md"}))
            return 2
        version = gallery_dl_version(executable)
        print(json.dumps({"installed": True, "path": executable, "version": version,
                          "pinned_version": PINNED_VERSION, "matches_pin": version == PINNED_VERSION}))
        return 0 if version == PINNED_VERSION else 3

    try:
        if not args.urls:
            raise WrapperError("Give at least one URL")
        if not args.out:
            raise WrapperError("--out is required: use a dedicated scratch folder")
        if not 1 <= args.max_files <= HARD_MAX_FILES:
            raise WrapperError(f"--max-files must be between 1 and {HARD_MAX_FILES}")
        if args.sleep_request < 1:
            raise WrapperError("--sleep-request must be at least 1 second")
        if not re.fullmatch(r"\d+(\.\d+)?[kKmM]?", args.limit_rate) or not re.fullmatch(r"\d+(\.\d+)?[kKmMgG]?", args.filesize_max):
            raise WrapperError("--limit-rate / --filesize-max must look like 500k, 2M or 50M")
        urls = [validate_url(u) for u in args.urls]
        if len(urls) > HARD_MAX_FILES:
            raise WrapperError(f"Too many URLs in one run (max {HARD_MAX_FILES})")
        resolution = [resolve_host(u) for u in urls]
        cookies = None
        if args.cookies is not None:
            cookies = args.cookies.expanduser().resolve()
            if not cookies.is_file():
                raise WrapperError(f"Cookies file not found: {cookies}")
        if not executable:
            raise WrapperError("gallery-dl is not installed. Ask the owner, then follow references/install.md")
        version = gallery_dl_version(executable)
        if version != PINNED_VERSION and not args.allow_version_mismatch:
            raise WrapperError(f"gallery-dl {version!r} is not the pinned {PINNED_VERSION}; see references/install.md")
        out = prepare_out_dir(args.out)
        run_dir = new_run_dir(out)
    except WrapperError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2

    started = now_iso()
    budget = args.max_files
    commands, errors, found, stderr_all = [], [], [], []
    exit_codes, skipped, capped = [], [], False
    # One gallery-dl process per URL, with the remaining budget, so the file limit
    # applies to the whole run rather than to each URL.
    origins: dict[str, str] = {}
    for url in urls:
        if budget <= 0:
            capped = True
            break
        cmd = build_command(executable, args.mode, out, run_dir, [url], budget, args.sleep_request,
                            args.limit_rate, args.filesize_max, cookies)
        commands.append(redact_command(cmd))
        result = run_gallery_dl(cmd, run_dir, budget if args.mode == "download" else None)
        exit_codes.append(result["exit_code"])
        stderr_all.append(result["stderr"])
        if args.mode == "metadata":
            entries, errs = parse_dump_json(result["stdout"])
            found += [{"input_url": url, **entry} for entry in entries]
            errors += [f"{url}: {err}" for err in errs]
            budget -= len([e for e in entries if "media_url" in e])
        elif args.mode == "urls":
            entries = [{"input_url": url, "media_url": line.strip()} for line in result["stdout"].splitlines() if line.strip()]
            found += entries
            budget -= len(entries)
        else:
            skipped += [{"input_url": url, "earlier_file": path} for path in result["skipped"]]
            # Every file that appeared during this URL's job came from this URL.
            for item in collect_files(run_dir, out):
                origins.setdefault(item["file"], url)
            capped = capped or result["capped"]
            budget = args.max_files - len(collect_files(run_dir, out))
    exit_code = next((code for code in exit_codes if code), 0)
    stderr = "\n".join(s for s in stderr_all if s)

    record = {
        "tool": "rights-checked-image-download", "mode": args.mode, "urls": urls, "resolution": resolution,
        "gallery_dl_version": version, "commands": commands, "run_folder": str(run_dir.relative_to(out)),
        "max_files": args.max_files, "cookies_used": cookies is not None,
        "started_at": started, "finished_at": now_iso(), "exit_code": exit_code,
        "stderr_tail": tail(stderr), "capped": capped,
        "limits": "Starting URLs and their DNS were checked; HTTP redirects followed by gallery-dl were not.",
    }
    if args.mode in ("metadata", "urls"):
        record["found"] = found[: args.max_files]
        count = len(record["found"])
    else:
        record["files"] = collect_files(run_dir, out, origins)
        record["already_downloaded"] = skipped
        count = len(record["files"])
    record["errors"] = errors
    record["outcome"] = outcome(exit_code, count, errors, stderr, len(skipped))
    write_manifest(out, run_dir, record)
    print(json.dumps({"outcome": record["outcome"], "exit_code": exit_code, "mode": args.mode, "items": count,
                      "capped": capped, "errors": errors[:3], "manifest": str(run_dir / "manifest.md"),
                      "rights_status": "NOT_CLEARED"}))
    return 0 if record["outcome"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())

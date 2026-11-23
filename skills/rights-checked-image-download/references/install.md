# Installing gallery-dl (explicit approval required)

Install only after explicit approval, and only this pinned, hash-checked version. Do not use `gallery-dl -U`, the standalone executable's self-updater, Homebrew `latest`, or the unpinned `pip install -U gallery-dl` from the upstream README.

Pinned release: **gallery-dl 1.32.19** (PyPI wheel `gallery_dl-1.32.19-py3-none-any.whl`)
SHA-256: `f6b1eb5e9a7409a988b754335d99dbb1873e130d133ed5d164d32e5e645d1c50`
Licence: GPL-2.0 (fine to use as a tool; do not bundle its code into a proprietary product).
Upstream: development moved from GitHub (`mikf/gallery-dl`, now a mirror) to Codeberg (`codeberg.org/mikf/gallery-dl`).

## macOS / Linux, isolated in its own folder

```bash
mkdir -p ~/.local/tools && cd ~/.local/tools
python3 -m pip download --no-deps "gallery-dl==1.32.19" -d gdl-wheel
shasum -a 256 gdl-wheel/gallery_dl-1.32.19-py3-none-any.whl   # Linux: sha256sum
# Continue ONLY if it prints f6b1eb5e9a7409a988b754335d99dbb1873e130d133ed5d164d32e5e645d1c50
python3 -m venv ~/.local/tools/gallery-dl
~/.local/tools/gallery-dl/bin/pip install gdl-wheel/gallery_dl-1.32.19-py3-none-any.whl
~/.local/tools/gallery-dl/bin/gallery-dl --version   # expect 1.32.19
```

The wrapper looks for `gallery-dl` at `~/.local/tools/gallery-dl/bin/gallery-dl` first, then on `PATH`. Pass `--gallery-dl PATH` to point it elsewhere.

Nothing here changes system Python, shell profiles or browser data. To remove it, delete `~/.local/tools/gallery-dl` and `~/.local/tools/gdl-wheel` (after explicit approval).

## Upgrading later

Treat an upgrade like a new install: read the changelog, download the new wheel, record its SHA-256 here, update `PINNED_VERSION` in `scripts/safe_download.py`, and rerun `tests/`.

## Video

Video is out of scope. gallery-dl hands some video to yt-dlp if it is installed; the wrapper does not install or call yt-dlp.

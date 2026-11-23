---
name: rights-checked-image-download
description: Safely retrieve a small, bounded set of images from a specific public URL when official image sources cannot provide them. Creates source manifests; downloads remain uncleared until a separate rights review.
---

# Rights-Checked Image Download

Retrieve image files and source metadata from a specific public URL when official image APIs cannot provide the needed material. This is a retrieval tool, not a licensing tool: downloaded files carry no right to publish.

## When to use

- Prefer official sources and APIs that expose rights metadata, such as Wikimedia Commons, Openverse, NASA, DVIDS, or appropriately filtered image libraries.
- Use this fallback only when a user names a specific public page or explicitly asks to retrieve from a URL.
- For social post reading without saving images, use a general social research workflow. For any intended publication, complete your rights-review step; this tool only supplies candidate files and provenance.
- Never use for bulk account archiving, private or paywalled material, or content behind a login without explicit authorization.

## Always use the wrapper

Run `scripts/safe_download.py`; never call `gallery-dl` directly. The wrapper:

- accepts public `http(s)` starting URLs and rejects hosts resolving to local/private addresses. This is best effort for the initial URL only; redirects and DNS changes are not fully covered. Use only trusted URLs;
- ignores gallery-dl config files, preventing hidden configured post-processors;
- never self-updates and never reads browser cookies. Cookies can be supplied only from a separate, explicitly authorized research profile;
- defaults to 25 files per run, with a hard maximum of 100, sleeps between requests, and limits bandwidth and file size;
- creates a new run folder for each invocation and does not count earlier downloads as new;
- refuses symlinked output folders and does not follow symlinks inside them;
- writes `manifest.json` and `manifest.md` with source URL, filename, SHA-256, size, retrieval time, and available author/date/licence metadata. Every item is `NOT_CLEARED`.

## Workflow

1. Check availability with `python3 scripts/safe_download.py --check`. If gallery-dl is missing or the version differs from the pinned version, read `references/install.md`. Do not install software without explicit approval.
2. Start with metadata only: `--mode metadata`. Review the returned items before saving files.
3. Download only the smallest useful set with `--mode download --max-files N`, into a dedicated scratch directory outside project folders.
4. Report the manifest outcome (`OK`, `PARTIAL`, `ACCESS_BLOCKED`, `FAILED`, `NOTHING_NEW`, or `NOTHING_FOUND`), source links, and `rights_status`. State that files are reference-only.
5. Before publication, use an independent rights-review step. Do not import, upload, or publish the downloads automatically.

```bash
python3 scripts/safe_download.py --check
python3 scripts/safe_download.py --mode metadata --out ~/image-research/job-001 "https://commons.wikimedia.org/wiki/File:Example.jpg"
python3 scripts/safe_download.py --mode download --max-files 5 --out ~/image-research/job-001 "<url>"
```

## Logins and hard rules

Some social services require login. Read `references/platforms.md` first. Use `--cookies FILE` only with a cookies file exported from a separate research profile after explicit approval for that site and task. Never use a personal or primary work account, export cookies from a main browser profile, or paste credentials into chat.

- No paid proxies, services, or upgrades without explicit approval.
- Never run `gallery-dl -U`, `--cookies-from-browser`, `--exec`, or an unread config file.
- Respect site terms and rate limits. Stop on 429 responses or login walls; do not retry around them.
- Never delete files outside this run's output directory.
- Downloaded does not mean licensed. Keep every item `NOT_CLEARED` until a rights review records permission, licence, or public-domain basis.

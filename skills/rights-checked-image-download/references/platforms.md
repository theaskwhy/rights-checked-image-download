# Platform notes (gallery-dl 1.32.19)

| Platform | What it can fetch | Login | Notes |
|---|---|---|---|
| Wikimedia Commons | Files, categories | None | Prefer the Commons API; it returns licence fields |
| Bluesky | Posts, media, profiles | None | Public posts only |
| Flickr | Images, albums, search | Optional OAuth | Prefer the Flickr API with a Creative Commons licence filter |
| Reddit | Submission images, galleries | Optional OAuth | Public posts; many images are hosted on i.redd.it or imgur |
| imgur | Albums, images | None | |
| Instagram | Posts, Reels, highlights | Cookies | Frequently blocks automated access |
| Facebook | Photos, albums | Cookies | Public pages vary |
| X / Twitter | Post media | Cookies | |
| TikTok | Post images/slideshows | Cookies | Video is out of scope |
| Pinterest | Pins | Cookies | |

## If a login is truly needed

1. Ask the owner for approval for that specific site and task.
2. Use a **separate browser profile** signed into a **throwaway account** created for research. Never use a personal or primary work account.
3. Export that profile's cookies for the one site to a `cookies.txt` (Netscape format) file kept outside project folders.
4. Pass it with `--cookies /path/to/cookies.txt`. Never paste cookie values into chat, commit them, or put them in a manifest.
5. Delete the cookies file when the task is done (with the owner's approval).

Platforms prohibit scraping in their terms and can restrict accounts that look automated. Keep runs small and occasional. Stop on 429 / rate-limit or checkpoint pages; do not rotate accounts, proxies or IPs to get around them.

## Rights reminder

A file downloaded from a social post is usually someone else's copyrighted work. Files are reference-only until an independent rights-review step records a licence, permission, or public-domain basis.

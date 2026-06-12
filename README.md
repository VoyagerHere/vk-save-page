# vk-save-page

Save any VK public page (group wall) as a self-contained offline HTML archive you can browse without internet access.

## Features

- Downloads all posts with photos, videos, documents, audio, polls, and articles
- Photos open in a full-screen lightbox on click
- Video thumbnails with a play button link back to VK
- VK articles are fetched and saved as local HTML pages
- Optional audio and document file downloads
- Reposts shown with original content
- Responsive layout, works on mobile

## Requirements

- Python 3.10+
- `requests` library

```
pip install -r requirements.txt
```

## Getting a token

You need a VK API access token with `wall`, `photos`, `groups` permissions.

```
python get_token.py
```

This opens a browser authorization page. After you allow access, copy the redirect URL and paste it back into the terminal — the script will extract and print your token.

## Usage

```
python vk_save.py <group> --token <token>
```

`<group>` can be a short name, a numeric ID, or a full URL:

```
python vk_save.py typical_progger --token vk1.a.XXX
python vk_save.py https://vk.com/typical_progger --token vk1.a.XXX
```

The result is saved to `./<group>/index.html`. Open it in any browser.

## Options

| Flag | Description |
|------|-------------|
| `--token TOKEN` | VK API access token (or set `VK_TOKEN` env var) |
| `--limit N` | Save only the latest N posts (default: all) |
| `--out DIR` | Custom output directory |
| `--download-audio` | Download audio files to `audio/` (only works if the API returns a direct URL) |
| `--download-docs` | Download document attachments to `docs/` |

### Using an environment variable

```
$env:VK_TOKEN = "vk1.a.XXX"   # PowerShell
python vk_save.py kombanation
```

## Output structure

```
<group>/
  index.html        # main feed
  posts.json        # raw API data
  images/           # photos and video thumbnails
  articles/         # saved VK articles
  audio/            # downloaded audio (with --download-audio)
  docs/             # downloaded documents (with --download-docs)
```

## Notes

- VK CDN image URLs expire after some time, so photos from old posts may return 404 — this is expected and not a bug.
- VK article pages are protected by a bot check and cannot always be fetched. When blocked, the article card links back to VK instead.
- Audio direct URLs are rarely included in API responses for regular user tokens.

## License

MIT

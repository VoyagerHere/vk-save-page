#!/usr/bin/env python3
"""
VK Public Page Saver
Usage: python vk_save.py <group_domain_or_id> [--token TOKEN] [--limit N] [--out DIR]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# Fix Windows console encoding (cp1252 → utf-8)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

import requests

VK_API_VERSION = "5.199"
VK_API_BASE = "https://api.vk.com/method/"


# ─── VK API ──────────────────────────────────────────────────────────────────


def api(method: str, token: str, **params) -> dict:
    params.update({"access_token": token, "v": VK_API_VERSION})
    r = requests.get(VK_API_BASE + method, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"VK API error {data['error']['error_code']}: {data['error']['error_msg']}")
    return data["response"]


def get_group_info(token: str, domain: str) -> dict:
    resp = api(
        "groups.getById",
        token,
        group_id=domain,
        fields="description,members_count,photo_200",
    )
    return resp["groups"][0]


def get_all_posts(token: str, domain: str, limit: int | None, verbose: bool = True) -> list[dict]:
    all_posts: list[dict] = []
    offset = 0
    batch = 100

    while True:
        resp = api("wall.get", token, domain=domain, count=batch, offset=offset, extended=0)
        total = resp["count"]
        items = resp["items"]
        if not items:
            break

        all_posts.extend(items)
        offset += len(items)

        if verbose:
            print(f"  Fetched: {len(all_posts)} / {total} posts", end="\r", flush=True)

        if limit and len(all_posts) >= limit:
            all_posts = all_posts[:limit]
            break

        if offset >= total:
            break

        time.sleep(0.34)  # ~3 req/s — within VK API rate limit

    if verbose:
        print()
    return all_posts


# ─── Image downloads ──────────────────────────────────────────────────────────


def download_image(url: str, path: Path) -> bool:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        path.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"\n  [warn] Failed to download {url}: {e}", file=sys.stderr)
        return False


def best_photo_url(sizes: list[dict]) -> str:
    order = ["w", "z", "y", "x", "m", "s"]
    by_type = {s["type"]: s["url"] for s in sizes}
    for t in order:
        if t in by_type:
            return by_type[t]
    return max(sizes, key=lambda s: s.get("width", 0))["url"]


# ─── Articles ────────────────────────────────────────────────────────────────

ARTICLE_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f0f2f5;
  color: #1a1a1a;
  line-height: 1.8;
}
a { color: #4a76a8; text-decoration: none; }
a:hover { text-decoration: underline; }
.article-wrap {
  max-width: 720px;
  margin: 0 auto;
  background: #fff;
  padding: 32px 24px 60px;
}
.article-back {
  display: inline-block;
  margin-bottom: 24px;
  color: #4a76a8;
  font-size: 0.9rem;
}
.article-cover { width: 100%; border-radius: 8px; margin-bottom: 24px; display: block; }
h1.article-title { font-size: 1.7rem; margin-bottom: 8px; }
.article-subtitle { color: #666; font-size: 1.05rem; margin-bottom: 24px; }
.article-body h2 { font-size: 1.35rem; margin: 28px 0 10px; }
.article-body h3 { font-size: 1.15rem; margin: 22px 0 8px; }
.article-body h4 { font-size: 1rem; margin: 18px 0 6px; }
.article-body p { margin: 12px 0; }
.article-body ul, .article-body ol { margin: 12px 0 12px 24px; }
.article-body li { margin: 4px 0; }
.article-body blockquote {
  border-left: 3px solid #4a76a8;
  margin: 16px 0;
  padding: 8px 16px;
  color: #444;
  font-style: italic;
}
.article-body hr { border: none; border-top: 1px solid #e0e0e0; margin: 24px 0; }
.article-body figure { margin: 16px 0; }
.article-body figure img { max-width: 100%; border-radius: 6px; display: block; }
.article-body figcaption { font-size: 0.82rem; color: #888; margin-top: 6px; }
.article-body .columns { display: flex; gap: 16px; }
.article-body .column { flex: 1; }
.article-fallback {
  background: #fff8e1;
  border: 1px solid #ffe082;
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 0.9rem;
  color: #555;
  margin-top: 16px;
}
@media (max-width: 480px) {
  .article-wrap { padding: 16px 12px 40px; }
  h1.article-title { font-size: 1.3rem; }
  .article-body .columns { flex-direction: column; }
}
"""


def _find_blocks(obj, depth: int = 0):
    if depth > 12:
        return None
    if isinstance(obj, dict):
        if "blocks" in obj and isinstance(obj.get("blocks"), list) and len(obj["blocks"]) > 2:
            return obj["blocks"]
        for v in obj.values():
            r = _find_blocks(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _find_blocks(item, depth + 1)
            if r:
                return r
    return None


def _render_rich_text(node) -> str:
    if isinstance(node, str):
        return escape(node)
    if isinstance(node, list):
        parts = []
        for chunk in node:
            if isinstance(chunk, str):
                parts.append(escape(chunk))
            elif isinstance(chunk, dict):
                text = escape(chunk.get("text", ""))
                link = chunk.get("link", "")
                bold = chunk.get("bold", False)
                italic = chunk.get("italic", False)
                if link:
                    text = f'<a href="{escape(link)}">{text}</a>'
                if bold:
                    text = f"<strong>{text}</strong>"
                if italic:
                    text = f"<em>{text}</em>"
                parts.append(text)
        return "".join(parts)
    return ""


def render_article_blocks(blocks: list, images_dir: Path, slug: str) -> str:
    counter = [0]
    out = []

    def img_html(photo: dict) -> str:
        sizes = photo.get("sizes", [])
        if not sizes:
            return ""
        url = best_photo_url(sizes)
        fname = f"art_{slug}_{counter[0]}.jpg"
        counter[0] += 1
        fpath = images_dir / fname
        if download_image(url, fpath):
            return f'<img src="../images/{fname}" loading="lazy">'
        return f'<a href="{url}" target="_blank">[photo]</a>'

    def render_block(b: dict) -> str:
        t = b.get("type", "")

        if t == "paragraph":
            text = _render_rich_text(b.get("text", ""))
            return f"<p>{text}</p>" if text.strip() else ""

        if t == "header":
            level = min(max(b.get("level", 2), 2), 4)
            text = _render_rich_text(b.get("text", ""))
            return f"<h{level}>{text}</h{level}>"

        if t == "photo":
            photo = b.get("photo", {})
            img = img_html(photo)
            caption = escape(b.get("caption", ""))
            return f"<figure>{img}<figcaption>{caption}</figcaption></figure>" if img else ""

        if t == "quote":
            text = _render_rich_text(b.get("text", ""))
            author = escape(b.get("author", ""))
            author_html = f"<footer>— {author}</footer>" if author else ""
            return f"<blockquote>{text}{author_html}</blockquote>"

        if t in ("unordered_list", "list"):
            items = b.get("items", [])
            li = "".join(f"<li>{_render_rich_text(i.get('text', i) if isinstance(i, dict) else i)}</li>" for i in items)
            return f"<ul>{li}</ul>"

        if t == "ordered_list":
            items = b.get("items", [])
            li = "".join(f"<li>{_render_rich_text(i.get('text', i) if isinstance(i, dict) else i)}</li>" for i in items)
            return f"<ol>{li}</ol>"

        if t == "divider":
            return "<hr>"

        if t == "columns":
            cols = b.get("columns", [])
            cols_html = "".join(
                f'<div class="column">{"".join(render_block(cb) for cb in col.get("blocks", []))}</div>'
                for col in cols
            )
            return f'<div class="columns">{cols_html}</div>'

        if t == "audio":
            audio = b.get("audio", {})
            artist = escape(audio.get("artist", ""))
            title = escape(audio.get("title", "Audio"))
            owner_id = audio.get("owner_id", "")
            audio_id = audio.get("id", "")
            url = f"https://vk.com/audio{owner_id}_{audio_id}"
            return f'<p>🎵 <a href="{url}" target="_blank">{artist} — {title}</a></p>'

        if t == "video":
            v = b.get("video", {})
            title = escape(v.get("title", "Video"))
            vid_id = f"{v.get('owner_id', '')}_{v.get('id', '')}"
            url = f"https://vk.com/video{vid_id}"
            return f'<p>🎬 <a href="{url}" target="_blank">{title}</a></p>'

        if t == "link":
            url = escape(b.get("url", "#"))
            text = escape(b.get("title", url))
            return f'<p><a href="{url}" target="_blank">{text}</a></p>'

        return ""

    for block in blocks:
        html = render_block(block)
        if html:
            out.append(html)

    return "\n".join(out)


def fetch_article(
    vk_url: str,
    article_slug: str,
    output_dir: Path,
    images_dir: Path,
    cover_html: str = "",
    title: str = "",
    subtitle: str = "",
) -> str | None:
    """Download a VK article page and save it as a standalone HTML file."""
    import re

    articles_dir = output_dir / "articles"
    articles_dir.mkdir(exist_ok=True)
    out_file = articles_dir / f"{article_slug}.html"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }

    try:
        r = requests.get(vk_url, headers=headers, timeout=25)
        r.raise_for_status()
        enc = r.apparent_encoding or "utf-8"
        page_html = r.content.decode(enc, errors="replace")
    except Exception as e:
        print(f"\n  [warn] Failed to load article {vk_url}: {e}", file=sys.stderr)
        return None

    # Detect bot-check / captcha page
    if '<html lang="en">' in page_html or "CheckYou" in page_html or len(r.content) < 50_000:
        is_bot_check = (
            "CheckYou" in page_html
            or "captcha" in page_html.lower()
            or ('lang="en"' in page_html and len(r.content) < 50_000)
        )
        if is_bot_check:
            print(f"\n  [warn] VK returned a captcha for {vk_url}", file=sys.stderr)
            return None

    time.sleep(1.5)  # pause between article requests to avoid rate limiting

    # Search for __INITIAL_STATE__ in page scripts
    state = None
    for pattern in [
        r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*(?:;|</script>)',
        r'__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;',
    ]:
        m = re.search(pattern, page_html, re.DOTALL)
        if m:
            try:
                state = json.loads(m.group(1))
                break
            except json.JSONDecodeError:
                pass

    body_html = ""

    if state:
        blocks = _find_blocks(state)
        if blocks:
            body_html = render_article_blocks(blocks, images_dir, article_slug)

    if not body_html:
        # Fallback: extract text from HTML tags
        text_chunks = re.findall(
            r'<(?:p|li|h[1-4]|blockquote)[^>]*>(.*?)</(?:p|li|h[1-4]|blockquote)>',
            page_html, re.DOTALL
        )
        clean = [re.sub(r'<[^>]+>', '', c).strip() for c in text_chunks]
        clean = [c for c in clean if len(c) > 20]
        if clean:
            body_html = "\n".join(f"<p>{escape(c)}</p>" for c in clean[:200])

    fallback = ""
    if not body_html:
        fallback = (
            f'<div class="article-fallback">⚠️ Could not extract article content. '
            f'<a href="{vk_url}" target="_blank">Open in VK</a></div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<style>{ARTICLE_CSS}</style>
</head>
<body>
<div class="article-wrap">
  <a class="article-back" href="../index.html">← Back to posts</a>
  {cover_html}
  <h1 class="article-title">{escape(title)}</h1>
  {f'<div class="article-subtitle">{escape(subtitle)}</div>' if subtitle else ""}
  <div class="article-body">{body_html}</div>
  {fallback}
</div>
</body>
</html>"""

    out_file.write_text(html, encoding="utf-8")
    return f"articles/{article_slug}.html"


# ─── HTML generation ──────────────────────────────────────────────────────────


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def text_to_html(text: str) -> str:
    import re
    text = escape(text)
    text = re.sub(r"\[([^|]+)\|([^\]]+)\]", r'<a href="https://vk.com/\1">\2</a>', text)
    text = re.sub(r"https?://\S+", lambda m: f'<a href="{m.group()}">{m.group()}</a>', text)
    return text.replace("\n", "<br>")


def render_attachments(
    attachments: list[dict],
    images_dir: Path,
    output_dir: Path,
    post_id,
    download_audio: bool = False,
    download_docs: bool = False,
) -> str:
    parts: list[str] = []

    for i, att in enumerate(attachments):
        t = att["type"]

        if t == "photo":
            sizes = att["photo"].get("sizes", [])
            if not sizes:
                continue
            url = best_photo_url(sizes)
            fname = f"p{post_id}_{i}.jpg"
            fpath = images_dir / fname
            if download_image(url, fpath):
                parts.append(f'<img src="images/{fname}" class="att-img" loading="lazy">')
            else:
                parts.append(f'<a href="{url}" target="_blank" class="att-link">[photo]</a>')

        elif t == "video":
            v = att["video"]
            title = escape(v.get("title", "Video"))
            vid_id = f"{v.get('owner_id', '')}_{v.get('id', '')}"
            link = f"https://vk.com/video{vid_id}"
            thumb = ""
            for key in ("photo_800", "photo_640", "photo_320", "photo_130"):
                if key in v:
                    fname = f"p{post_id}_{i}_vthumb.jpg"
                    fpath = images_dir / fname
                    if download_image(v[key], fpath):
                        thumb = f'<img src="images/{fname}" class="att-img">'
                    break
            parts.append(
                f'<a href="{link}" target="_blank" class="att-video">'
                f'{thumb}<span class="play-btn">▶</span>{title}</a>'
            )

        elif t == "link":
            import re as _re
            lnk = att["link"]
            raw_url = lnk.get("url", "")
            desc = lnk.get("description", "")
            title = lnk.get("title", raw_url)

            # Detect links to VK articles: vk.com/@slug or vk.com/article...
            is_article = (
                desc == "Статья"
                or _re.search(r"vk\.com/@[\w-]+", raw_url)
                or _re.search(r"vk\.com/article-?\d+_\d+", raw_url)
            )

            if is_article:
                # Normalize URL: m.vk.com → vk.com
                article_url = _re.sub(r"https?://m\.vk\.com/", "https://vk.com/", raw_url)

                # Build slug from @handle
                slug_m = _re.search(r"@([\w-]+)", article_url)
                slug = slug_m.group(1)[:80] if slug_m else f"article_{post_id}_{i}"

                cover_html = ""
                cover_card_html = ""
                photo = lnk.get("photo", {})
                if photo:
                    sizes = photo.get("sizes", [])
                    if sizes:
                        cover_url = best_photo_url(sizes)
                        fname = f"p{post_id}_{i}_cover.jpg"
                        fpath = images_dir / fname
                        if download_image(cover_url, fpath):
                            cover_card_html = f'<img src="images/{fname}" class="art-cover-img">'
                            cover_html = f'<img src="../images/{fname}" class="article-cover">'

                print(f"\n  Downloading article: {title[:50]}...", end="", flush=True)
                local_path = fetch_article(
                    article_url, slug, output_dir, images_dir,
                    cover_html=cover_html,
                    title=title,
                    subtitle=desc if desc != "Статья" else "",
                )
                print(" OK" if local_path else " failed")

                link = local_path if local_path else escape(raw_url)
                ext_icon = "" if local_path else ' <small style="color:#aaa">[VK↗]</small>'
                target = "_self" if local_path else "_blank"
                parts.append(
                    f'<a href="{link}" target="{target}" class="att-article-card">'
                    f'{cover_card_html}'
                    f'<div class="art-meta">'
                    f'<div class="art-label">📄 Article{ext_icon}</div>'
                    f'<strong>{escape(title)}</strong>'
                    + "</div></a>"
                )
            else:
                parts.append(
                    f'<a href="{escape(raw_url)}" target="_blank" class="att-link-card">'
                    f'<strong>{escape(title)}</strong>'
                    + (f"<br><small>{escape(desc)}</small>" if desc else "")
                    + "</a>"
                )

        elif t == "doc":
            doc = att["doc"]
            raw_url = doc.get("url", "")
            doc_title = doc.get("title", "Document")
            ext = doc.get("ext", "")

            if download_docs and raw_url:
                docs_dir = output_dir / "docs"
                docs_dir.mkdir(exist_ok=True)
                safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in doc_title)
                fname = f"{safe_name[:60]}.{ext}" if ext and not safe_name.endswith(f".{ext}") else safe_name[:64]
                fpath = docs_dir / fname
                if not fpath.exists() and download_image(raw_url, fpath):
                    parts.append(
                        f'<a href="docs/{fname}" class="att-doc" download>📄 {escape(doc_title)}'
                        f'<span class="att-badge">saved</span></a>'
                    )
                else:
                    parts.append(f'<a href="docs/{fname}" class="att-doc" download>📄 {escape(doc_title)}</a>')
            else:
                parts.append(
                    f'<a href="{escape(raw_url)}" target="_blank" class="att-doc">📄 {escape(doc_title)}</a>'
                )

        elif t == "audio":
            audio = att["audio"]
            artist = escape(audio.get("artist", ""))
            title = escape(audio.get("title", "Audio"))
            owner_id = audio.get("owner_id", "")
            audio_id = audio.get("id", "")
            raw_audio_url = audio.get("url", "")
            vk_url = f"https://vk.com/audio{owner_id}_{audio_id}"

            if download_audio and raw_audio_url:
                audio_dir = output_dir / "audio"
                audio_dir.mkdir(exist_ok=True)
                fname = f"{artist} - {title}"[:80].replace("/", "_").replace("\\", "_") + ".mp3"
                fpath = audio_dir / fname
                if not fpath.exists():
                    download_image(raw_audio_url, fpath)
                if fpath.exists():
                    parts.append(
                        f'<div class="att-audio-player">'
                        f'<span>🎵 {artist} — {title}</span>'
                        f'<audio controls src="audio/{fname}" preload="none" style="width:100%;margin-top:4px"></audio>'
                        f'</div>'
                    )
                else:
                    parts.append(
                        f'<a href="{vk_url}" target="_blank" class="att-audio">'
                        f'🎵 {artist} — {title} <small style="color:#aaa">(URL unavailable)</small></a>'
                    )
            else:
                parts.append(
                    f'<a href="{vk_url}" target="_blank" class="att-audio">'
                    f'🎵 {artist} — {title}</a>'
                )

        elif t == "poll":
            poll = att["poll"]
            q = escape(poll.get("question", "Poll"))
            votes = poll.get("votes", 0)
            parts.append(f'<div class="att-poll">📊 {q} ({votes} votes)</div>')

        elif t == "article":
            art = att["article"]
            art_title = art.get("title", "Article")
            art_sub = art.get("subtitle", "")
            art_url = art.get("url", "")
            views = art.get("views", 0)

            cover_html = ""
            cover_card_html = ""
            photo = art.get("photo", {})
            if photo:
                sizes = photo.get("sizes", [])
                if sizes:
                    cover_url = best_photo_url(sizes)
                    fname = f"p{post_id}_{i}_cover.jpg"
                    fpath = images_dir / fname
                    if download_image(cover_url, fpath):
                        cover_card_html = f'<img src="images/{fname}" class="art-cover-img">'
                        cover_html = f'<img src="../images/{fname}" class="article-cover">'

            slug = art_url.split("@")[-1].split("/")[-1] if art_url else f"article_{post_id}_{i}"
            slug = slug[:80]

            local_path = None
            if art_url:
                print(f"\n  Downloading article: {art_title[:50]}...", end="", flush=True)
                local_path = fetch_article(
                    art_url, slug, output_dir, images_dir,
                    cover_html=cover_html,
                    title=art_title,
                    subtitle=art_sub,
                )
                print(" OK" if local_path else " failed")

            link = local_path if local_path else art_url
            ext_icon = "" if local_path else ' <small style="color:#aaa">[VK↗]</small>'
            target = '_self' if local_path else '_blank'

            parts.append(
                f'<a href="{link}" target="{target}" class="att-article-card">'
                f'{cover_card_html}'
                f'<div class="art-meta">'
                f'<div class="art-label">📄 Article{ext_icon}</div>'
                f'<strong>{escape(art_title)}</strong>'
                + (f'<div class="art-sub">{escape(art_sub)}</div>' if art_sub else "")
                + (f'<div class="art-views">👁 {views:,}</div>' if views else "")
                + "</div></a>"
            )

    return "".join(f'<div class="att">{p}</div>' for p in parts)


def render_post(
    post: dict,
    images_dir: Path,
    output_dir: Path,
    download_audio: bool = False,
    download_docs: bool = False,
) -> str:
    pid = post["id"]
    date_str = datetime.fromtimestamp(post["date"]).strftime("%d.%m.%Y %H:%M")
    text_html = text_to_html(post.get("text", ""))
    atts_html = ""
    if "attachments" in post:
        atts_html = render_attachments(
            post["attachments"], images_dir, output_dir, pid,
            download_audio=download_audio, download_docs=download_docs,
        )

    likes = post.get("likes", {}).get("count", 0)
    reposts = post.get("reposts", {}).get("count", 0)
    views = post.get("views", {}).get("count", 0)
    comments = post.get("comments", {}).get("count", 0)

    repost_html = ""
    if post.get("copy_history"):
        orig = post["copy_history"][0]
        orig_text = text_to_html(orig.get("text", ""))
        orig_atts = ""
        if "attachments" in orig:
            orig_atts = render_attachments(
                orig["attachments"], images_dir, output_dir, f"{pid}_orig",
                download_audio=download_audio, download_docs=download_docs,
            )
        repost_html = f'<div class="repost"><div class="repost-label">🔁 Repost</div>{orig_text}{orig_atts}</div>'

    pinned = '<span class="pinned-badge">📌 Pinned</span>' if post.get("is_pinned") else ""

    return f"""
<article class="post" id="post-{pid}">
  <div class="post-header">
    <span class="post-date">{date_str}</span>{pinned}
  </div>
  <div class="post-text">{text_html}</div>
  {repost_html}
  {atts_html}
  <div class="post-stats">
    <span>❤️ {likes}</span>
    <span>💬 {comments}</span>
    <span>🔁 {reposts}</span>
    <span>👁 {views:,}</span>
  </div>
</article>"""


CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
  background: #f0f2f5;
  color: #1a1a1a;
  line-height: 1.6;
}
a { color: #4a76a8; text-decoration: none; }
a:hover { text-decoration: underline; }

.page-header {
  background: #4a76a8;
  color: white;
  padding: 24px 16px;
  text-align: center;
}
.page-header h1 { font-size: 1.6rem; margin-bottom: 4px; }
.page-header .meta { font-size: 0.85rem; opacity: 0.8; }

.feed {
  max-width: 640px;
  margin: 20px auto;
  padding: 0 12px 40px;
}

.post {
  background: #fff;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,.1);
}
.post-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.post-date { color: #999; font-size: 0.82rem; }
.pinned-badge { font-size: 0.78rem; color: #e07b39; }
.post-text { font-size: 0.97rem; }
.post-text br { display: block; content: ""; margin-top: 4px; }
.post-stats {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
  color: #888;
  font-size: 0.82rem;
}

/* Attachments */
.att { margin-top: 10px; }
.att-img {
  max-width: 100%;
  border-radius: 6px;
  display: block;
  cursor: zoom-in;
}
.att-video {
  display: block;
  position: relative;
  border-radius: 6px;
  overflow: hidden;
  color: inherit;
}
.att-video .play-btn {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 3rem;
  color: rgba(255,255,255,0.9);
  text-shadow: 0 2px 8px rgba(0,0,0,.6);
  pointer-events: none;
}
.att-link-card {
  display: block;
  background: #f7f8fa;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 10px 12px;
  color: inherit;
  font-size: 0.9rem;
}
.att-link-card:hover { background: #eff0f2; text-decoration: none; }
.att-doc, .att-audio, .att-poll {
  display: block;
  background: #f7f8fa;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.9rem;
  color: #555;
}
.att-badge {
  background: #4a76a8;
  color: white;
  font-size: 0.7rem;
  border-radius: 4px;
  padding: 1px 5px;
  margin-left: 6px;
  vertical-align: middle;
}
.att-audio-player {
  background: #f7f8fa;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.9rem;
}

/* Article card */
.att-article-card {
  display: flex;
  gap: 12px;
  background: #f7f8fa;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
  color: inherit;
  text-decoration: none;
}
.att-article-card:hover { background: #eff0f2; text-decoration: none; }
.art-cover-img { width: 120px; height: 90px; object-fit: cover; flex-shrink: 0; }
.art-meta { padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
.art-label { font-size: 0.75rem; color: #4a76a8; }
.art-meta strong { font-size: 0.95rem; }
.art-sub { font-size: 0.82rem; color: #777; }
.art-views { font-size: 0.78rem; color: #aaa; }

/* Repost */
.repost {
  border-left: 3px solid #4a76a8;
  padding-left: 12px;
  margin-top: 10px;
  color: #444;
  font-size: 0.9rem;
}
.repost-label { color: #4a76a8; font-size: 0.8rem; margin-bottom: 4px; }

/* Lightbox */
.lightbox {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.85);
  z-index: 1000;
  justify-content: center;
  align-items: center;
  cursor: zoom-out;
}
.lightbox.active { display: flex; }
.lightbox img { max-width: 95vw; max-height: 95vh; border-radius: 4px; }

@media (max-width: 480px) {
  .post { padding: 12px; }
  .page-header h1 { font-size: 1.3rem; }
}
"""

JS = """
document.querySelectorAll('.att-img').forEach(img => {
  img.addEventListener('click', () => {
    const lb = document.getElementById('lightbox');
    document.getElementById('lb-img').src = img.src;
    lb.classList.add('active');
  });
});
document.getElementById('lightbox').addEventListener('click', () => {
  document.getElementById('lightbox').classList.remove('active');
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('lightbox').classList.remove('active');
});
"""


def generate_html(
    posts: list[dict],
    group: dict,
    output_dir: Path,
    download_audio: bool = False,
    download_docs: bool = False,
) -> Path:
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    name = escape(group.get("name", "VK Group"))
    members = group.get("members_count", 0)
    saved_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    print(f"Generating HTML for {len(posts)} posts...")
    posts_html = ""
    for i, post in enumerate(posts, 1):
        print(f"  Post {i}/{len(posts)}", end="\r", flush=True)
        posts_html += render_post(post, images_dir, output_dir, download_audio, download_docs)
    print()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}</title>
<style>{CSS}</style>
</head>
<body>
<div id="lightbox" class="lightbox">
  <img id="lb-img" src="">
</div>
<header class="page-header">
  <h1>{name}</h1>
  <div class="meta">{members:,} followers &nbsp;·&nbsp; saved {saved_at} &nbsp;·&nbsp; {len(posts)} posts</div>
</header>
<main class="feed">
{posts_html}
</main>
<script>{JS}</script>
</body>
</html>"""

    out = output_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


# ─── Entry point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Save a VK public page as an offline HTML archive")
    parser.add_argument("domain", help="Group short name or ID (e.g. typical_progger)")
    parser.add_argument("--token", help="VK API access token (or set VK_TOKEN env var)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of posts (default: all)")
    parser.add_argument("--out", default=None, help="Output directory (default: ./<domain>)")
    parser.add_argument("--download-audio", action="store_true", help="Download audio files to audio/ (requires accessible URL)")
    parser.add_argument("--download-docs", action="store_true", help="Download document attachments to docs/")
    args = parser.parse_args()

    token = args.token or os.environ.get("VK_TOKEN", "")
    if not token:
        print("A VK API token is required. Pass --token TOKEN or set the VK_TOKEN environment variable.")
        print("To get a token, run:  python get_token.py")
        sys.exit(1)

    # Accept both full URLs (https://vk.com/kombanation) and short names
    raw = args.domain.strip().rstrip("/")
    if raw.startswith("http://") or raw.startswith("https://"):
        from urllib.parse import urlparse
        domain = urlparse(raw).path.strip("/").split("/")[-1]
    else:
        domain = raw.lstrip("@")
    output_dir = Path(args.out) if args.out else Path(domain)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching group info for '{domain}'...")
    group = get_group_info(token, domain)
    print(f"  Group: {group['name']} ({group.get('members_count', 0):,} followers)")

    print(f"Fetching posts{f' (limit {args.limit})' if args.limit else ''}...")
    posts = get_all_posts(token, domain, args.limit)
    print(f"  Downloaded: {len(posts)} posts")

    # Save raw data for potential re-rendering
    raw_path = output_dir / "posts.json"
    raw_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Raw data → {raw_path}")

    html_path = generate_html(posts, group, output_dir, args.download_audio, args.download_docs)
    print(f"\nDone! Open in browser: {html_path.resolve()}")


if __name__ == "__main__":
    main()

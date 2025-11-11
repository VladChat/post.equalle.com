import os
import re
import sys
from pathlib import Path
import feedparser
from typing import Dict, List, Optional

# Support running as `python scripts/rss_fetch.py`
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.cache_manager import append_new_posts

def _extract_image(entry) -> Optional[str]:
    media = getattr(entry, "media_content", None)
    if media and isinstance(media, list) and media and "url" in media[0]:
        return media[0]["url"]
    thumb = getattr(entry, "media_thumbnail", None)
    if thumb and isinstance(thumb, list) and thumb and "url" in thumb[0]:
        return thumb[0]["url"]
    summary = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    content = getattr(entry, "content", None)
    if content and isinstance(content, list):
        for c in content:
            html = c.get("value", "") or ""
            m2 = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
            if m2:
                return m2.group(1)
    return None

def _extract_hashtags(entry) -> List[str]:
    tags = []
    for t in getattr(entry, "tags", []) or []:
        term = ""
        if isinstance(t, dict):
            term = t.get("term", "") or ""
        else:
            term = getattr(t, "term", "") or ""
        term = re.sub(r"\s+", "", term).lower()
        term = re.sub(r"[^a-z0-9_]", "", term)
        if term and len(term) <= 25:
            tags.append(term)
    return tags[:8]

def main() -> None:
    rss_url = os.getenv("RSS_URL", "").strip()
    if not rss_url:
        raise SystemExit("❌ RSS_URL is not set (environment).")

    feed = feedparser.parse(rss_url)
    if getattr(feed, "bozo", 0):
        print(f"⚠️ Feed parse warning: {getattr(feed, 'bozo_exception', '')}")

    new_posts = []
    for e in feed.entries:
        item: Dict = {
            "title": getattr(e, "title", "").strip(),
            "summary": getattr(e, "summary", "").strip(),
            "link": getattr(e, "link", "").strip(),
            "image": _extract_image(e),
            "hashtags": _extract_hashtags(e),
            "published": getattr(e, "published", "") or getattr(e, "updated", ""),
        }
        if item["link"]:
            new_posts.append(item)

    added, total = append_new_posts(new_posts)
    print(f"✅ RSS parsed. Added {added} new item(s). Total in cache: {total}")

if __name__ == "__main__":
    main()

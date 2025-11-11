# =========================================
# rss_fetch.py
# Purpose:
#   - Parse blog RSS and append unseen items into shared cache
#   - Use config.json for all adjustable settings (no secrets)
#   - Provide rich diagnostics and resilient parsing
# =========================================

import os
import re
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional
import feedparser

# Allow running directly: python scripts/rss_fetch.py
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.cache_manager import append_new_posts

# -----------------------------------------
# Configuration handling
# -----------------------------------------
CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {
    "rss_url": "https://blog.equalle.com/index.xml",
    "platforms": {
        "facebook": {
            "enabled": True,
            "page_id": "325670187920349",
            "token_env": "FB_PAGE_TOKEN"
        },
        "instagram": {"enabled": False, "token_env": "IG_TOKEN"},
        "pinterest": {"enabled": False, "token_env": "PINTEREST_TOKEN"},
        "twitter": {"enabled": False, "token_env": "TWITTER_TOKEN"},
        "youtube": {"enabled": False, "token_env": "YT_TOKEN"}
    },
    "settings": {
        "max_cache_items": 200,
        "max_published_history": 300,
        "mode": "dev",
        "log_level": "info"
    }
}


def load_config() -> dict:
    """Load config.json or create it with defaults if missing."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        print(f"🆕 Created default config at {CONFIG_PATH}")
        return DEFAULT_CONFIG

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = DEFAULT_CONFIG | data
        merged["platforms"] = DEFAULT_CONFIG["platforms"] | data.get("platforms", {})
        merged["settings"] = DEFAULT_CONFIG["settings"] | data.get("settings", {})
        return merged
    except Exception as e:
        print(f"⚠️ Failed to read config.json: {e}")
        return DEFAULT_CONFIG


# -----------------------------------------
# Helpers for parsing RSS content
# -----------------------------------------
def _extract_image(entry) -> Optional[str]:
    """Try multiple RSS fields to find the first valid image URL."""
    # media_content / media_thumbnail / content
    for attr in ("media_content", "media_thumbnail", "content"):
        value = getattr(entry, attr, None)
        if isinstance(value, list):
            for v in value:
                html = v.get("url") or v.get("value", "")
                if not html:
                    continue
                # Check for <img src=...> inside HTML fragments
                m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
                if m:
                    return m.group(1)
                # Direct URL field
                if v.get("url"):
                    return v["url"]
    # summary <img src=...>
    summary = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.I)
    if m:
        return m.group(1)
    return None


def _extract_hashtags(entry) -> List[str]:
    """Convert category/tags to normalized hashtags."""
    tags = []
    for t in getattr(entry, "tags", []) or []:
        term = ""
        if isinstance(t, dict):
            term = t.get("term", "") or ""
        else:
            term = getattr(t, "term", "") or ""
        term = re.sub(r"[^a-zA-Z0-9 ]+", "", term).strip().lower()
        if term:
            parts = term.split()
            joined = "".join(parts)
            if len(joined) <= 25:
                tags.append(joined)
    return tags[:8]


def _clean_summary(html: str, limit: int = 400) -> str:
    """Remove HTML tags and trim summary length."""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


# -----------------------------------------
# Main logic
# -----------------------------------------
def main() -> None:
    config = load_config()
    rss_url = config.get("rss_url", "").strip()
    if not rss_url:
        raise SystemExit("❌ RSS URL is missing in config.json")

    print(f"🔍 Fetching RSS from: {rss_url}")
    feed = feedparser.parse(rss_url)

    if getattr(feed, "bozo", 0):
        print(f"⚠️ Warning: malformed RSS or parse issue → {getattr(feed, 'bozo_exception', '')}")

    if not getattr(feed, "entries", []):
        print("⚠️ No entries found in RSS feed.")
        return

    new_posts = []
    for e in feed.entries:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "").strip()
        summary = getattr(e, "summary", "").strip()
        if not (title and link):
            continue

        item: Dict = {
            "title": title,
            "summary": _clean_summary(summary),
            "link": link,
            "image": _extract_image(e),
            "hashtags": _extract_hashtags(e),
            "published": getattr(e, "published", "") or getattr(e, "updated", ""),
        }
        new_posts.append(item)

    if not new_posts:
        print("⚠️ No valid posts parsed from feed entries.")
        return

    added, total = append_new_posts(new_posts)
    print(f"✅ RSS parsed successfully. Added {added} new item(s). Total in cache: {total}")

    # Optional verbose output for debugging
    if config["settings"].get("log_level") == "debug":
        preview = new_posts[:2]
        print("\n--- Preview of first parsed items ---")
        for i, p in enumerate(preview, start=1):
            print(f"{i}. {p['title']} → {p['link']}")
            print(f"   Tags: {', '.join(p['hashtags'])}")
            print(f"   Image: {p['image']}")
            print(f"   Summary: {p['summary'][:150]}...")
        print("-----------------------------------")


if __name__ == "__main__":
    main()

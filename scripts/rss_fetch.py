# =========================================
# rss_fetch.py
# Purpose:
#   - Parse blog RSS and append unseen items into shared cache
#   - Use config.json for all adjustable settings (no secrets)
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
        # Merge defaults for any missing keys
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
    """Best-effort image extraction from various RSS tags."""
    for attr in ("media_content", "media_thumbnail", "content"):
        value = getattr(entry, attr, None)
        if isinstance(value, list):
            for v in value:
                html = v.get("url") or v.get("value", "")
                if not html:
                    continue
                m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
                if m:
                    return m.group(1)
                if v.get("url"):
                    return v["url"]
    # summary <img src=...>
    summary = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.I)
    if m:
        return m.group(1)
    return None


def _extract_hashtags(entry) -> List[str]:
    """Build a lightweight hashtag list from entry.tags."""
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


# -----------------------------------------
# Main logic
# -----------------------------------------
def main() -> None:
    config = load_config()
    rss_url = config.get("rss_url", "").strip()

    if not rss_url:
        raise SystemExit("❌ RSS URL is missing in config.json")

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

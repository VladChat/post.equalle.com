# =========================================
# rss_fetch.py
# Purpose:
#   - Parse blog RSS and append unseen items into shared cache
#   - Log all actions and errors to data/logs/rss_fetch.log
# =========================================

import os
import re
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import feedparser

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.cache_manager import append_new_posts

# -----------------------------------------
# Paths & Config
# -----------------------------------------
CONFIG_PATH = Path(__file__).parent / "config.json"
LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "rss_url": "https://blog.equalle.com/index.xml",
    "platforms": {
        "facebook": {"enabled": True, "page_id": "325670187920349", "token_env": "FB_PAGE_TOKEN"}
    },
    "settings": {
        "max_cache_items": 200,
        "max_published_history": 300,
        "mode": "dev",
        "log_level": "info"
    }
}


def setup_logger(level: str = "info"):
    """Configure logging to file and console."""
    logfile = LOG_DIR / "rss_fetch.log"
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(logfile, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info("Logger initialized (level=%s, file=%s)", level.upper(), logfile)


def load_config() -> dict:
    """Load config.json or create it with defaults if missing."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        logging.warning("Created default config at %s", CONFIG_PATH)
        return DEFAULT_CONFIG

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = DEFAULT_CONFIG | data
        merged["platforms"] = DEFAULT_CONFIG["platforms"] | data.get("platforms", {})
        merged["settings"] = DEFAULT_CONFIG["settings"] | data.get("settings", {})
        return merged
    except Exception as e:
        logging.error("Failed to read config.json: %s", e)
        return DEFAULT_CONFIG


# -----------------------------------------
# RSS helpers
# -----------------------------------------
def _extract_image(entry) -> Optional[str]:
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
    summary = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.I)
    if m:
        return m.group(1)
    return None


def _extract_hashtags(entry) -> List[str]:
    tags = []
    for t in getattr(entry, "tags", []) or []:
        term = getattr(t, "term", "") if not isinstance(t, dict) else t.get("term", "")
        term = re.sub(r"[^a-zA-Z0-9 ]+", "", term).strip().lower()
        if term:
            joined = "".join(term.split())
            if len(joined) <= 25:
                tags.append(joined)
    return tags[:8]


def _clean_summary(html: str, limit: int = 400) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


# -----------------------------------------
# Main logic
# -----------------------------------------
def main() -> None:
    config = load_config()
    setup_logger(config["settings"].get("log_level", "info"))

    rss_url = config.get("rss_url", "").strip()
    if not rss_url:
        logging.error("RSS URL missing in config.json")
        raise SystemExit(1)

    logging.info("Fetching RSS from: %s", rss_url)
    feed = feedparser.parse(rss_url)

    if getattr(feed, "bozo", 0):
        logging.warning("Malformed RSS or parse issue: %s", getattr(feed, "bozo_exception", ""))

    if not getattr(feed, "entries", []):
        logging.warning("No entries found in RSS feed.")
        return

    new_posts = []
    for e in feed.entries:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "").strip()
        if not (title and link):
            continue
        item: Dict = {
            "title": title,
            "summary": _clean_summary(getattr(e, "summary", "")),
            "link": link,
            "image": _extract_image(e),
            "hashtags": _extract_hashtags(e),
            "published": getattr(e, "published", "") or getattr(e, "updated", ""),
        }
        new_posts.append(item)

    added, total = append_new_posts(new_posts)
    logging.info("RSS parsed successfully. Added %d new item(s). Total in cache: %d", added, total)

    if config["settings"].get("log_level") == "debug":
        for i, p in enumerate(new_posts[:2], start=1):
            logging.debug("Item %d: %s | %s", i, p["title"], p["link"])


if __name__ == "__main__":
    main()

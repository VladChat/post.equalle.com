# ============================================================
# File: utils_instagram.py
# Purpose: Helper functions for Instagram card generation
# ============================================================

from pathlib import Path
import re
import xml.etree.ElementTree as ET
import html
import json

# --- Prefer JSON cache created by RSS Sync ---
def parse_latest_from_cache(cache_json_path: Path):
    if not cache_json_path.exists():
        return None
    data = json.loads(cache_json_path.read_text(encoding="utf-8"))
    if isinstance(data, list) and data:
        item = data[0]
        title = item.get("title", "").strip()
        link = item.get("link", "")
        image_url = item.get("image", "") or item.get("media", "") or item.get("media_url", "")
        return {"title": title, "link": link, "image_url": image_url}
    return None

# --- Fallback to RSS XML if present ---
def parse_latest_from_rss(rss_path: Path):
    tree = ET.parse(rss_path)
    root = tree.getroot()
    items = root.findall(".//item")
    if not items:
        raise ValueError("No <item> found in RSS feed.")
    item = items[0]
    title = html.unescape(item.findtext("title", "")).strip()
    link = item.findtext("link", "").strip()
    media_el = item.find("{http://search.yahoo.com/mrss/}content")
    image_url = media_el.attrib.get("url", "") if media_el is not None else ""
    return {"title": title, "link": link, "image_url": image_url}

# --- Title shortener for overlay (2 lines max) ---
def shorten_title(title: str, max_words: int = 5) -> str:
    words = [w for w in title.split() if w.lower() not in {'for','and','the','a','an','to','in','with','of'}]
    short = " ".join(words[:max_words]) or title
    # soft wrap around ~25 chars
    return re.sub(r"(.{25,}?)\s", r"\1\n", short)

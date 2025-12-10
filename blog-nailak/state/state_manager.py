# ============================================
# File: blog-nailak/state/state_manager.py
# Purpose: Track which RSS posts were published to which platforms
#          and prevent reposting same URL or same image per platform
# ============================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from rss.rss_parser import Post

# state.json лежит рядом с этим файлом
STATE_FILE = Path(__file__).with_name("state.json")


def _ensure_state_shape(raw: Any) -> Dict[str, Any]:
    """Normalizes state structure for backward compatibility.

    Legacy format:
        {
          "facebook": [...],
          "instagram": [...],
          "pinterest": [...]
        }

    New format adds image tracking:
        {
          "facebook": [...],
          "instagram": [...],
          "pinterest": [...],
          "images": {
            "facebook": [...],
            "instagram": [...],
            "pinterest": [...]
          }
        }
    """
    if not isinstance(raw, dict):
        raw = {}

    # ensure url lists for known platforms
    for platform in ("facebook", "instagram", "pinterest"):
        urls = raw.get(platform)
        if not isinstance(urls, list):
            raw[platform] = []
        else:
            # keep as-is
            raw[platform] = urls

    images = raw.get("images")
    if not isinstance(images, dict):
        images = {}
    for platform in ("facebook", "instagram", "pinterest"):
        lst = images.get(platform)
        if not isinstance(lst, list):
            images[platform] = []
        else:
            images[platform] = lst
    raw["images"] = images

    return raw


def load_state() -> Dict[str, Any]:
    """Loads state.json from disk. Creates default structure if file is missing."""
    if not STATE_FILE.exists():
        state: Dict[str, Any] = {
            "facebook": [],
            "instagram": [],
            "pinterest": [],
            "images": {
                "facebook": [],
                "instagram": [],
                "pinterest": [],
            },
        }
        return state

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        # In case of corruption – start from clean state
        raw = {}

    return _ensure_state_shape(raw)


def save_state(state: Dict[str, Any]) -> None:
    """Persists state.json to disk (ensuring directories exist)."""
    state = _ensure_state_shape(state)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_image_key(post: Post, platform: str) -> str | None:
    """Returns a stable image identifier for a given platform.

    Uses platform-specific card URL if present, otherwise generic image.
    We keep full URL as key – этого достаточно, т.к. карточки генерятся по постам.
    """
    img: str | None = None
    platform = platform.lower()
    if platform == "facebook":
        img = post.image_facebook or post.image_generic
    elif platform == "instagram":
        img = post.image_instagram or post.image_generic
    elif platform == "pinterest":
        img = post.image_pinterest or post.image_generic
    else:
        img = post.image_generic

    if not img:
        return None

    # Нормализуем пробелы/обрезки, но оставляем полный URL
    return str(img).strip()


def is_posted(post: Post, platform: str, state: Dict[str, Any]) -> bool:
    """Returns True if this post (URL or image) was already used on the platform.

    Защита работает по двум уровням:
      1) URL поста уже публиковался → считаем дубликатом.
      2) URL картинки уже публиковался на этой платформе → считаем дубликатом.
    """
    platform = platform.lower()
    state = _ensure_state_shape(state)

    url = post.link.strip()
    posted_urls: List[str] = state.get(platform, [])
    if url in posted_urls:
        print(f"[state] URL already posted for {platform}: {url}")
        return True

    img_key = _get_image_key(post, platform)
    if img_key:
        posted_images: List[str] = state.get("images", {}).get(platform, [])
        if img_key in posted_images:
            print(f"[state] Image already posted for {platform}: {img_key}")
            return True

    return False


def mark_post(post: Post, platform: str, state: Dict[str, Any]) -> None:
    """Marks this post (URL + image) as used for given platform."""
    platform = platform.lower()
    state = _ensure_state_shape(state)

    url = post.link.strip()
    posted_urls: List[str] = state.setdefault(platform, [])
    if url and url not in posted_urls:
        posted_urls.append(url)

    img_key = _get_image_key(post, platform)
    if img_key:
        images = state.setdefault("images", {})
        img_list: List[str] = images.setdefault(platform, [])
        if img_key not in img_list:
            img_list.append(img_key)
    """
    At this point caller обычно вызовет save_state(state).
    """



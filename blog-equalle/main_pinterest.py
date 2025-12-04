# ============================================
# File: blog-equalle/main_pinterest.py
# Purpose: Pick next RSS post and publish to Pinterest
# ============================================

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

# Ensure local imports work when run as: python blog-equalle/main_pinterest.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from rss.rss_loader import load_posts
from rss.rss_parser import Post
from state.state_manager import load_state, save_state, is_posted, mark_post
from utils.text_builder import build_pinterest_payload
from social.pinterest_poster import publish_pinterest_pin

PLATFORM = "pinterest"
BOARD_LIST_FILENAME = "board_list.json"
DEFAULT_BOARD_NAME = "Grit Guide & Education"


def _load_board_map() -> Dict[str, str]:
    """
    Load mapping "Category name" -> "board_id" from board_list.json
    which lives next to this file.

    Example structure:
    {
      "Marine Sanding": "8394...",
      "Auto Body Sanding": "8394...",
      ...
    }
    """
    base_dir = Path(__file__).resolve().parent
    path = base_dir / BOARD_LIST_FILENAME

    if not path.is_file():
        raise FileNotFoundError(f"[pin][main] board_list.json not found at {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("[pin][main] board_list.json must be a JSON object {name: id}")

    # Нормализуем все ID к строкам
    board_map: Dict[str, str] = {}
    for name, bid in raw.items():
        if not name:
            continue
        board_map[str(name).strip()] = str(bid).strip()

    if not board_map:
        raise ValueError("[pin][main] board_list.json is empty")

    return board_map


def _pick_image_url(post: Post) -> Optional[str]:
    """
    Choose the best image URL for Pinterest:
    - Pinterest-specific card, если есть
    - иначе Instagram / Facebook card
    - иначе любой generic image из RSS
    """
    for url in (
        getattr(post, "image_pinterest", None),
        getattr(post, "image_instagram", None),
        getattr(post, "image_facebook", None),
        getattr(post, "image_generic", None),
    ):
        if url:
            return url
    return None


def _primary_category(post: Post) -> Optional[str]:
    """
    First category from RSS = main category.
    Later we'll map it 1:1 to a Pinterest board.
    """
    cats = getattr(post, "categories", None) or []
    if not cats:
        return None
    primary = str(cats[0]).strip()
    return primary or None


def _pick_board_id(primary_category: Optional[str], board_map: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """
    Returns (category_name_used, board_id) or None if we can't find anything.
    Priority:
      1. Exact match by category name
      2. Case-insensitive match
      3. DEFAULT_BOARD_NAME, если он есть в карте
      4. Первый попавшийся board из карты (как совсем крайний fallback)
    """
    if primary_category:
        # 1) exact key match
        if primary_category in board_map:
            return primary_category, board_map[primary_category]

        # 2) case-insensitive match
        lower = primary_category.lower()
        for name, bid in board_map.items():
            if name.lower() == lower:
                return name, bid

    # 3) default board
    if DEFAULT_BOARD_NAME in board_map:
        return DEFAULT_BOARD_NAME, board_map[DEFAULT_BOARD_NAME]

    # 4) first entry as last resort
    for name, bid in board_map.items():
        return name, bid

    return None


def _pick_next_post(max_items: int, state: Dict[str, object]) -> Optional[Post]:
    """
    Find the next RSS post that:
      - hasn't been posted to Pinterest yet (by URL/image)
      - has at least one usable image
    """
    posts = load_posts(limit=max_items)
    print(f"[pin][main] Loaded {len(posts)} posts from RSS.")

    for post in posts:
        if is_posted(post, PLATFORM, state):
            continue
        image_url = _pick_image_url(post)
        if not image_url:
            print(f"[pin][main][SKIP] No image for post: {post.title!r}")
            continue
        # return first suitable; image_url will be recalculated by caller
        return post

    return None


def main() -> None:
    print("[pin][main] === Pinterest auto-post ===")

    max_items = int(os.getenv("MAX_RSS_ITEMS", "20"))

    # 1) загрузить состояние и карту board'ов
    state = load_state()
    board_map = _load_board_map()

    # 2) найти следующий пост
    post = _pick_next_post(max_items=max_items, state=state)
    if post is None:
        print("[pin][main] No suitable posts to publish.")
        return

    print(f"[pin][main] Selected post: {post.title}")

    # 3) подобрать картинку (ещё раз, чтобы получить фактический URL)
    image_url = _pick_image_url(post)
    if not image_url:
        print("[pin][main][WARN] Selected post lost its image, aborting.")
        return

    # 4) выбрать board по первой категории
    primary_category = _primary_category(post)
    cat_and_board = _pick_board_id(primary_category, board_map)

    if cat_and_board is None:
        print("[pin][main][WARN] Cannot find any board_id to use, aborting.")
        return

    category_used, board_id = cat_and_board
    print(f"[pin][main] Primary category: {primary_category!r}, using board: {category_used!r} ({board_id})")

    # 5) собрать payload и отправить в Pinterest
    payload = build_pinterest_payload(post=post, image_url=image_url)
    pin_id = publish_pinterest_pin(payload, board_id=board_id)

    print(f"[pin][main] Published Pinterest pin. id={pin_id}")

    # 6) обновить состояние
    mark_post(post, PLATFORM, state)
    save_state(state)
    print("[pin][main] State updated.")


if __name__ == "__main__":
    main()

# ============================================
# File: blog-nailak/main_pinterest.py
# Purpose: Pick next RSS post from blog.nailak.com and publish to Pinterest
# ============================================

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

# Ensure local imports work when run as: python blog-nailak/main_pinterest.py
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

# Если по ключевым словам ничего не нашли — используем эту доску, если она есть в карте
FALLBACK_BOARD_NAME = "At-Home Nail Care"

# Короткий и чистый словарь: доска -> список ключевых фраз (в нижнем регистре)
# Имена досок ДОЛЖНЫ совпадать с ключами в board_list.json
BOARD_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "Cuticle Care": (
        "cuticle care",
        "cuticles",
    ),
    "Dry & Cracked Cuticles": (
        "dry cuticle",
        "dry cuticles",
        "cracked cuticles",
        "dry skin around nails",
    ),
    "Hangnail Care": (
        "hangnail",
        "hang nail",
    ),
    "Cuticle Oil Tips": (
        "cuticle oil",
        "oil for cuticles",
    ),
    "Nail Growth": (
        "nail growth",
        "grow nails",
        "longer nails",
    ),
    "Oils for Nail Growth": (
        "oil for nail growth",
        "growth oil",
    ),
    "Nail Growth DIY Oils": (
        "diy nail oil",
        "homemade nail oil",
    ),
    "Nail Vitamins & Supplements": (
        "nail vitamins",
        "biotin",
        "supplements for nails",
    ),
    "Repair Brittle Nails": (
        "brittle nails",
        "weak nails",
    ),
    "Peeling & Splitting Nails": (
        "peeling nails",
        "splitting nails",
    ),
    "Nail Hydration": (
        "dry nails",
        "hydration",
        "moisture",
    ),
    "Nail Ridges Care": (
        "nail ridges",
        "vertical ridges",
        "ridges on nails",
    ),
    "Repair After Acrylics": (
        "after acrylics",
        "acrylic damage",
        "acrylic nails damage",
    ),
    "Nail Bed Recovery": (
        "nail bed",
        "bed damage",
        "damaged nail bed",
    ),
    "Gel & Dip Damage Repair": (
        "gel polish damage",
        "gel damage",
        "dip powder damage",
    ),
    "Best Nail Oils": (
        "best nail oils",
        "top nail oils",
    ),
    "Essential Oils for Nails": (
        "tea tree oil",
        "lavender oil",
        "essential oil",
    ),
    "Carrier Oils for Nails": (
        "jojoba oil",
        "sweet almond oil",
        "argan oil",
        "castor oil",
    ),
    "Nail Fungus Treatment": (
        "nail fungus",
        "fungal infection",
        "onychomycosis",
    ),
    "Natural Antifungal Oils": (
        "antifungal oil",
        "antifungal",
        "natural fungus remedy",
    ),
    "Toenail Fungus Care": (
        "toenail fungus",
        "toe fungus",
    ),
    "Non-Toxic Nail Care": (
        "non-toxic",
        "toxin-free",
        "3-free",
        "5-free",
    ),
    "Vegan Nail Care": (
        "vegan",
        "plant-based",
    ),
    "Eco-Friendly Nail Care": (
        "eco-friendly",
        "sustainable",
        "green beauty",
    ),
    "Manicure Prep": (
        "manicure prep",
        "prep your nails",
        "before manicure",
    ),
    "Damage-Free Removal": (
        "remove gel",
        "remove acrylic",
        "removal without damage",
    ),
    "At-Home Nail Care": (
        "at home",
        "home routine",
        "self-care at home",
    ),
    "Nail Care for Dry Weather": (
        "dry weather",
        "winter hands",
        "cold weather",
    ),
}


def _load_board_map() -> Dict[str, str]:
    """
    Load mapping "Board name" -> "board_id" from board_list.json
    which lives next to this file.
    """
    base_dir = Path(__file__).resolve().parent
    path = base_dir / BOARD_LIST_FILENAME

    if not path.is_file():
        raise FileNotFoundError(f"[pin][main] board_list.json not found at {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("[pin][main] board_list.json must be a JSON object {name: id}")

    board_map: Dict[str, str] = {}
    for name, bid in raw.items():
        name_str = str(name).strip()
        bid_str = str(bid).strip()
        if not name_str or not bid_str:
            # пропускаем пустые значения или незаполненные ID
            continue
        board_map[name_str] = bid_str

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


def _build_search_text(post: Post) -> str:
    """
    Собираем текст для анализа темы: title + description/summary.
    Всё приводим к нижнему регистру.
    """
    title = getattr(post, "title", "") or ""
    desc = getattr(post, "description", "") or ""
    if not desc:
        desc = getattr(post, "summary", "") or ""
    text = f"{title} {desc}".lower()
    return " ".join(text.split())  # уплотняем пробелы


def _pick_board_by_keywords(post: Post, board_map: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """
    Пытаемся подобрать доску по ключевым словам:
      - считаем совпадения по BOARD_KEYWORDS
      - выбираем доску с максимальным score
    Возвращаем (board_name, board_id) или None, если ничего не нашли.
    """
    text = _build_search_text(post)
    if not text:
        return None

    scores: Dict[str, int] = {}

    for board_name, keywords in BOARD_KEYWORDS.items():
        # доска должна существовать в board_list.json и иметь ID
        board_id = board_map.get(board_name)
        if not board_id:
            continue

        for kw in keywords:
            kw = kw.strip().lower()
            if not kw:
                continue
            if kw in text:
                scores[board_name] = scores.get(board_name, 0) + 1

    if not scores:
        return None

    # выбираем доску с максимальным количеством совпадений
    best_board_name = max(scores.items(), key=lambda item: item[1])[0]
    best_board_id = board_map[best_board_name]
    return best_board_name, best_board_id


def _pick_board_for_post(post: Post, board_map: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """
    Главная точка выбора доски:
      1) пробуем подобрать по ключевым словам
      2) если не получилось — используем FALLBACK_BOARD_NAME, если он есть
      3) если и его нет — берём первый board из карты
    """
    # 1) keyword-based
    match = _pick_board_by_keywords(post, board_map=board_map)
    if match is not None:
        return match

    # 2) fallback-доска по имени
    if FALLBACK_BOARD_NAME in board_map:
        return FALLBACK_BOARD_NAME, board_map[FALLBACK_BOARD_NAME]

    # 3) самый первый board как крайний вариант
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
        # возвращаем первый подходящий пост
        return post

    return None


def main() -> None:
    print("[pin][main] === Pinterest auto-post (Nailak) ===")

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

    # 3) убедиться, что у поста есть валидная картинка
    image_url = _pick_image_url(post)
    if not image_url:
        print("[pin][main][WARN] Selected post lost its image, aborting.")
        return

    # 4) выбрать доску по теме (ключевым словам)
    board_info = _pick_board_for_post(post, board_map=board_map)
    if board_info is None:
        print("[pin][main][WARN] Cannot find any board_id to use, aborting.")
        return

    board_name, board_id = board_info
    print(f"[pin][main] Using board: {board_name!r} ({board_id})")

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

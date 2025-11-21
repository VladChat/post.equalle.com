# ============================================
# File: blog-equalle/state/state_manager.py
# Purpose: Track which RSS posts were published to which platforms
# ============================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from rss.rss_parser import Post

# state.json лежит рядом с этим файлом
STATE_FILE = Path(__file__).with_name("state.json")

DEFAULT_STATE: Dict[str, List[str]] = {
    "facebook": [],
    "instagram": [],
    "pinterest": [],
}


def _ensure_dirs() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, List[str]]:
    _ensure_dirs()
    if not STATE_FILE.exists():
        return json.loads(json.dumps(DEFAULT_STATE))

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_STATE))

    # Guarantee all keys
    for key, default_list in DEFAULT_STATE.items():
        if key not in data or not isinstance(data.get(key), list):
            data[key] = list(default_list)

    return data


def save_state(state: Dict[str, List[str]]) -> None:
    _ensure_dirs()
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_posted(post: Post, platform: str, state: Dict[str, List[str]]) -> bool:
    url = post.link
    posted_list = state.get(platform, [])
    return url in posted_list


def mark_post(post: Post, platform: str, state: Dict[str, List[str]]) -> None:
    url = post.link
    posted_list = state.setdefault(platform, [])
    if url not in posted_list:
        posted_list.append(url)

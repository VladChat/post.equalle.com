# ============================================
# File: blog-equalle/main_pinterest.py
# ============================================

from __future__ import annotations

import os
import sys
from typing import Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from rss.rss_loader import load_posts
from state.state_manager import load_state, save_state, is_posted, mark_post
from utils.text_builder import build_pinterest_payload
from social.pinterest_poster import publish_pinterest_pin


PLATFORM = "pinterest"


def pick_next_post(max_items: int = 20) -> Optional[object]:
    posts = load_posts(limit=max_items)
    state = load_state()

    for post in posts:
        if not is_posted(post, PLATFORM, state):
            return post
    return None


def main() -> None:
    print("[pin][main] === Pinterest auto-post ===")
    max_items = int(os.getenv("MAX_RSS_ITEMS", "20"))

    state = load_state()
    post = pick_next_post(max_items=max_items)

    if post is None:
        print("[pin][main] No new posts to publish.")
        return

    print(f"[pin][main] Selected post: {post.title}")
    image_url = post.image_pinterest or post.image_generic
    if not image_url:
        print("[pin][main][WARN] No Pinterest card found, aborting.")
        return

    payload = build_pinterest_payload(post=post, image_url=image_url)
    pin_id = publish_pinterest_pin(payload)

    print(f"[pin][main] Published Pinterest pin. id={pin_id}")

    mark_post(post, PLATFORM, state)
    save_state(state)
    print("[pin][main] State updated.")


if __name__ == "__main__":
    main()

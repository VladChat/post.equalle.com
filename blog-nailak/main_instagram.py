# ============================================
# File: blog-nailak/main_instagram.py
# Purpose: Pick next RSS post and publish to Instagram Business (Nailak)
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
from utils.text_builder import build_instagram_caption
from social.instagram_poster import publish_instagram_image


PLATFORM = "instagram"


def pick_next_post(max_items: int = 20) -> Optional[object]:
    posts = load_posts(limit=max_items)
    state = load_state()

    for post in posts:
        if not is_posted(post, PLATFORM, state):
            return post
    return None


def main() -> None:
    print("[ig][main] === Instagram auto-post (Nailak) ===")
    max_items = int(os.getenv("MAX_RSS_ITEMS", "20"))

    state = load_state()
    post = pick_next_post(max_items=max_items)

    if post is None:
        print("[ig][main] No new posts to publish.")
        return

    print(f"[ig][main] Selected post: {post.title}")
    caption = build_instagram_caption(post)

    image_url = post.image_instagram or post.image_generic
    if not image_url:
        print("[ig][main][WARN] No Instagram image/card found, aborting.")
        return

    media_id = publish_instagram_image(caption=caption, image_url=image_url)
    print(f"[ig][main] Published Instagram post. media_id={media_id}")

    mark_post(post, PLATFORM, state)
    save_state(state)
    print("[ig][main] State updated.")


if __name__ == "__main__":
    main()

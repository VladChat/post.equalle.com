# ============================================
# File: blog-equalle/main_facebook.py
# Purpose: Pick next RSS post and publish to Facebook Page
# ============================================

from __future__ import annotations

import os
import sys
from typing import Optional

# Ensure local imports work when run as: python blog-equalle/main_facebook.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from rss.rss_loader import load_posts
from state.state_manager import load_state, save_state, is_posted, mark_post
from utils.text_builder import build_facebook_message
from social.facebook_poster import publish_facebook_photo
from social.facebook_commenter import publish_facebook_comment
from utils.text_builder import build_facebook_comment
import random
import time


PLATFORM = "facebook"


def pick_next_post(max_items: int = 20) -> Optional[object]:
    posts = load_posts(limit=max_items)
    state = load_state()

    for post in posts:
        if not is_posted(post, PLATFORM, state):
            return post
    return None


def main() -> None:
    print("[fb][main] === Facebook auto-post ===")
    max_items = int(os.getenv("MAX_RSS_ITEMS", "20"))

    state = load_state()
    post = pick_next_post(max_items=max_items)

    if post is None:
        print("[fb][main] No new posts to publish.")
        return

    print(f"[fb][main] Selected post: {post.title}")
    message = build_facebook_message(post)

    image_url = post.image_facebook or post.image_generic
    if not image_url:
        print("[fb][main][WARN] No Facebook card found, aborting.")
        return

    result = publish_facebook_photo(message=message, image_url=image_url, link=post.link)
    print(f"[fb][main] Published Facebook post. id={result}")

    # ===== Автокомментарий после публикации =====
    if result:
        pause = random.randint(30, 180)
        print(f"[fb][main] Waiting {pause} seconds before comment...")
        time.sleep(pause)

        try:
            comment_text = build_facebook_comment(post)
            if comment_text:
                publish_facebook_comment(result, comment_text)
                print("[fb][main] Comment published.]")
            else:
                print("[fb][main] No comment text generated, skipping.]")
        except Exception as e:
            print(f"[fb][main][WARN] Failed to publish comment: {e}")

    mark_post(post, PLATFORM, state)
    save_state(state)
    print("[fb][main] State updated.")


if __name__ == "__main__":
    main()
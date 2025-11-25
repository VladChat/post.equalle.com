# ============================================
# File: product-post/comment_after_post.py
# Purpose: Add auto-comment after creating FB post
# ============================================

import json
import time
import random
from pathlib import Path

from llm.generator import generate_facebook_comment
from comment.fb_commenter import post_facebook_comment

ROOT = Path(__file__).resolve().parent
STATE_POST_FILE = ROOT / "last_post_id.json"


def main() -> None:
    if not STATE_POST_FILE.exists():
        print("[COMMENT] No last_post_id.json found. Nothing to comment.")
        return

    try:
        data = json.loads(STATE_POST_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[COMMENT] Failed to read last_post_id.json: {e}")
        return

    post_id = data.get("post_id")
    product = data.get("product")

    if not post_id or not product:
        print("[COMMENT] Invalid state file. Missing post_id or product.")
        return

    # Pause human-like time
    pause = random.randint(30, 180)
    print(f"[COMMENT] Waiting {pause} seconds before posting comment...")
    time.sleep(pause)

    # Generate comment text
    try:
        comment = generate_facebook_comment(product)
    except Exception as e:
        print(f"[COMMENT][ERROR] LLM failed: {e}")
        return

    print("[COMMENT] Generated comment:")
    print(comment)

    # Publish comment
    try:
        post_facebook_comment(post_id, comment)
    except Exception as e:
        print(f"[COMMENT][FB ERROR] {e}")
        return

    print("[COMMENT] Done.")


if __name__ == "__main__":
    main()

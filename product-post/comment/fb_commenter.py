# ============================================
# File: product-post/comment/fb_commenter.py
# Purpose: Publish comments under Facebook posts
# ============================================

import os
import requests

DEFAULT_FB_PAGE_ID = "325670187920349"


def get_page_token() -> str:
    token = os.getenv("FB_PAGE_TOKEN") or os.getenv("PAGE_TOKEN")
    if not token:
        raise RuntimeError("FB_PAGE_TOKEN is missing")
    return token


def get_page_id() -> str:
    return os.getenv("FB_PAGE_ID", DEFAULT_FB_PAGE_ID)


def post_facebook_comment(post_id: str, message: str) -> dict:
    """Publish a comment under a Facebook post."""
    url = f"https://graph.facebook.com/v21.0/{post_id}/comments"
    payload = {
        "message": message,
        "access_token": get_page_token(),
    }

    print(f"[FB][COMMENT] POST → {url}")
    resp = requests.post(url, data=payload, timeout=30)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        print(f"[FB][COMMENT][ERROR] {resp.status_code}: {data}")
        raise RuntimeError(f"Facebook comment error: {resp.status_code}")

    print(f"[FB][COMMENT][OK] {data}")
    return data

# ============================================
# File: blog-equalle/social/facebook_commenter.py
# Purpose: Publish comments under Facebook posts
# ============================================

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any

import requests


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> Dict[str, Any]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("platforms", {}).get("facebook", {})


def _get_page_token() -> str:
    fb_cfg = _load_config()
    token_env = fb_cfg.get("token_env", "FB_PAGE_TOKEN")
    token = os.getenv(token_env)
    if not token:
        raise RuntimeError(f"[fb][comment] Missing token in env: {token_env}")
    return token


def publish_facebook_comment(post_id: str, message: str) -> str:
    """Publish a comment under an existing Facebook post.

    post_id — id поста, который вернул publish_facebook_photo(...).
    message — короткий текст комментария БЕЗ ссылок.
    """
    access_token = _get_page_token()

    url = f"https://graph.facebook.com/v21.0/{post_id}/comments"
    payload = {
        "message": message,
        "access_token": access_token,
    }

    print(f"[fb][comment] POST {url}")
    response = requests.post(url, data=payload, timeout=30)

    if not response.ok:
        raise RuntimeError(
            f"[fb][comment] Facebook API error: {response.status_code} {response.text}"
        )

    data = response.json()
    comment_id = str(data.get("id") or "")
    print(f"[fb][comment] Response JSON: {data}")
    return comment_id

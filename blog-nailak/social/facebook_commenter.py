# ============================================
# File: blog-nailak/social/facebook_commenter.py
# Purpose: Publish comments under Facebook posts (Nailak)
# ============================================

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any

import requests


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> Dict[str, Any]:
    """Loads Nailak facebook config block only."""
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("platforms", {}).get("facebook", {})


def _get_page_token() -> str:
    """
    ALWAYS use only FB_PAGE_TOKEN_NAILAK.
    No fallbacks.
    No legacy names.
    """
    token = os.getenv("FB_PAGE_TOKEN_NAILAK")

    if not token:
        raise RuntimeError("[fb][comment] Missing token in env: FB_PAGE_TOKEN_NAILAK")

    return token


def publish_facebook_comment(post_id: str, message: str) -> str:
    """Publish a comment under an existing Facebook post."""

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
    print(f"[fb][comment] Response JSON: {data}")

    return str(data.get("id") or "")

# ============================================
# File: blog-equalle/social/facebook_poster.py
# Purpose: Publish photo post to Facebook Page using Graph API
# ============================================

from __future__ import annotations

import os
from typing import Any, Dict

import requests


GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class FacebookConfigError(Exception):
    pass


def _get_config() -> tuple[str, str]:
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    access_token = os.getenv("FB_ACCESS_TOKEN", "").strip()

    if not page_id:
        raise FacebookConfigError("FB_PAGE_ID is not set.")
    if not access_token:
        raise FacebookConfigError("FB_ACCESS_TOKEN is not set (use GitHub Secret).")

    return page_id, access_token


def publish_facebook_photo(message: str, image_url: str, link: str | None = None) -> str:
    """Creates a photo post on the Facebook Page using remote image URL."""
    page_id, access_token = _get_config()

    url = f"{GRAPH_API_BASE}/{page_id}/photos"
    payload: Dict[str, Any] = {
        "url": image_url,
        "caption": message,
        "access_token": access_token,
    }

    print(f"[fb][poster] POST {url}")
    response = requests.post(url, data=payload, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Facebook API error: {response.status_code} {response.text}")

    data = response.json()
    post_id = data.get("post_id") or data.get("id") or ""
    print(f"[fb][poster] Response: {data}")
    return str(post_id)

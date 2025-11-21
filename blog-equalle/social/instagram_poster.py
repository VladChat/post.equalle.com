# ============================================
# File: blog-equalle/social/instagram_poster.py
# Purpose: Publish image to Instagram Business via Graph API
# ============================================

from __future__ import annotations

import os
from typing import Any, Dict

import requests


GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class InstagramConfigError(Exception):
    pass


def _get_config() -> tuple[str, str]:
    """Returns (ig_business_id, access_token)."""
    ig_id = os.getenv("IG_BUSINESS_ID", "").strip()
    access_token = os.getenv("IG_ACCESS_TOKEN", "").strip()

    if not ig_id:
        raise InstagramConfigError("IG_BUSINESS_ID is not set.")
    if not access_token:
        raise InstagramConfigError("IG_ACCESS_TOKEN is not set (use GitHub Secret).")

    return ig_id, access_token


def publish_instagram_image(caption: str, image_url: str) -> str:
    """2-step publish via /media then /media_publish."""
    ig_id, access_token = _get_config()

    # Step 1: create container
    url_media = f"{GRAPH_API_BASE}/{ig_id}/media"
    payload_media: Dict[str, Any] = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }

    print(f"[ig][poster] POST {url_media}")
    r1 = requests.post(url_media, data=payload_media, timeout=30)
    if not r1.ok:
        raise RuntimeError(f"Instagram media error: {r1.status_code} {r1.text}")
    data1 = r1.json()
    container_id = data1.get("id")
    if not container_id:
        raise RuntimeError(f"Instagram media response missing id: {data1}")

    # Step 2: publish container
    url_publish = f"{GRAPH_API_BASE}/{ig_id}/media_publish"
    payload_publish = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    print(f"[ig][poster] POST {url_publish}")
    r2 = requests.post(url_publish, data=payload_publish, timeout=30)
    if not r2.ok:
        raise RuntimeError(f"Instagram publish error: {r2.status_code} {r2.text}")

    data2 = r2.json()
    media_id = data2.get("id") or ""
    print(f"[ig][poster] Response: {data2}")
    return str(media_id)

# =========================================
# social_api.py
# Purpose:
#   - Unified API layer for social networks
#   - Exposes simple helpers: publish_photo(), publish_feed()
#   - Currently implemented: Facebook (Graph API v21.0)
#     Placeholders for other platforms can be added later.
# =========================================

from __future__ import annotations
import json
import time
from typing import Optional, Dict, Any
import requests


GRAPH_VER = "v21.0"


def _post(url: str, data: Dict[str, Any], logger=None, timeout: int = 30) -> Optional[Dict[str, Any]]:
    """POST helper with basic error logging."""
    try:
        resp = requests.post(url, data=data, timeout=timeout)
    except Exception as e:
        if logger:
            logger.error("HTTP error: %s %s", url, e)
        return None

    if not resp.ok:
        if logger:
            logger.error("HTTP %s -> %s | %s", resp.status_code, url, resp.text)
        return None

    try:
        return resp.json()
    except Exception as e:
        if logger:
            logger.error("JSON parse error for %s: %s", url, e)
        return None


def publish_photo(
    platform: str,
    page_or_account_id: str,
    token: str,
    caption: str,
    image_url: str,
    logger=None,
) -> Optional[str]:
    """
    Publish a photo post to a platform.
    Returns post_id (or media id) on success, None on failure.

    Supported:
      - platform == "facebook": POST /{page_id}/photos
    """
    platform = (platform or "").lower()

    if platform == "facebook":
        endpoint = f"https://graph.facebook.com/{GRAPH_VER}/{page_or_account_id}/photos"
        payload = {
            "caption": caption,
            "url": image_url,
            "access_token": token,
        }
        if logger:
            logger.debug("POST %s | data=%s", endpoint, {k: v for k, v in payload.items() if k != "access_token"})
        data = _post(endpoint, payload, logger=logger)
        if not data:
            return None
        # Graph may return {"post_id": "..."} or {"id": "..."}
        return data.get("post_id") or data.get("id")

    # Future: Instagram, Pinterest…
    if logger:
        logger.error("publish_photo: unsupported platform '%s'", platform)
    return None


def publish_feed(
    platform: str,
    page_or_account_id: str,
    token: str,
    message: str,
    link: Optional[str] = None,
    logger=None,
) -> Optional[str]:
    """
    Publish a text/link post to a platform.
    Returns post_id on success, None on failure.

    Supported:
      - platform == "facebook": POST /{page_id}/feed
    """
    platform = (platform or "").lower()

    if platform == "facebook":
        endpoint = f"https://graph.facebook.com/{GRAPH_VER}/{page_or_account_id}/feed"
        payload = {
            "message": message,
            "access_token": token,
        }
        if link:
            payload["link"] = link

        if logger:
            logger.debug("POST %s | data=%s", endpoint, {k: v for k, v in payload.items() if k != "access_token"})
        data = _post(endpoint, payload, logger=logger)
        if not data:
            return None
        return data.get("id")

    # Future: Twitter/X text, etc.
    if logger:
        logger.error("publish_feed: unsupported platform '%s'", platform)
    return None

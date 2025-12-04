# ============================================
# File: blog-equalle/social/pinterest_poster.py
# Purpose: Publish pin to Pinterest via v5 API
# ============================================

from __future__ import annotations

import os
from typing import Any, Dict

import requests

PINTEREST_API_BASE = "https://api.pinterest.com/v5"


class PinterestConfigError(Exception):
    """Raised when Pinterest configuration (env) is invalid."""
    pass


def _get_access_token() -> str:
    """
    Read access token from environment.

    Primary variable:
      - PINTEREST_ACCESS_TOKEN  (GitHub Secret)

    Fallback:
      - PINTEREST_TOKEN         (на всякий случай, для старых настроек)
    """
    token = os.getenv("PINTEREST_ACCESS_TOKEN", "").strip()
    if not token:
        token = os.getenv("PINTEREST_TOKEN", "").strip()

    if not token:
        raise PinterestConfigError(
            "Pinterest access token not found. "
            "Set PINTEREST_ACCESS_TOKEN as a GitHub Actions secret."
        )

    return token


def publish_pinterest_pin(payload: Dict[str, Any], board_id: str) -> str:
    """
    Creates a pin using prepared payload and explicit board_id.

    Expected payload structure (from utils.text_builder.build_pinterest_payload):
      {
        "title": "...",
        "description": "...",
        "link": "https://blog.equalle.com/....",
        "media_source": {
          "source_type": "image_url",
          "url": "https://blog.equalle.com/..."
        }
      }

    We add:
      - board_id
    """
    if not board_id:
        raise ValueError("publish_pinterest_pin() requires non-empty board_id")

    access_token = _get_access_token()

    # Не мутируем исходный dict на всякий случай
    body: Dict[str, Any] = dict(payload)
    body["board_id"] = board_id

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"{PINTEREST_API_BASE}/pins"
    print(f"[pin][poster] POST {url}")
    print(f"[pin][poster] Payload keys: {list(body.keys())}")

    response = requests.post(url, json=body, headers=headers, timeout=30)

    if not response.ok:
        raise RuntimeError(
            f"[pin][poster] Pinterest API error: {response.status_code} {response.text}"
        )

    data = response.json()
    pin_id = str(data.get("id") or "")
    print(f"[pin][poster] Response: {data}")
    return pin_id

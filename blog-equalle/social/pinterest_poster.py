# ============================================
# File: blog-equalle/social/pinterest_poster.py
# Purpose: Publish pin to Pinterest via v5 API
# ============================================

from __future__ import annotations

import os
from typing import Any, Dict
import requests

PINTEREST_API_BASE = "https://api.pinterest.com/v5"

# ⭐ Pinterest BOARD ID — НЕ секретная инфа
PINTEREST_BOARD_ID = "839428886736046036"   # ← твоя доска "Sanding Tips & Guides"


class PinterestConfigError(Exception):
    pass


def _get_config() -> tuple[str, str]:
    # Access token всё ещё должен быть секретом
    access_token = os.getenv("PINTEREST_ACCESS_TOKEN", "").strip()

    if not access_token:
        raise PinterestConfigError("PINTEREST_ACCESS_TOKEN is not set (use GitHub Secret).")

    return access_token, PINTEREST_BOARD_ID


def publish_pinterest_pin(payload: Dict[str, Any]) -> str:
    """Creates a pin using prepared payload."""
    access_token, board_id = _get_config()

    # Вставляем Board ID прямо здесь
    payload["board_id"] = board_id

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"{PINTEREST_API_BASE}/pins"
    print(f"[pin][poster] POST {url}")
    response = requests.post(url, json=payload, headers=headers, timeout=30)

    if not response.ok:
        raise RuntimeError(f"Pinterest API error: {response.status_code} {response.text}")

    data = response.json()
    pin_id = data.get("id") or ""
    print(f"[pin][poster] Response: {data}")
    return str(pin_id)

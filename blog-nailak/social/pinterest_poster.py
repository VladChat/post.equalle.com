# ============================================
# File: blog-nailak/social/pinterest_poster.py
# Purpose: Publish pin to Pinterest via v5 API (Nailak)
# ============================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
import requests


PINTEREST_API_BASE = "https://api.pinterest.com/v5"
_CONFIG_CACHE: Dict[str, Any] | None = None


class PinterestConfigError(Exception):
    pass


# -------------------------------------------------
# LOAD CONFIG.JSON FOR PINTEREST SETTINGS
# -------------------------------------------------

def _find_config_path() -> Path:
    """
    Ищет config.json:
      - <repo_root>/blog-nailak/config.json
      - <repo_root>/scripts/config.json
      - <repo_root>/config.json
    """
    current_file = Path(__file__).resolve()
    repo_root = current_file.parents[2]

    candidates = [
        repo_root / "blog-nailak" / "config.json",
        repo_root / "scripts" / "config.json",
        repo_root / "config.json",
    ]

    for path in candidates:
        if path.exists():
            print(f"[pin][config] Using config file: {path}")
            return path

    raise PinterestConfigError(
        "[pin][config] config.json not found in expected locations."
    )


def _load_config() -> Dict[str, Any]:
    """Lazy-load config.json."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    path = _find_config_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            _CONFIG_CACHE = json.load(f)
    except Exception as exc:
        raise PinterestConfigError(
            f"[pin][config] Failed to load config.json: {exc}"
        ) from exc

    return _CONFIG_CACHE or {}


def _get_config() -> tuple[str, str]:
    """
    Возвращает (access_token, board_id).

    - access_token берётся из ENV[token_env]
    - board_id берётся из config.json → platforms.pinterest.board
    """
    cfg = _load_config()

    platforms = cfg.get("platforms", {})
    pin_cfg = platforms.get("pinterest") or {}

    board_id = str(pin_cfg.get("board", "")).strip()
    token_env = str(pin_cfg.get("token_env", "PINTEREST_TOKEN")).strip()

    if not board_id:
        raise PinterestConfigError(
            "[pin][config] Missing platforms.pinterest.board in config.json"
        )

    if not token_env:
        raise PinterestConfigError(
            "[pin][config] Missing platforms.pinterest.token_env in config.json"
        )

    access_token = os.getenv(token_env, "").strip()
    if not access_token:
        raise PinterestConfigError(
            f"[pin][config] GitHub Secret '{token_env}' is not set."
        )

    print(f"[pin][config] board_id={board_id}, token_env={token_env}")
    return access_token, board_id


# -------------------------------------------------
# PUBLISH PIN
# -------------------------------------------------

def publish_pinterest_pin(payload: Dict[str, Any]) -> str:
    """Creates a Pinterest pin using Pinterest v5 API."""
    access_token, board_id = _get_config()

    payload["board_id"] = board_id

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"{PINTEREST_API_BASE}/pins"
    print(f"[pin][poster] POST {url}")

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    if not response.ok:
        raise RuntimeError(
            f"[pin][poster] Pinterest API error: {response.status_code} {response.text}"
        )

    data = response.json()
    pin_id = data.get("id") or ""
    print(f"[pin][poster] Response: {data}")

    return str(pin_id)

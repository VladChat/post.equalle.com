# ============================================
# File: blog-nailak/social/instagram_poster.py
# Purpose:
#   - Publish image to Instagram Business via Graph API (Nailak)
#
# Config:
#   - Берём настройки из config.json:
#       {
#         "platforms": {
#           "instagram": {
#             "enabled": true,
#             "business_id": "REPLACE_WITH_NAILAK_IG_BUSINESS_ID",
#             "token_env": "FB_PAGE_TOKEN_NAILAK"
#           }
#         }
#       }
#
#   - business_id  -> platforms.instagram.business_id
#   - token_env    -> platforms.instagram.token_env  (обычно "FB_PAGE_TOKEN_NAILAK")
#   - сам токен    -> GitHub Secret с таким именем
#
# ============================================

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

import requests

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_CONFIG_CACHE: Dict[str, Any] | None = None


class InstagramConfigError(Exception):
    pass


# ============ ЗАГРУЗКА CONFIG.JSON ============

def _find_config_path() -> Path:
    """
    Ищет config.json в типичных местах относительно корня репозитория:

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
            print(f"[ig][config] Using config file: {path}")
            return path

    raise InstagramConfigError(
        "[ig][config] config.json not found. Expected one of: "
        + ", ".join(str(p) for p in candidates)
    )


def _load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    config_path = _find_config_path()
    try:
        with config_path.open("r", encoding="utf-8") as f:
            _CONFIG_CACHE = json.load(f)
    except Exception as exc:
        raise InstagramConfigError(
            f"[ig][config] Failed to load {config_path}: {exc}"
        ) from exc

    return _CONFIG_CACHE or {}


def _get_config() -> tuple[str, str]:
    """
    Возвращает (business_id, access_token)
    """
    cfg = _load_config()

    platforms = cfg.get("platforms", {})
    ig_cfg = platforms.get("instagram") or {}

    business_id = str(ig_cfg.get("business_id", "")).strip()
    token_env = str(ig_cfg.get("token_env", "FB_PAGE_TOKEN_NAILAK")).strip()

    if not business_id:
        raise InstagramConfigError(
            "[ig][config] Missing platforms.instagram.business_id in config.json"
        )

    if not token_env:
        raise InstagramConfigError(
            "[ig][config] Missing platforms.instagram.token_env in config.json"
        )

    access_token = os.getenv(token_env, "").strip()
    if not access_token:
        raise InstagramConfigError(
            f"[ig][config] GitHub Secret '{token_env}' is not set."
        )

    print(f"[ig][config] business_id={business_id}, token_env={token_env}")
    return business_id, access_token


# ============ ПУБЛИКАЦИЯ В INSTAGRAM ============

def publish_instagram_image(caption: str, image_url: str) -> str:
    """
    Публикует изображение в Instagram Business (2 шага):
      1) создаём media container
      2) публикуем его
    """
    business_id, access_token = _get_config()

    # --- Шаг 1: создание media container ---
    url_media = f"{GRAPH_API_BASE}/{business_id}/media"
    payload_media: Dict[str, Any] = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }

    print(f"[ig][poster] POST {url_media}")
    print(f"[ig][poster] Payload keys: {list(payload_media.keys())}")

    r1 = requests.post(url_media, data=payload_media, timeout=30)
    if not r1.ok:
        raise RuntimeError(
            f"[ig][poster] Instagram media error: {r1.status_code} {r1.text}"
        )

    data1 = r1.json()
    container_id = data1.get("id")
    if not container_id:
        raise RuntimeError(
            f"[ig][poster] Instagram media response missing id: {data1}"
        )

    print(f"[ig][poster] Created container_id={container_id}. Waiting for processing...")
    time.sleep(3)

    # --- Шаг 2: публикация контейнера ---
    url_publish = f"{GRAPH_API_BASE}/{business_id}/media_publish"
    payload_publish = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    print(f"[ig][poster] POST {url_publish}")
    r2 = requests.post(url_publish, data=payload_publish, timeout=30)
    if not r2.ok:
        raise RuntimeError(
            f"[ig][poster] Instagram publish error: {r2.status_code} {r2.text}"
        )

    data2 = r2.json()
    media_id = data2.get("id") or ""
    print(f"[ig][poster] Response: {data2}")

    return media_id

# ============================================
# File: blog-equalle/social/facebook_poster.py
# Purpose:
#   - Publish photo post to Facebook Page using Graph API
#
# Data sources:
#   - config.json:
#       {
#         "platforms": {
#           "facebook": {
#             "enabled": true,
#             "page_id": "325670187920349",
#             "token_env": "FB_PAGE_TOKEN"
#           },
#           ...
#         }
#       }
#
# ENV:
#   - FB_PAGE_TOKEN  (основное имя GitHub Secret с page access token)
#   - PAGE_TOKEN     (опционально, для совместимости со старыми настройками)
#
# Notes:
#   - FB_PAGE_ID в ENV не нужен: page_id берём из config.json.
#   - Токен общий для Facebook и Instagram (page access token System User).
# ============================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import requests


GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_CONFIG_CACHE: Dict[str, Any] | None = None


class FacebookConfigError(Exception):
    """Ошибки конфигурации Facebook-постера."""
    pass


# ============ ЗАГРУЗКА CONFIG.JSON ============

def _find_config_path() -> Path:
    """
    Ищет config.json в типичных местах относительно корня репозитория:

      - <repo_root>/blog-equalle/config.json
      - <repo_root>/scripts/config.json
      - <repo_root>/config.json
    """

    current_file = Path(__file__).resolve()
    # current_file: .../post.equalle.com/blog-equalle/social/facebook_poster.py
    # repo_root:   .../post.equalle.com
    repo_root = current_file.parents[2]

    candidates = [
        repo_root / "blog-equalle" / "config.json",
        repo_root / "scripts" / "config.json",
        repo_root / "config.json",
    ]

    for path in candidates:
        if path.exists():
            print(f"[fb][config] Using config file: {path}")
            return path

    raise FacebookConfigError(
        "[fb][config] config.json not found. Expected one of: "
        + ", ".join(str(p) for p in candidates)
    )


def _load_config() -> Dict[str, Any]:
    """Лениво загружает config.json и кэширует результат."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    config_path = _find_config_path()
    try:
        with config_path.open("r", encoding="utf-8") as f:
            _CONFIG_CACHE = json.load(f)
    except Exception as exc:
        raise FacebookConfigError(
            f"[fb][config] Failed to load {config_path}: {exc}"
        ) from exc

    return _CONFIG_CACHE or {}


def _get_config() -> tuple[str, str]:
    """
    Возвращает (page_id, access_token):

      - page_id берём из config.json → platforms.facebook.page_id
      - токен читаем из ENV:
          FB_PAGE_TOKEN  (основное имя)
          PAGE_TOKEN     (fallback, как было в старых скриптах)
    """
    cfg = _load_config()

    platforms = cfg.get("platforms", {})
    fb_cfg = platforms.get("facebook") or {}

    page_id = str(fb_cfg.get("page_id", "")).strip()
    if not page_id:
        raise FacebookConfigError(
            "[fb][config] Missing platforms.facebook.page_id in config.json"
        )

    # Токен: полностью повторяем логику рабочих скриптов
    token = (os.getenv("FB_PAGE_TOKEN") or os.getenv("PAGE_TOKEN") or "").strip()
    if not token:
        raise FacebookConfigError(
            "[fb][config] ENV FB_PAGE_TOKEN (or PAGE_TOKEN) is required but not set. "
            "Set this GitHub Secret to your Facebook Page token."
        )

    print(f"[fb][config] page_id={page_id}, token_source="
          f"{'FB_PAGE_TOKEN' if os.getenv('FB_PAGE_TOKEN') else 'PAGE_TOKEN'}")

    return page_id, token


# ============ ПУБЛИКАЦИЯ В FACEBOOK ============

def publish_facebook_photo(message: str, image_url: str, link: str | None = None) -> str:
    """
    Публикует фото-пост на Facebook Page по удалённому URL картинки.

    Параметры:
      - message: текст поста (caption)
      - image_url: URL картинки (jpg/png), доступный извне
      - link: сейчас НЕ используется напрямую /photos,
              ссылку лучше встраивать в message.

    Возвращает:
      - post_id опубликованного поста (строка)
    """
    page_id, access_token = _get_config()

    url = f"{GRAPH_API_BASE}/{page_id}/photos"
    payload: Dict[str, Any] = {
        "url": image_url,
        "caption": message,
        "access_token": access_token,
    }

    print(f"[fb][poster] POST {url}")
    print(f"[fb][poster] Payload keys: {list(payload.keys())}")

    response = requests.post(url, data=payload, timeout=30)
    if not response.ok:
        raise RuntimeError(
            f"[fb][poster] Facebook API error: {response.status_code} {response.text}"
        )

    data = response.json()
    post_id = data.get("post_id") or data.get("id") or ""
    print(f"[fb][poster] Response JSON: {data}")
    return str(post_id)

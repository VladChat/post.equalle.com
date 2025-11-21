# ============================================
# File: blog-equalle/social/instagram_poster.py
# Purpose:
#   - Publish image to Instagram Business via Graph API
#
# Config:
#   - Берём настройки из config.json:
#       {
#         "platforms": {
#           "instagram": {
#             "enabled": true,
#             "business_id": "17841422239487755",
#             "token_env": "FB_PAGE_TOKEN"
#           }
#         }
#       }
#
#   - business_id  -> platforms.instagram.business_id
#   - token_env    -> platforms.instagram.token_env  (обычно "FB_PAGE_TOKEN")
#   - Сам токен    -> GitHub Secret с таким именем (FB_PAGE_TOKEN)
#
# Важно:
#   - Отдельного "инстаграмного" токена нет.
#   - Используем тот же PAGE ACCESS TOKEN, что и для Facebook.
# ============================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import requests

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_CONFIG_CACHE: Dict[str, Any] | None = None


class InstagramConfigError(Exception):
    """Ошибки конфигурации Instagram-постера."""
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
    # current_file: .../post.equalle.com/blog-equalle/social/instagram_poster.py
    # repo_root:   .../post.equalle.com
    repo_root = current_file.parents[2]

    candidates = [
        repo_root / "blog-equalle" / "config.json",
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
    """Лениво загружает config.json и кэширует результат."""
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
    Возвращает кортеж (business_id, access_token).

    - business_id берём из config.json → platforms.instagram.business_id
    - имя переменной с токеном берём из config.json → platforms.instagram.token_env
      (по умолчанию 'FB_PAGE_TOKEN')
    - сам токен читаем из ENV[ token_env ] (GitHub Secret).
    """
    cfg = _load_config()

    platforms = cfg.get("platforms", {})
    ig_cfg = platforms.get("instagram") or {}

    business_id = str(ig_cfg.get("business_id", "")).strip()
    token_env = str(ig_cfg.get("token_env", "FB_PAGE_TOKEN")).strip()

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
    Публикует изображение в Instagram Business (два шага):

      1) POST /{business_id}/media
         - создаём контейнер (media object)
      2) POST /{business_id}/media_publish
         - публикуем созданный контейнер

    Параметры:
      - caption: текст подписи
      - image_url: публичный URL картинки (jpg/png)

    Возвращает:
      - media_id опубликованного объекта (строка)
    """
    business_id, access_token = _get_config()

    # --- Шаг 1: создаём media container ---
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

    # --- Шаг 2: публикуем контейнер ---
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

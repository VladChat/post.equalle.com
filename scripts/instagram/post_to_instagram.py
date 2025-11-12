# ============================================================
# File: scripts/instagram/post_to_instagram.py
# Full path: <repo_root>/scripts/instagram/post_to_instagram.py
# Purpose:
#   - Берёт последнюю готовую IG-карточку (1080×1350 JPEG) из /images/ig/
#   - Формирует caption из data/cache/latest_posts.json
#   - Проверяет дубликаты по data/state.json (секция "instagram")
#   - Публикует в Instagram через Graph API:
#       POST /{IG_BUSINESS_ID}/media → media container
#       POST /{IG_BUSINESS_ID}/media_publish → publish
#   - Обновляет data/state.json
#   - Пишет лог в data/logs/post_to_instagram.log
#
# ENV (секреты/система, НЕ из файлов):
#   MODE                = "prod" | "dev"   (по умолчанию "dev")
#   FB_PAGE_TOKEN       = "<page_access_token>" # Page token (общий и для FB, и для IG)
#   (резервное имя: PAGE_TOKEN)
#   IG_IMAGES_BASE_URL  = "https://blog.equalle.com/images/ig/"  # публичная база для .jpg
# ============================================================

from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Dict
from datetime import datetime, timezone

import requests

# === Path resolution (robust) ===
ROOT = Path(__file__).resolve().parents[2]

# === Paths ===
IMAGES_DIR = ROOT / "images" / "ig"
CACHE_JSON = ROOT / "data" / "cache" / "latest_posts.json"
STATE_JSON = ROOT / "data" / "state.json"
LOG_DIR    = ROOT / "data" / "logs"
LOG_FILE   = LOG_DIR / "post_to_instagram.log"
PREVIEW_OUT= ROOT / "data" / "out" / "instagram_preview.json"

GRAPH_BASE = "https://graph.facebook.com/v21.0"


# === Logging helpers ===
def _ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "out").mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    _ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{ts}] {msg}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


# === ENV & state helpers ===
def get_mode() -> str:
    return os.getenv("MODE", "dev").strip().lower()

def get_ig_id() -> str:
    """
    Возвращает Instagram Business ID (фиксированное значение).
    """
    return "17841422239487755"

def get_page_token() -> str:
    token = os.getenv("FB_PAGE_TOKEN") or os.getenv("PAGE_TOKEN")
    if not token:
        raise RuntimeError("ENV FB_PAGE_TOKEN (or PAGE_TOKEN) is required but not set.")
    return token.strip()

def read_state() -> Dict:
    if not STATE_JSON.exists():
        return {}
    try:
        return json.loads(STATE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_state(state: Dict) -> None:
    STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# === Data loaders ===
def load_latest_post() -> Dict:
    """
    Ожидается структура:
    {
      "latest": {
        "title": "...",
        "url": "https://blog.equalle.com/posts/....",
        "description": "...",
        "category": "...",
        "date": "2025-11-11T12:00:00Z"
      }
    }
    Поддерживается и плоский вариант, где корневой объект уже содержит поля поста.
    """
    if not CACHE_JSON.exists():
        raise FileNotFoundError(f"Cache not found: {CACHE_JSON}")
    data = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "latest" in data and isinstance(data["latest"], dict):
        return data["latest"]
    if isinstance(data, dict) and "title" in data and "url" in data:
        return data
    raise ValueError("Unexpected latest_posts.json structure — no usable 'latest' item.")

def pick_latest_image() -> Path:
    """
    Берёт последний изменённый JPEG в /images/ig/.
    Формат — .jpg (вертикальный 1080×1350).
    """
    if not IMAGES_DIR.exists():
        raise FileNotFoundError(f"Images dir not found: {IMAGES_DIR}")

    jpgs = sorted(
        [p for p in IMAGES_DIR.glob("*.jpg") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not jpgs:
        raise FileNotFoundError(f"No .jpg images in {IMAGES_DIR}")
    return jpgs[0]


# === Caption builder ===
def _truncate_caption(text: str, limit: int = 2200) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_nl = cut.rfind("\n")
    last_sp = cut.rfind(" ")
    idx = max(last_nl, last_sp, limit - 1)
    return cut[:idx].rstrip() + "…"

def build_caption(latest: Dict) -> str:
    title = (latest.get("title") or "").strip()
    url   = (latest.get("url") or "").strip()
    desc  = (latest.get("description") or "").strip()

    parts = []
    if title:
        parts.append(title)
    if desc:
        parts.append(desc)
    if url:
        parts.append(f"Read more 👉 {url}")
    parts.append("#Sanding #Woodworking #eQualle #Abrasives")
    caption = "\n\n".join(parts).strip()
    return _truncate_caption(caption, 2200)


# === Duplicate guard ===
def is_already_posted(state: Dict, latest_url: str) -> bool:
    ig_state = (state or {}).get("instagram", {})
    return bool(latest_url) and ig_state.get("last_url") == latest_url

def update_state_after_publish(state: Dict, post_id: str, image_name: str, url: str) -> None:
    if not isinstance(state, dict):
        state = {}
    if "instagram" not in state or not isinstance(state["instagram"], dict):
        state["instagram"] = {}
    state["instagram"]["last_post_id"] = post_id
    state["instagram"]["last_image"]   = image_name
    state["instagram"]["last_url"]     = url
    write_state(state)


# === Graph API calls ===
def graph_post(path: str, params: Dict) -> Dict:
    url = f"{GRAPH_BASE.rstrip('/')}/{path.lstrip('/')}"
    resp = requests.post(url, data=params, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"error": {"message": f"Non-JSON response: {resp.text[:200]}"},
                "status_code": resp.status_code}
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Graph API error ({resp.status_code}): {data}")
    return data

def create_media_container(ig_id: str, image_url: str, caption: str, token: str) -> str:
    params = {
        "image_url": image_url,
        "caption": caption,
        "access_token": token,
    }
    data = graph_post(f"{ig_id}/media", params)
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"No creation_id returned: {data}")
    return creation_id

def publish_media(ig_id: str, creation_id: str, token: str) -> str:
    params = {
        "creation_id": creation_id,
        "access_token": token,
    }
    data = graph_post(f"{ig_id}/media_publish", params)
    published_id = data.get("id")
    if not published_id:
        raise RuntimeError(f"No published media id returned: {data}")
    return published_id


# === Main ===
def main():
    mode  = get_mode()
    ig_id = get_ig_id()
    token = get_page_token()

    log(f"=== Instagram post run | MODE={mode} ===")

    latest = load_latest_post()
    latest_url   = (latest.get("url") or "").strip()
    latest_title = (latest.get("title") or "").strip()

    state = read_state()
    if is_already_posted(state, latest_url):
        log(f"Skip: already posted this URL → {latest_url}")
        return

    image_path = pick_latest_image()
    image_name = image_path.name

    PUBLIC_BASE = os.getenv("IG_IMAGES_BASE_URL", "https://blog.equalle.com/images/ig/")
    image_url = (PUBLIC_BASE.rstrip("/") + "/" + image_name).strip()

    caption = build_caption(latest)

    if mode != "prod":
        preview = {
            "image_name": image_name,
            "image_url": image_url,
            "caption": caption,
            "latest_url": latest_url,
            "latest_title": latest_title,
            "ig_business_id": ig_id,
            "ts": datetime.now(timezone.utc).isoformat()
        }
        _ensure_dirs()
        PREVIEW_OUT.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[DEV] Preview saved → {PREVIEW_OUT}")
        return

    log(f"Create media container for {image_name}")
    creation_id = create_media_container(ig_id, image_url, caption, token)
    log(f"Creation ID: {creation_id}")

    time.sleep(2)

    log("Publish media…")
    published_id = publish_media(ig_id, creation_id, token)
    log(f"Published IG media id: {published_id}")

    update_state_after_publish(state, published_id, image_name, latest_url)
    log("State updated (instagram).")
    log("=== Done ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        raise

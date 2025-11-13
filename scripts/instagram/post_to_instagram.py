# ============================================================
# File: scripts/instagram/post_to_instagram.py
# Full path: <repo_root>/scripts/instagram/post_to_instagram.py
# Purpose:
#   - Ищет IG-карточку (1080×1350 JPEG/PNG) по слагу поста:
#       * cлаг из URL (последний сегмент)
#       * слаг из title (slugify(title))
#   - Поддерживает имя файла формата: YYYY-MM-DD-<slug>.jpg|png
#   - Никогда не подставляет чужую картинку (нет fallback на случайные файлы)
#   - Формирует caption из data/cache/latest_posts.json
#   - Публикует через Graph API (или сохраняет предпросмотр в DEV)
#   - Обновляет data/state.json и пишет лог
#
# ENV:
#   MODE               = "prod" | "dev" (default "dev")
#   FB_PAGE_TOKEN      = <page access token>    # общий для FB/IG
#   IG_IMAGES_BASE_URL = "https://post.equalle.com/images/ig"
# ============================================================

from __future__ import annotations

import os
import re
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

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
    return "17841422239487755"  # фиксировано

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
def _pick_latest_from_list(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        raise ValueError("latest_posts.json list is empty.")

    def _dt(it: Dict[str, Any]) -> Optional[datetime]:
        pub = it.get("published") or it.get("date")
        if not pub:
            return None
        try:
            return parsedate_to_datetime(pub)
        except Exception:
            return None

    with_dates = [(it, _dt(it)) for it in items]
    dated = [pair for pair in with_dates if pair[1] is not None]
    if dated:
        latest_it = max(dated, key=lambda p: p[1])[0]
    else:
        latest_it = items[0]

    return {
        "title": (latest_it.get("title") or "").strip(),
        "url": (latest_it.get("url") or latest_it.get("link") or "").strip(),
        "description": (latest_it.get("description") or latest_it.get("summary") or "").strip(),
        "category": latest_it.get("category", ""),
        "date": latest_it.get("published", latest_it.get("date", "")),
    }

def load_latest_post() -> Dict[str, Any]:
    if not CACHE_JSON.exists():
        raise FileNotFoundError(f"Cache not found: {CACHE_JSON}")

    data = json.loads(CACHE_JSON.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return _pick_latest_from_list(data)

    if isinstance(data, dict) and "latest" in data and isinstance(data["latest"], dict):
        latest = data["latest"]
        return {
            "title": (latest.get("title") or "").strip(),
            "url": (latest.get("url") or latest.get("link") or "").strip(),
            "description": (latest.get("description") or latest.get("summary") or "").strip(),
            "category": latest.get("category", ""),
            "date": latest.get("date") or latest.get("published") or "",
        }

    if isinstance(data, dict) and ("title" in data) and ("url" in data or "link" in data):
        return {
            "title": (data.get("title") or "").strip(),
            "url": (data.get("url") or data.get("link") or "").strip(),
            "description": (data.get("description") or data.get("summary") or "").strip(),
            "category": data.get("category", ""),
            "date": data.get("date") or data.get("published") or "",
        }

    raise ValueError("Unexpected latest_posts.json structure — cannot derive latest post.")

# === Slug helpers ===
def slugify(text: str) -> str:
    text = (text or "").lower()
    # латиница/цифры → оставляем, прочее в дефисы
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text

def slug_from_url(url: str) -> str:
    try:
        path = urlparse(url or "").path.strip("/")
        last = path.split("/")[-1] if path else ""
        if "." in last:
            last = last.rsplit(".", 1)[0]
        return (last or "").lower()
    except Exception:
        return ""

# === Image picking (strict, no wrong fallbacks) ===
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")

def _match_image_candidates(desired_slugs: List[str]) -> Tuple[Optional[Path], List[str]]:
    """
    Ищем:
      1) Точное совпадение: YYYY-MM-DD-<slug>.(jpg|png)
      2) Имя файла содержит <slug> (игнорируя дату-префикс)
    Возвращаем (path|None, debug_messages).
    """
    debug: List[str] = []
    if not IMAGES_DIR.exists():
        raise FileNotFoundError(f"Images dir not found: {IMAGES_DIR}")

    files = [p for p in IMAGES_DIR.glob("*.*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    debug.append(f"[SCAN] Found {len(files)} images in {IMAGES_DIR}")

    # нормализованные имена для сравнения
    def norm_name(p: Path) -> str:
        name = p.stem.lower()
        name = DATE_PREFIX.sub("", name)  # срезаем возможный YYYY-MM-DD-
        return name

    # 1) точное совпадение с датой или без неё
    for want in desired_slugs:
        for p in files:
            if p.stem.lower().endswith(f"-{want}") or p.stem.lower() == want or norm_name(p) == want:
                debug.append(f"[MATCH:exact] {p.name} ⇐ {want}")
                return p, debug

    # 2) частичное — имя содержит нужный slug после среза даты
    for want in desired_slugs:
        for p in files:
            if want in norm_name(p):
                debug.append(f"[MATCH:contains] {p.name} ⇐ {want}")
                return p, debug

    debug.append("[MATCH:none] No image matched desired slugs.")
    return None, debug

def pick_image_for_latest(latest_title: str, latest_url: str) -> Path:
    desired = []
    title_slug = slugify(latest_title or "")
    if title_slug:
        desired.append(title_slug)
    url_slug = slug_from_url(latest_url or "")
    if url_slug and url_slug not in desired:
        desired.append(url_slug)

    log(f"Desired slugs: {desired or ['<empty>']}")

    img, dbg = _match_image_candidates(desired)
    for line in dbg:
        log(line)

    if not img:
        raise FileNotFoundError(
            "No IG card for this post. Expected image like 'YYYY-MM-DD-<slug>.jpg' "
            f"with slug in {desired}. Run card builder first."
        )
    return img

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
    params = {"image_url": image_url, "caption": caption, "access_token": token}
    data = graph_post(f"{ig_id}/media", params)
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"No creation_id returned: {data}")
    return creation_id

def publish_media(ig_id: str, creation_id: str, token: str) -> str:
    params = {"creation_id": creation_id, "access_token": token}
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

    # Ищем только релевантную карточку; без чужих fallback'ов
    image_path = pick_image_for_latest(latest_title, latest_url)
    image_name = image_path.name

    PUBLIC_BASE = os.getenv("IG_IMAGES_BASE_URL", "https://post.equalle.com/images/ig")
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

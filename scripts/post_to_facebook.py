# =========================================
# post_to_facebook.py
# Purpose:
#   - DEV: сохранить предпросмотр поста (без публикации)
#   - PROD: опубликовать пост на Facebook Page
# Inputs:
#   - MODE env: "dev" | "prod"
#   - FB_PAGE_ID, FB_PAGE_TOKEN (Secrets/Envs)
# Data:
#   - Читает: data/cache/latest_posts.json
#   - Пишет:  data/out/facebook_preview.json (DEV), data/state.json (PROD)
# Logs:
#   - data/logs/post_to_facebook.log
# =========================================

from __future__ import annotations
import os, sys, json, requests
from pathlib import Path
from typing import Dict, Optional

# запуск как модуль и как файл
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.logger import get_logger
from scripts.utils.cache_manager import next_unpublished, mark_published
from scripts.utils.post_formatter import format_facebook

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cache" / "latest_posts.json"
STATE_PATH = ROOT / "data" / "state.json"
OUT_DIR = ROOT / "data" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PLATFORM = "facebook"

def _load_cache() -> list[Dict]:
    if not CACHE_PATH.exists():
        return []
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_preview(item: Dict, caption: str) -> Path:
    out = OUT_DIR / "facebook_preview.json"
    out.write_text(json.dumps({
        "title": item.get("title"),
        "image": item.get("image"),
        "link": item.get("link"),
        "caption": caption
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return out

def _build_caption(item: Dict) -> str:
    # централизованный форматер + подрезка
    caption = format_facebook(item)
    return caption[:2000] + ("…" if len(caption) > 2000 else "")

def _post_photo(logger, page_id: str, token: str, image_url: str, caption: str) -> Optional[str]:
    r = requests.post(
        f"https://graph.facebook.com/v21.0/{page_id}/photos",
        data={"caption": caption, "url": image_url, "access_token": token},
        timeout=30,
    )
    if not r.ok:
        logger.error("FB /photos %s: %s", r.status_code, r.text)
        return None
    return (r.json().get("post_id") or r.json().get("id"))

def _post_feed(logger, page_id: str, token: str, caption: str, link: Optional[str]) -> Optional[str]:
    payload = {"message": caption, "access_token": token}
    if link:
        payload["link"] = link
    r = requests.post(f"https://graph.facebook.com/v21.0/{page_id}/feed", data=payload, timeout=30)
    if not r.ok:
        logger.error("FB /feed %s: %s", r.status_code, r.text)
        return None
    return r.json().get("id")

def main() -> None:
    logger = get_logger("post_to_facebook", level="info", keep_days=14)
    mode = (os.getenv("MODE", "dev") or "dev").strip().lower()
    is_prod = mode == "prod"
    logger.info("Start Facebook poster (mode=%s)", mode)

    items = _load_cache()
    if not items:
        logger.warning("Cache is empty: %s", CACHE_PATH)
        return

    # берём следующий не опубликованный
    post = next_unpublished(PLATFORM)
    if not post:
        logger.info("No unpublished items.")
        return

    caption = _build_caption(post)
    logger.info("Caption prepared (%d chars)", len(caption))

    if not is_prod:
        out = _save_preview(post, caption)
        logger.info("DEV preview saved: %s", out)
        return

    # PROD
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_TOKEN", "").strip()
    if not page_id or not token:
        raise SystemExit("FB_PAGE_ID/FB_PAGE_TOKEN are required in PROD mode")

    image_url = (post.get("image") or "").strip() or None
    if image_url:
        logger.info("Publishing photo post…")
        post_id = _post_photo(logger, page_id, token, image_url, caption)
    else:
        logger.info("Publishing feed post…")
        post_id = _post_feed(logger, page_id, token, caption, post.get("link"))

    if not post_id:
        logger.error("Publish failed.")
        return

    logger.info("Published: %s", post_id)
    # отмечаем опубликованным
    link = post.get("link", "")
    if link:
        mark_published(PLATFORM, link)
        logger.info("State updated: %s", STATE_PATH)

if __name__ == "__main__":
    main()

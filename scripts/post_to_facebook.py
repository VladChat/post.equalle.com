# =========================================
# post_to_facebook.py
# Purpose:
#   - DEV: сохраняет предпросмотр поста (без публикации)
#   - PROD: публикует пост на Facebook Page через единый API-слой
# Data I/O:
#   - Reads:  data/cache/latest_posts.json
#   - Writes: data/out/facebook_preview.json (DEV), data/state.json (PROD)
# Logs:
#   - data/logs/post_to_facebook.log
# ENV:
#   - MODE: "dev" (default) | "prod"
#   - FB_PAGE_ID, FB_PAGE_TOKEN (required in PROD)
# =========================================

from __future__ import annotations
import os, sys, json
from pathlib import Path
from typing import Dict, Optional

# allow running directly
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.logger import get_logger
from scripts.utils.social_api import publish_photo, publish_feed
from scripts.utils.post_formatter import format_facebook  # общая разметка подписи

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cache" / "latest_posts.json"
STATE_PATH = ROOT / "data" / "state.json"
OUT_DIR = ROOT / "data" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PLATFORM = "facebook"


# ---------------------------
# Helpers
# ---------------------------
def _load_cache() -> list[Dict]:
    if not CACHE_PATH.exists():
        return []
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_state() -> Dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"published_links": []}


def _save_state(state: Dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _pick_next_item(items: list[Dict], published_links: set[str]) -> Optional[Dict]:
    for it in items:
        link = (it.get("link") or "").strip()
        if link and link not in published_links:
            return it
    return None


def _build_caption(item: Dict) -> str:
    # централизованный форматер + ограничение длины
    caption = format_facebook(item)
    return caption[:2000] + ("…" if len(caption) > 2000 else "")


def _save_preview(item: Dict, caption: str) -> Path:
    out = OUT_DIR / "facebook_preview.json"
    out.write_text(
        json.dumps(
            {
                "title": item.get("title"),
                "image": item.get("image"),
                "link": item.get("link"),
                "caption": caption,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out


# ---------------------------
# Main
# ---------------------------
def main() -> None:
    logger = get_logger("post_to_facebook", level="info", keep_days=14)
    mode = (os.getenv("MODE", "dev") or "dev").strip().lower()
    is_prod = mode == "prod"
    logger.info("Facebook poster start (mode=%s)", mode)

    items = _load_cache()
    if not items:
        logger.warning("Cache empty: %s", CACHE_PATH)
        return

    state = _load_state()
    published = set(state.get("published_links", []))
    item = _pick_next_item(items, published)

    if not item:
        logger.info("No unpublished items.")
        return

    caption = _build_caption(item)
    logger.info("Caption prepared (%d chars)", len(caption))

    if not is_prod:
        out = _save_preview(item, caption)
        logger.info("DEV preview saved: %s", out)
        return

    # === PROD publish ===
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_TOKEN", "").strip()
    if not page_id or not token:
        raise SystemExit("FB_PAGE_ID and FB_PAGE_TOKEN are required in PROD mode.")

    image_url = (item.get("image") or "").strip() or None
    post_id: Optional[str] = None

    if image_url:
        logger.info("Publishing photo via API layer…")
        post_id = publish_photo(PLATFORM, page_id, token, caption, image_url, logger=logger)
        # fallback на feed, если картинка не прошла
        if not post_id:
            logger.warning("Photo publish failed. Fallback to /feed with link.")
            post_id = publish_feed(PLATFORM, page_id, token, caption, item.get("link"), logger=logger)
    else:
        logger.info("Publishing feed (text/link) via API layer…")
        post_id = publish_feed(PLATFORM, page_id, token, caption, item.get("link"), logger=logger)

    if not post_id:
        logger.error("Publish failed.")
        return

    logger.info("Published: %s", post_id)

    # отметим как опубликованный
    link = (item.get("link") or "").strip()
    if link:
        published.add(link)
        state["published_links"] = sorted(published)
        _save_state(state)
        logger.info("State updated: %s", STATE_PATH)


if __name__ == "__main__":
    main()

# ============================================================
# File: scripts/post_to_facebook_scr.py
# Purpose:
#   Публикует посты на Facebook, используя скриншоты страниц
#   (вместо оригинальных изображений из RSS).
# Mode:
#   Всегда PROD, реально постит на страницу.
# ============================================================

from __future__ import annotations
import os
import sys
import json
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

# allow running directly
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.logger import get_logger
from scripts.utils.social_api import publish_photo, publish_feed
from scripts.utils.fb_post_formatter import format_facebook
from scripts.media.fb_screenshot_manager import make_screenshot_if_needed

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cache" / "latest_posts.json"
STATE_PATH = ROOT / "data" / "state.json"

CONFIG_PATH = Path(__file__).parent / "config.json"
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
    return {"published_links": [], "screenshots_done": []}


def _save_state(state: Dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _pick_next_item(items: list[Dict], published_links: set[str]) -> Optional[Dict]:
    for it in items:
        link = (it.get("link") or "").strip()
        if link and link not in published_links:
            return it
    return None


def _build_caption(item: Dict) -> str:
    caption = format_facebook(item)
    return caption[:2000] + ("…" if len(caption) > 2000 else "")


def _load_config() -> Dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing config file: {CONFIG_PATH}")
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Failed to read config.json: {e}")


def _get_page_id(cfg: Dict) -> str:
    fb = (cfg.get("platforms") or {}).get("facebook") or {}
    page_id = (fb.get("page_id") or "").strip()
    if not page_id:
        raise SystemExit("Facebook page_id not found in scripts/config.json → platforms.facebook.page_id")
    return page_id


def _derive_screenshot_path(link: str) -> Path:
    p = urlparse(link or "")
    slug = Path(p.path.rstrip("/")).name or "home"
    slug = slug[:80] or "post"
    out = ROOT / "data" / "screens" / f"{slug}.webp"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------
# Main
# ---------------------------
def main() -> None:
    logger = get_logger("post_to_facebook_scr", level="info", keep_days=14)

    cfg = _load_config()
    page_id = _get_page_id(cfg)
    token = os.getenv("FB_PAGE_TOKEN", "").strip()
    if not token:
        raise SystemExit("FB_PAGE_TOKEN is required for screenshot posting (GitHub Secret).")

    logger.info("Facebook screenshot poster start (PROD mode)")

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

    link = (item.get("link") or "").strip()
    if not link:
        logger.warning("Item has no link. Skipping.")
        return

    # === Делаем или берём скриншот ===
    shot_path = _derive_screenshot_path(link)
    saved = make_screenshot_if_needed(link, shot_path, logger)
    if not saved:
        logger.warning("No screenshot available; skipping post.")
        return

    item["image"] = saved
    caption = _build_caption(item)
    logger.info("Caption prepared (%d chars)", len(caption))

    # === Публикуем пост ===
    post_id: Optional[str] = None
    try:
        logger.info("Publishing screenshot to Facebook via API…")
        post_id = publish_photo(PLATFORM, page_id, token, caption, item["image"], logger=logger)
        if not post_id:
            logger.warning("Photo publish failed. Fallback to /feed with link.")
            post_id = publish_feed(PLATFORM, page_id, token, caption, item["link"], logger=logger)
    except Exception as e:
        logger.error("Publish failed: %s", e)
        return

    if not post_id:
        logger.error("Failed to publish screenshot post.")
        return

    logger.info("Published successfully: %s", post_id)

    # === Обновляем state.json ===
    published.add(link)
    state["published_links"] = sorted(published)
    _save_state(state)
    logger.info("State updated: %s", STATE_PATH)


if __name__ == "__main__":
    main()

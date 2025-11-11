# =========================================
# post_to_facebook.py
# Purpose:
#   - DEV: сохраняет предпросмотр поста (без публикации)
#   - PROD: публикует пост на Facebook Page через единый API-слой
# Data I/O:
#   - Reads:  data/cache/latest_posts.json, scripts/config.json
#   - Writes: data/out/facebook_preview.json (DEV), data/state.json (PROD)
# Logs:
#   - data/logs/post_to_facebook.log
# ENV:
#   - MODE: "dev" | "prod"  (ENV имеет приоритет над settings.mode из config.json)
#   - FB_PAGE_TOKEN (required in PROD)
# Notes:
#   - FB_PAGE_ID больше НЕ нужен в ENV: берём page_id из scripts/config.json
# =========================================

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
from scripts.utils.fb_post_formatter import format_facebook  # форматер только для Facebook
from scripts.media.screenshot import capture_screenshot  # ⬅️ добавлено

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cache" / "latest_posts.json"
STATE_PATH = ROOT / "data" / "state.json"
OUT_DIR = ROOT / "data" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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


def _resolve_mode(cfg: Dict) -> str:
    # ENV MODE имеет приоритет, иначе берём из config.settings.mode, по умолчанию dev
    env_mode = (os.getenv("MODE") or "").strip().lower()
    if env_mode in ("dev", "prod"):
        return env_mode
    return ((cfg.get("settings") or {}).get("mode") or "dev").strip().lower()


def _derive_screenshot_path(link: str) -> Path:
    """
    Строит путь для скриншота на основе URL поста:
    data/screens/{slug}.webp, где slug — последний сегмент пути.
    """
    p = urlparse(link or "")
    slug = Path(p.path.rstrip("/")).name or "home"
    # На случай очень длинных хвостов или пустоты
    slug = slug[:80] or "post"
    out = ROOT / "data" / "screens" / f"{slug}.webp"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------
# Main
# ---------------------------
def main() -> None:
    logger = get_logger("post_to_facebook", level="info", keep_days=14)

    cfg = _load_config()
    mode = _resolve_mode(cfg)
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

    # === DEV: делаем скриншот страницы поста и прописываем его в item["image"]
    # (В PROD не трогаем — там ожидается image_url, пригодный для публикации через API)
    if not is_prod:
        link = (item.get("link") or "").strip()
        if link:
            try:
                shot_path = _derive_screenshot_path(link)
                saved = capture_screenshot(
                    link,
                    out_path=str(shot_path),
                    width=1920,
                    height=1080,
                    full_page=True
                )
                item["image"] = saved  # локальный путь попадёт в preview.json
                logger.info("Screenshot created: %s", saved)
            except Exception as e:
                logger.warning("Screenshot failed: %s", e)

    caption = _build_caption(item)
    logger.info("Caption prepared (%d chars)", len(caption))

    if not is_prod:
        out = _save_preview(item, caption)
        logger.info("DEV preview saved: %s", out)
        return

    # === PROD publish ===
    page_id = _get_page_id(cfg)  # из config.json, не из ENV
    token = os.getenv("FB_PAGE_TOKEN", "").strip()
    if not token:
        raise SystemExit("FB_PAGE_TOKEN is required in PROD mode (GitHub Secret).")

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

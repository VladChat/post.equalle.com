# ============================================================
# File: scripts/media/fb_screenshot_manager.py
# Purpose: Manage Facebook screenshot creation and deduplication
# ============================================================

from pathlib import Path
from scripts.media.screenshot import capture_screenshot
import json
import logging

STATE_PATH = Path("data/state.json")

def _load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"published_links": [], "screenshots_done": []}


def _save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def make_screenshot_if_needed(link: str, out_path: Path, logger: logging.Logger) -> str | None:
    """
    Создаёт скриншот страницы, если такого ещё нет.
    - Проверяет наличие ссылки в state.json → screenshots_done
    - Если ссылка уже есть → пропускает
    - Если нет → делает скриншот, сохраняет и добавляет запись в state.json
    """
    state = _load_state()
    screenshots_done = set(state.get("screenshots_done", []))

    if link in screenshots_done:
        logger.info("Screenshot already exists for this link. Skipping.")
        return str(out_path) if out_path.exists() else None

    try:
        saved = capture_screenshot(
            link,
            out_path=str(out_path),
            width=1920,
            height=1080,
            full_page=True
        )
        screenshots_done.add(link)
        state["screenshots_done"] = sorted(screenshots_done)
        _save_state(state)
        logger.info("Screenshot created and recorded: %s", saved)
        return saved
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)
        return None

# ============================================
# File: instagram_reels/post_one_reel.py
# Purpose: Post exactly 1 Instagram Reel per run (from local manifests) and persist independent state
# Notes:
# - Instagram Graph API publishing uses container -> status -> publish flow.
# - To publish a Reel: POST /{ig-user-id}/media with media_type=REELS, video_url, caption,
#   then poll the container status_code until FINISHED, then POST /{ig-user-id}/media_publish.
# - Instagram does not have a separate "title" field for Reels; it is part of the caption.
# ============================================

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# ----- Config (safe defaults; override via env) -----

# Default IG Business/Creator User ID: equalleabrasives (can be overridden)
DEFAULT_IG_USER_ID = "17841422239487755"

# Graph API version (override if you pin a different version)
DEFAULT_GRAPH_API_VERSION = "v21.0"

# Manifest ordering (daily starting point rotates)
MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

# Caption limits (Instagram caption max is 2200 chars)
CAPTION_MAX = 2200

MAX_ATTEMPTS_PER_VIDEO = 3

# Container status polling
STATUS_POLL_TIMEOUT_SEC = 900
STATUS_POLL_INTERVAL_SEC = 10


@dataclass(frozen=True)
class ReelItem:
    manifest_name: str
    video_url: str
    filename: str
    title: str
    description: str


def repo_root_from_this_file() -> Path:
    # instagram_reels/post_one_reel.py -> repo root = two levels up
    return Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def utc_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def build_caption(title: str, description: str) -> str:
    title = (title or "").strip()
    description = (description or "").strip()

    if title and description:
        caption = f"{title}\n\n{description}"
    else:
        caption = title or description

    return truncate(caption, CAPTION_MAX)


def manifest_cycle_for_today(state: Dict[str, Any]) -> List[str]:
    """Rotate the *starting* manifest once per UTC day."""
    rot = state.setdefault("rotation", {})
    today = utc_today()

    last_day = (rot.get("last_day") or "").strip()
    idx_raw = rot.get("manifest_index")

    try:
        idx = int(idx_raw) if idx_raw is not None else -1
    except Exception:
        idx = -1

    if last_day != today:
        idx = (idx + 1) % len(MANIFEST_FILES_ORDER) if idx >= 0 else 0
        rot["manifest_index"] = idx
        rot["last_day"] = today

    start = int(rot.get("manifest_index", 0) or 0) % len(MANIFEST_FILES_ORDER)
    return MANIFEST_FILES_ORDER[start:] + MANIFEST_FILES_ORDER[:start]


def ensure_required_fields(raw: Dict[str, Any], manifest_name: str) -> ReelItem:
    video_url = (raw.get("video_url") or "").strip()
    if not video_url:
        raise ValueError(f"[{manifest_name}] missing 'video_url'")

    filename = (raw.get("filename") or "").strip()
    if not filename:
        filename = video_url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1] or "video.mp4"

    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "").strip()

    return ReelItem(
        manifest_name=manifest_name,
        video_url=video_url,
        filename=filename,
        title=title,
        description=description,
    )


def pick_next_item(manifest_dir: Path, state: Dict[str, Any]) -> Optional[ReelItem]:
    """Pick 1 item using today's manifest rotation order."""
    st_items = state.get("items", {}) or {}
    ordered_names = manifest_cycle_for_today(state)

    existing_paths = [manifest_dir / name for name in ordered_names if (manifest_dir / name).exists()]
    if not existing_paths:
        raise FileNotFoundError(f"No manifest json files found in: {manifest_dir}")

    for path in existing_paths:
        manifest_name = path.name
        data = load_json(path)

        items = data.get("items")
        if not isinstance(items, list):
            raise ValueError(f"[{manifest_name}] expected top-level 'items' as array")

        for raw in items:
            if not isinstance(raw, dict):
                continue

            it = ensure_required_fields(raw, manifest_name)

            rec = st_items.get(it.video_url) or {}
            if rec.get("result") == "success":
                continue

            attempts = int(rec.get("attempts", 0) or 0)
            if attempts >= MAX_ATTEMPTS_PER_VIDEO:
                continue

            return it

    return None


def graph_base(version: str) -> str:
    version = (version or DEFAULT_GRAPH_API_VERSION).strip()
    if not version.startswith("v"):
        version = "v" + version
    return f"https://graph.facebook.com/{version}"


def create_reel_container(ig_user_id: str, token: str, version: str, video_url: str, caption: str, *, share_to_feed: bool) -> str:
    """
    POST /{ig-user-id}/media
      media_type=REELS
      video_url=<url>
      caption=<caption>
      share_to_feed=true|false

    Returns: container_id (creation_id)
    """
    url = f"{graph_base(version)}/{ig_user_id}/media"

    data = {
        "access_token": token,
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
    }
    # share_to_feed is optional; keep explicit for predictability
    data["share_to_feed"] = "true" if share_to_feed else "false"

    resp = requests.post(url, data=data, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create_container failed: HTTP {resp.status_code}: {resp.text[:800]}")
    j = resp.json()
    cid = (j.get("id") or "").strip()
    if not cid:
        raise RuntimeError(f"create_container missing id: {j}")
    return cid


def get_container_status(container_id: str, token: str, version: str) -> Dict[str, Any]:
    """GET /{ig-container-id}?fields=status_code,status,error_message"""
    url = f"{graph_base(version)}/{container_id}"
    params = {
        "fields": "status_code,status,error_message",
        "access_token": token,
    }
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"container_status failed: HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def wait_container_finished(container_id: str, token: str, version: str) -> Dict[str, Any]:
    deadline = time.time() + STATUS_POLL_TIMEOUT_SEC
    last: Dict[str, Any] = {}

    while time.time() < deadline:
        last = get_container_status(container_id, token, version)
        status_code = str(last.get("status_code") or "").upper().strip()

        if status_code == "FINISHED":
            return last
        if status_code == "ERROR":
            detail = last.get("error_message") or last.get("status") or last
            raise RuntimeError(f"container ERROR: {detail}")

        # IN_PROGRESS, EXPIRED, etc.
        time.sleep(STATUS_POLL_INTERVAL_SEC)

    return last


def publish_container(ig_user_id: str, token: str, version: str, creation_id: str) -> str:
    """POST /{ig-user-id}/media_publish?creation_id=... -> returns IG media id"""
    url = f"{graph_base(version)}/{ig_user_id}/media_publish"
    resp = requests.post(url, data={"access_token": token, "creation_id": creation_id}, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"media_publish failed: HTTP {resp.status_code}: {resp.text[:800]}")
    j = resp.json()
    mid = (j.get("id") or "").strip()
    if not mid:
        raise RuntimeError(f"media_publish missing id: {j}")
    return mid


def update_state_for_attempt(
    state: Dict[str, Any],
    item: ReelItem,
    result: str,
    *,
    container_id: Optional[str] = None,
    media_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    st_items = state.setdefault("items", {})
    rec = st_items.get(item.video_url) or {}

    attempts = int(rec.get("attempts", 0) or 0) + 1
    rec.update(
        {
            "video_url": item.video_url,
            "filename": item.filename,
            "manifest": item.manifest_name,
            "title": item.title,
            "description": item.description,
            "caption": build_caption(item.title, item.description),
            "result": result,  # "success" | "failed"
            "attempts": attempts,
            "last_ts_utc": utc_now_iso(),
        }
    )
    if container_id:
        rec["container_id"] = str(container_id)
    if media_id:
        rec["media_id"] = str(media_id)
    if error:
        rec["error"] = error

    st_items[item.video_url] = rec

    state.setdefault("runs", []).append(
        {
            "ts_utc": utc_now_iso(),
            "video_url": item.video_url,
            "filename": item.filename,
            "manifest": item.manifest_name,
            "result": result,
            "container_id": container_id,
            "media_id": media_id,
            "error": error,
        }
    )


def main() -> int:
    token = (
        os.getenv("IG_ACCESS_TOKEN")
        or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or os.getenv("FB_PAGE_TOKEN")
        or os.getenv("FB_PAGE_ACCESS_TOKEN")
        or os.getenv("FACEBOOK_PAGE_TOKEN")
        or ""
    ).strip()
    if not token:
        print("ERROR: Missing env IG_ACCESS_TOKEN (or INSTAGRAM_ACCESS_TOKEN / META_ACCESS_TOKEN / FB_PAGE_TOKEN)")
        return 2

    ig_user_id = (os.getenv("IG_USER_ID") or os.getenv("IG_BUSINESS_ID") or DEFAULT_IG_USER_ID).strip()
    version = (os.getenv("GRAPH_API_VERSION") or DEFAULT_GRAPH_API_VERSION).strip()

    share_to_feed = (os.getenv("IG_REELS_SHARE_TO_FEED") or "true").strip().lower() in ("1", "true", "yes")

    repo_root = repo_root_from_this_file()
    manifest_dir = repo_root / "instagram_reels" / "manifests"
    state_path = repo_root / "instagram_reels" / "state" / "instagram_reels_post_state.json"

    if state_path.exists():
        state = load_json(state_path)
    else:
        state = {"version": 1, "rotation": {}, "items": {}, "runs": []}

    dry_run = (os.getenv("IG_REELS_DRY_RUN") or os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes")

    item = pick_next_item(manifest_dir, state)
    if not item:
        save_json_atomic(state_path, state)
        print("No pending IG reels found (all posted or max attempts reached).")
        return 0

    caption = build_caption(item.title, item.description)

    if dry_run:
        save_json_atomic(state_path, state)
        print("DRY RUN: would post 1 IG Reel:")
        print(f"  manifest: {item.manifest_name}")
        print(f"  filename: {item.filename}")
        print(f"  video_url: {item.video_url}")
        print(f"  caption: {caption}")
        print(f"  share_to_feed: {share_to_feed}")
        return 0

    container_id: Optional[str] = None
    media_id: Optional[str] = None

    try:
        # 1) Create container
        container_id = create_reel_container(
            ig_user_id=ig_user_id,
            token=token,
            version=version,
            video_url=item.video_url,
            caption=caption,
            share_to_feed=share_to_feed,
        )

        # 2) Wait until container is ready
        st = wait_container_finished(container_id, token, version)

        # 3) Publish
        media_id = publish_container(ig_user_id, token, version, container_id)

        update_state_for_attempt(state, item, "success", container_id=container_id, media_id=media_id, error=None)
        save_json_atomic(state_path, state)

        print(f"OK: Posted 1 IG Reel. ig_user_id={ig_user_id} media_id={media_id} manifest={item.manifest_name}")
        try:
            print("container_status:", st.get("status_code"))
        except Exception:
            pass
        return 0

    except Exception as e:
        err = str(e)[:1500]
        update_state_for_attempt(state, item, "failed", container_id=container_id, media_id=media_id, error=err)
        save_json_atomic(state_path, state)
        print(f"FAILED: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

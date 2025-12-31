# ============================================
# File: facebook_reels/post_one_reel.py
# Purpose: Post exactly 1 Facebook Page Reel per run (from local manifests) and persist independent state
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

# Default Page ID: eQualle Abrasives (can be overridden)
DEFAULT_FB_PAGE_ID = "325670187920349"

# Graph API version (override if you pin a different version)
DEFAULT_GRAPH_API_VERSION = "v21.0"

# Manifest ordering (daily starting point rotates)
MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

# Limits (keep captions readable)
TITLE_MAX = 100
DESC_MAX = 2000  # FB caption limit is larger; keep some bound anyway

MAX_ATTEMPTS_PER_VIDEO = 3

STATUS_POLL_TIMEOUT_SEC = 600
STATUS_POLL_INTERVAL_SEC = 5


@dataclass(frozen=True)
class ReelItem:
    manifest_name: str
    video_url: str
    filename: str
    title: str
    description: str


def repo_root_from_this_file() -> Path:
    # facebook_reels/post_one_reel.py -> repo root = two levels up
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


def manifest_cycle_for_today(state: Dict[str, Any]) -> List[str]:
    """
    Rotate the *starting* manifest once per UTC day.
    If run multiple times same day -> same start.
    """
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

    title = truncate(str(raw.get("title") or ""), TITLE_MAX)
    description = truncate(str(raw.get("description") or ""), DESC_MAX)

    return ReelItem(
        manifest_name=manifest_name,
        video_url=video_url,
        filename=filename,
        title=title,
        description=description,
    )


def pick_next_item(manifest_dir: Path, state: Dict[str, Any]) -> Optional[ReelItem]:
    """
    Pick 1 item using today's manifest rotation order.
    Tries the chosen manifest first; if it has no pending items, falls through to next manifests.
    """
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


def create_reel_upload_session(page_token: str, version: str) -> Dict[str, Any]:
    """
    Step 1: Create Reel upload session.
    POST /me/video_reels?upload_phase=start&access_token={page_token}
    Returns: { video_id, upload_url }
    """
    url = f"{graph_base(version)}/me/video_reels"
    resp = requests.post(url, params={"access_token": page_token, "upload_phase": "start"}, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create_reel failed: HTTP {resp.status_code}: {resp.text[:800]}")
    data = resp.json()
    if "video_id" not in data or "upload_url" not in data:
        raise RuntimeError(f"create_reel response missing fields: {data}")
    return data


def upload_hosted_video(upload_url: str, page_token: str, video_url: str) -> None:
    """
    Step 2.B: Upload hosted video by URL.
    POST upload_url with headers:
      Authorization: OAuth {page_token}
      file_url: {video_url}
    """
    headers = {
        "Authorization": f"OAuth {page_token}",
        "file_url": video_url,
    }
    resp = requests.post(upload_url, headers=headers, timeout=180)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"upload_hosted failed: HTTP {resp.status_code}: {resp.text[:800]}")
    data = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {}
    if isinstance(data, dict) and data.get("success") is not True:
        # Some responses are {"success": true}
        # If missing success, still treat 2xx as ok.
        pass


def publish_reel(page_token: str, version: str, video_id: str, title: str, description: str) -> Dict[str, Any]:
    """
    Step 4: Publish reel (finish upload phase).
    POST /me/video_reels?video_id=...&upload_phase=finish&video_state=PUBLISHED&title=...&description=...
    """
    url = f"{graph_base(version)}/me/video_reels"
    params = {
        "access_token": page_token,
        "video_id": str(video_id),
        "upload_phase": "finish",
        "video_state": "PUBLISHED",
    }
    # Optional fields
    if title:
        params["title"] = title
    if description:
        params["description"] = description

    resp = requests.post(url, params=params, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"publish_reel failed: HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json() if resp.text else {}


def get_upload_status(page_token: str, version: str, video_id: str) -> Dict[str, Any]:
    """
    Step 3 (optional): GET /{video_id}?fields=status&access_token=...
    """
    url = f"{graph_base(version)}/{video_id}"
    resp = requests.get(url, params={"fields": "status", "access_token": page_token}, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"status failed: HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def wait_until_published(page_token: str, version: str, video_id: str) -> Dict[str, Any]:
    deadline = time.time() + STATUS_POLL_TIMEOUT_SEC
    last = {}

    while time.time() < deadline:
        last = get_upload_status(page_token, version, video_id)
        st = (last.get("status") or {})

        # Typical shape:
        # status: { video_status, uploading_phase: {status}, processing_phase: {status}, publishing_phase: {status} }
        uploading = ((st.get("uploading_phase") or {}).get("status") or "").lower()
        processing = ((st.get("processing_phase") or {}).get("status") or "").lower()
        publishing = ((st.get("publishing_phase") or {}).get("status") or "").lower()
        video_status = (st.get("video_status") or "").lower()

        # success condition: publishing complete (some accounts may not fill all fields)
        if publishing == "complete":
            return last
        if video_status in ("ready", "published"):
            return last

        # fail conditions
        if uploading in ("error", "failed") or processing in ("error", "failed") or publishing in ("error", "failed"):
            raise RuntimeError(f"status indicates failure: {st}")

        time.sleep(STATUS_POLL_INTERVAL_SEC)

    return last


def update_state_for_attempt(
    state: Dict[str, Any],
    item: ReelItem,
    result: str,
    *,
    video_id: Optional[str] = None,
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
            "result": result,  # "success" | "failed"
            "attempts": attempts,
            "last_ts_utc": utc_now_iso(),
        }
    )
    if video_id:
        rec["video_id"] = str(video_id)
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
            "video_id": video_id,
            "error": error,
        }
    )


def main() -> int:
    page_token = (os.getenv("FB_PAGE_TOKEN") or os.getenv("FB_PAGE_ACCESS_TOKEN") or os.getenv("FACEBOOK_PAGE_TOKEN") or "").strip()
    if not page_token:
        print("ERROR: Missing env FB_PAGE_TOKEN (or FB_PAGE_ACCESS_TOKEN / FACEBOOK_PAGE_TOKEN)")
        return 2

    page_id = (os.getenv("FB_PAGE_ID") or DEFAULT_FB_PAGE_ID).strip()
    version = (os.getenv("GRAPH_API_VERSION") or DEFAULT_GRAPH_API_VERSION).strip()

    repo_root = repo_root_from_this_file()
    manifest_dir = repo_root / "facebook_reels" / "manifests"
    state_path = repo_root / "facebook_reels" / "state" / "facebook_reels_post_state.json"

    state = {}
    if state_path.exists():
        state = load_json(state_path)
    else:
        state = {"version": 1, "rotation": {}, "items": {}, "runs": []}

    dry_run = (os.getenv("FB_REELS_DRY_RUN") or os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes")

    # Pick 1 reel item using daily rotation (and fallback across manifests if needed)
    item = pick_next_item(manifest_dir, state)
    if not item:
        save_json_atomic(state_path, state)  # persists rotation day/index updates
        print("No pending reels found (all posted or max attempts reached).")
        return 0

    if dry_run:
        save_json_atomic(state_path, state)  # persist rotation day/index updates
        print("DRY RUN: would post 1 FB Reel:")
        print(f"  manifest: {item.manifest_name}")
        print(f"  filename: {item.filename}")
        print(f"  video_url: {item.video_url}")
        print(f"  title: {item.title}")
        print(f"  description: {item.description}")
        return 0

    video_id = None
    try:
        # 1) Create upload session
        created = create_reel_upload_session(page_token, version)
        video_id = str(created["video_id"])
        upload_url = str(created["upload_url"])

        # 2) Upload hosted video by URL (no download needed)
        upload_hosted_video(upload_url, page_token, item.video_url)

        # 3) Publish
        publish_reel(page_token, version, video_id, item.title, item.description)

        # 4) Poll (optional but useful)
        st = wait_until_published(page_token, version, video_id)

        update_state_for_attempt(state, item, "success", video_id=video_id, error=None)
        save_json_atomic(state_path, state)

        print(f"OK: Posted 1 FB Reel. page_id={page_id} video_id={video_id} manifest={item.manifest_name}")
        # Print compact status for debugging
        try:
            print("status:", (st.get("status") or {}).get("video_status"))
        except Exception:
            pass
        return 0

    except Exception as e:
        err = str(e)[:1000]
        update_state_for_attempt(state, item, "failed", video_id=video_id, error=err)
        save_json_atomic(state_path, state)
        print(f"FAILED: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

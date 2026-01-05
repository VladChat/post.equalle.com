# ============================================
# File: youtube-post/post_one_video.py
# Purpose: Post exactly 1 YouTube video per run (from local manifests) and persist independent state
# Notes:
# - Uses the same manifest format as your Pinterest/FB scripts: manifests/*.json -> { items: [...] }
# - Uploading to YouTube requires OAuth 2.0 (refresh token). API key alone won't work.
# ============================================

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from youtube_auth import get_access_token


# ----- Config (safe defaults; override via env) -----

# Manifest ordering (daily starting point rotates)
MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

# Limits (keep metadata readable)
TITLE_MAX = 100
DESC_MAX = 5000  # YouTube allows much more; keep reasonable

MAX_ATTEMPTS_PER_VIDEO = 3

# Download timeout safety (seconds)
DOWNLOAD_TIMEOUT = 600

# Defaults for video metadata
DEFAULT_PRIVACY_STATUS = "public"  # public | unlisted | private
DEFAULT_CATEGORY_ID = "26"  # 26 = Howto & Style


@dataclass(frozen=True)
class VideoItem:
    manifest_name: str
    video_url: str
    filename: str
    title: str
    description: str


def base_dir_from_this_file() -> Path:
    # youtube-post/post_one_video.py -> base dir = youtube-post/
    return Path(__file__).resolve().parent



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
    """Rotate the *starting* manifest once per UTC day.
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


def ensure_required_fields(raw: Dict[str, Any], manifest_name: str) -> VideoItem:
    video_url = (raw.get("video_url") or "").strip()
    if not video_url:
        raise ValueError(f"[{manifest_name}] missing 'video_url'")

    filename = (raw.get("filename") or "").strip()
    if not filename:
        filename = video_url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1] or "video.mp4"

    title = truncate(str(raw.get("title") or ""), TITLE_MAX)
    description = truncate(str(raw.get("description") or ""), DESC_MAX)

    return VideoItem(
        manifest_name=manifest_name,
        video_url=video_url,
        filename=filename,
        title=title,
        description=description,
    )


def pick_next_item(manifest_dir: Path, state: Dict[str, Any]) -> Optional[VideoItem]:
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


def download_video_to_temp(url: str, filename: str) -> Path:
    """Download URL to a temp file and return path."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="yt_upload_"))
    out_path = tmp_dir / filename

    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
        r.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return out_path


def youtube_upload_video_http(
    *,
    access_token: str,
    file_path: Path,
    title: str,
    description: str,
    privacy_status: str,
    category_id: str,
    made_for_kids: bool,
    tags: Optional[List[str]] = None,
) -> str:
    """Resumable upload and return YouTube video ID."""
    meta: Dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }
    if tags:
        meta["snippet"]["tags"] = tags

    init_url = "https://www.googleapis.com/upload/youtube/v3/videos"
    params = {"uploadType": "resumable", "part": "snippet,status"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8",
        "X-Upload-Content-Type": "video/*",
        "X-Upload-Content-Length": str(file_path.stat().st_size),
    }

    init = requests.post(init_url, params=params, headers=headers, json=meta, timeout=120)
    init.raise_for_status()

    upload_url = (init.headers.get("Location") or "").strip()
    if not upload_url:
        raise RuntimeError(f"Resumable init missing Location header. Status={init.status_code} Body={init.text[:500]}")

    with file_path.open("rb") as f:
        up_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/*",
        }
        up = requests.put(upload_url, headers=up_headers, data=f, timeout=DOWNLOAD_TIMEOUT)
        up.raise_for_status()
        resp = up.json()

    video_id = (resp.get("id") or "").strip()
    if not video_id:
        raise RuntimeError(f"Upload finished but no video id returned: {resp}")
    return video_id



def main() -> int:
    base_dir = base_dir_from_this_file()

    # Paths (autonomous)
    manifest_dir = base_dir / "manifests"
    state_path = base_dir / "state" / "youtube_post_state.json"

    # Load or init state
    if state_path.exists():
        state = load_json(state_path)
    else:
        state = {"version": 1, "rotation": {"manifest_index": -1, "last_day": ""}, "items": {}, "runs": []}

    item = pick_next_item(manifest_dir, state)
    if not item:
        print("No pending items found in manifests (everything posted or max attempts reached).")
        save_json_atomic(state_path, state)
        return 0

    # Ensure item record exists
    st_items = state.setdefault("items", {})
    if not isinstance(st_items, dict):
        state["items"] = {}
        st_items = state["items"]

    rec = st_items.get(item.video_url) or {}
    attempts = int(rec.get("attempts", 0) or 0) + 1

    rec.update(
        {
            "video_url": item.video_url,
            "filename": item.filename,
            "manifest": item.manifest_name,
            "title": item.title,
            "description": item.description,
            "attempts": attempts,
            "last_try_ts_utc": utc_now_iso(),
            "result": "pending",
        }
    )
    st_items[item.video_url] = rec
    save_json_atomic(state_path, state)

    # Metadata overrides
    privacy = (os.getenv("YOUTUBE_PRIVACY_STATUS") or DEFAULT_PRIVACY_STATUS).strip().lower()
    if privacy not in ("public", "unlisted", "private"):
        privacy = DEFAULT_PRIVACY_STATUS

    category_id = (os.getenv("YOUTUBE_CATEGORY_ID") or DEFAULT_CATEGORY_ID).strip() or DEFAULT_CATEGORY_ID

    made_for_kids = (os.getenv("YOUTUBE_MADE_FOR_KIDS") or "false").strip().lower() in ("1", "true", "yes")

    tags_raw = (os.getenv("YOUTUBE_TAGS") or "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None

    dry_run = (os.getenv("YOUTUBE_POST_DRY_RUN") or os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes")
    if dry_run:
        rec["result"] = "dry_run"
        rec["dry_run_ts_utc"] = utc_now_iso()
        st_items[item.video_url] = rec
        state.setdefault("runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_url": item.video_url,
                "manifest": item.manifest_name,
                "result": "dry_run",
            }
        )
        state["last_post"] = {"ts_utc": utc_now_iso(), "video_url": item.video_url, "manifest": item.manifest_name}
        save_json_atomic(state_path, state)
        print(f"DRY RUN: would upload video: {item.video_url}")
        return 0

    # OAuth access token
    try:
        access_token = get_access_token()
    except Exception as e:
        rec["result"] = "failed"
        rec["error"] = str(e)[:1500]
        st_items[item.video_url] = rec
        state.setdefault("runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_url": item.video_url,
                "manifest": item.manifest_name,
                "result": "failed",
                "error": str(e)[:500],
            }
        )
        save_json_atomic(state_path, state)
        print(f"FAILED: {e}")
        return 2

    # Download and upload
    try:
        print(f"[youtube] downloading: {item.video_url}")
        file_path = download_video_to_temp(item.video_url, item.filename)
        print(f"[youtube] downloaded to: {file_path}")

        print(f"[youtube] uploading: title='{item.title}' privacy='{privacy}'")
        video_id = youtube_upload_video_http(
            access_token=access_token,
            file_path=file_path,
            title=item.title,
            description=item.description,
            privacy_status=privacy,
            category_id=category_id,
            made_for_kids=made_for_kids,
            tags=tags,
        )

        rec["result"] = "success"
        rec["youtube_video_id"] = video_id
        rec["published_ts_utc"] = utc_now_iso()
        rec.pop("error", None)
        st_items[item.video_url] = rec

        run_entry = {
            "ts_utc": utc_now_iso(),
            "video_url": item.video_url,
            "manifest": item.manifest_name,
            "result": "success",
            "youtube_video_id": video_id,
        }
        state.setdefault("runs", []).append(run_entry)
        state["last_post"] = run_entry
        save_json_atomic(state_path, state)

        print(f"OK: uploaded. video_id={video_id} manifest={item.manifest_name}")
        return 0
    except requests.HTTPError as e:
        err = str(e)
        rec["result"] = "failed"
        rec["error"] = (getattr(e.response, "text", "") or err)[:1500]
        st_items[item.video_url] = rec

        state.setdefault("runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_url": item.video_url,
                "manifest": item.manifest_name,
                "result": "failed",
                "error": rec["error"][:500],
            }
        )
        save_json_atomic(state_path, state)
        print(f"FAILED: {rec['error']}")
        return 1

    except Exception as e:
        rec["result"] = "failed"
        rec["error"] = str(e)[:1500]
        st_items[item.video_url] = rec

        state.setdefault("runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_url": item.video_url,
                "manifest": item.manifest_name,
                "result": "failed",
                "error": str(e)[:500],
            }
        )
        save_json_atomic(state_path, state)
        print(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# ============================================
# File: youtube-post/post_one_video.py
# Purpose: Post exactly 1 YouTube video per run (from local manifests) and persist independent state
# Notes:
# - Uses local manifests in youtube-post/manifests/*.json (current format: { pins: [...] })
# - Uploading to YouTube requires OAuth 2.0 (refresh token). API key alone won't work.
# - This script is autonomous: it reads only from youtube-post/* and writes only to youtube-post/state/*
# ============================================

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from youtube_auth import get_access_token


# ---------- Paths (repo-relative) ----------
REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "youtube-post" / "manifests"
STATE_PATH = REPO_ROOT / "youtube-post" / "state" / "youtube_post_state.json"

# Daily manifest rotation order (starting point rotates each day)
MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

# ---------- Limits ----------
TITLE_MAX = 100
DESC_MAX = 5000  # YouTube allows much more; keep it readable
MAX_ATTEMPTS_PER_VIDEO = 3
DOWNLOAD_TIMEOUT = 600  # seconds

# Defaults for video metadata
DEFAULT_PRIVACY_STATUS = "public"  # public | unlisted | private
DEFAULT_CATEGORY_ID = "26"  # 26 = Howto & Style
DEFAULT_MADE_FOR_KIDS = False


@dataclass(frozen=True)
class VideoItem:
    manifest_name: str
    manifest_action: str
    manifest_tag: str
    video_url: str
    filename: str
    title: str
    description: str
    destination_url: str
    alt: str
    status: str


# ----------------- JSON helpers -----------------
def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def utc_day_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ----------------- Manifest parsing -----------------
def _infer_filename(video_url: str) -> str:
    return (
        video_url.split("?")[0]
        .split("#")[0]
        .rstrip("/")
        .split("/")[-1]
        or "video.mp4"
    )


def read_manifest_file(path: Path) -> List[VideoItem]:
    data = load_json(path)

    action = str(data.get("action") or "").strip()
    tag = str(data.get("tag") or "").strip()

    pins = data.get("pins")
    if not isinstance(pins, list):
        raise ValueError(f"[{path.name}] expected top-level 'pins' as array")

    out: List[VideoItem] = []
    for raw in pins:
        if not isinstance(raw, dict):
            continue

        status = str(raw.get("status") or "").strip()
        video_url = str(raw.get("video_url") or "").strip()
        if not video_url:
            continue

        filename = str(raw.get("filename") or "").strip() or _infer_filename(video_url)
        title = str(raw.get("title") or "").strip()
        description = str(raw.get("description") or "").strip()
        alt = str(raw.get("alt") or "").strip()

        destination_url = ""
        dest = raw.get("destination")
        if isinstance(dest, dict):
            destination_url = str(dest.get("url") or "").strip()

        out.append(
            VideoItem(
                manifest_name=path.name,
                manifest_action=action,
                manifest_tag=tag,
                video_url=video_url,
                filename=filename,
                title=title,
                description=description,
                destination_url=destination_url,
                alt=alt,
                status=status,
            )
        )

    return out


def read_all_items() -> List[VideoItem]:
    paths: List[Path] = []
    for name in MANIFEST_FILES_ORDER:
        p = MANIFEST_DIR / name
        if p.exists():
            paths.append(p)

    # Include any extra manifests not in the order list
    extra = sorted([p for p in MANIFEST_DIR.glob("*.json") if p.name not in set(MANIFEST_FILES_ORDER)])
    paths.extend(extra)

    out: List[VideoItem] = []
    for p in paths:
        out.extend(read_manifest_file(p))
    return out


# ----------------- SEO formatting -----------------
def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _split_summary_rest(text: str) -> Tuple[str, str]:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return "", ""
    parts = re.split(r"(?<=[.!?])\s+", t, maxsplit=1)
    summary = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return summary, rest


def _hashtagify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    if not s:
        return ""
    return f"#{s}"


def build_description(item: VideoItem) -> str:
    # Use first sentence as the visible "hook" line; keep it short.
    summary, rest = _split_summary_rest(item.description)

    if not summary:
        summary = item.title

    summary = _truncate(summary, 180)

    # Optional extra line derived from alt (only if it adds information)
    extra = ""
    if item.alt:
        alt_clean = re.sub(r"\s+", " ", item.alt.strip())
        # Avoid duplicating if already contained
        if alt_clean and alt_clean.lower() not in (item.description or "").lower():
            extra = f"Tip: {alt_clean}."

    # Hashtags: keep 2–3 maximum (more can look spammy on Shorts)
    tags_raw = [
        item.manifest_tag,
        item.manifest_action,
        "sanding",
    ]
    hashtags: List[str] = []
    for t in tags_raw:
        h = _hashtagify(t)
        if h and h not in hashtags:
            hashtags.append(h)
        if len(hashtags) >= 3:
            break

    lines: List[str] = [summary]

    # Put the link on line 2 so it's visible without expanding the description.
    if item.destination_url:
        lines.append(item.destination_url)
        lines.append("")

    if rest:
        lines.append(_truncate(rest, 800))
        lines.append("")

    if extra:
        lines.append(_truncate(extra, 240))
        lines.append("")

    if hashtags:
        lines.append(" ".join(hashtags))

    # Trim trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()

    desc = "\n".join(lines).strip()
    return _truncate(desc, DESC_MAX)


def build_tags(item: VideoItem) -> List[str]:
    # YouTube "tags" are optional. Keep short and relevant.
    base = []
    for t in [item.manifest_tag, item.manifest_action, "sanding", "sandpaper"]:
        t = (t or "").strip()
        if not t:
            continue
        if t.lower() not in [x.lower() for x in base]:
            base.append(t)
    return base[:8]


# ----------------- State / rotation -----------------
def load_or_init_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        return load_json(STATE_PATH)
    return {
        "version": 1,
        "rotation": {"manifest_index": -1, "last_day": ""},
        "items": {},  # keyed by video_url
        "runs": [],
    }


def should_skip_item(state: Dict[str, Any], item: VideoItem) -> bool:
    items = state.get("items") or {}
    rec = items.get(item.video_url)
    if not isinstance(rec, dict):
        return False
    # success already posted
    if rec.get("result") == "success":
        return True
    # too many attempts
    attempts = int(rec.get("attempts") or 0)
    return attempts >= MAX_ATTEMPTS_PER_VIDEO


def pick_next_item(state: Dict[str, Any], all_items: List[VideoItem]) -> Optional[VideoItem]:
    # Rotate starting manifest index once per day
    rotation = state.get("rotation") or {}
    last_day = str(rotation.get("last_day") or "")
    idx = int(rotation.get("manifest_index") or -1)

    today = utc_day_str()
    if today != last_day:
        idx = (idx + 1) % max(1, len(MANIFEST_FILES_ORDER))
        rotation["manifest_index"] = idx
        rotation["last_day"] = today
        state["rotation"] = rotation

    # Build an ordered manifest list starting from idx
    ordered_manifests = []
    for i in range(len(MANIFEST_FILES_ORDER)):
        ordered_manifests.append(MANIFEST_FILES_ORDER[(idx + i) % len(MANIFEST_FILES_ORDER)])

    # Scan manifests in that order; take first READY item that isn't posted yet
    by_manifest: Dict[str, List[VideoItem]] = {}
    for it in all_items:
        by_manifest.setdefault(it.manifest_name, []).append(it)

    for m in ordered_manifests:
        for it in by_manifest.get(m, []):
            if it.status and it.status.lower() != "ready":
                continue
            if not it.video_url or not it.title:
                continue
            if should_skip_item(state, it):
                continue
            return it

    # Fallback: scan everything
    for it in all_items:
        if it.status and it.status.lower() != "ready":
            continue
        if not it.video_url or not it.title:
            continue
        if should_skip_item(state, it):
            continue
        return it

    return None


# ----------------- Download + Upload -----------------
def download_video(video_url: str, out_path: Path) -> None:
    with requests.get(video_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
        r.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def youtube_resumable_upload_init(
    access_token: str,
    *,
    file_size: int,
    mime_type: str,
    title: str,
    description: str,
    tags: List[str],
    privacy_status: str,
    category_id: str,
    made_for_kids: bool,
) -> str:
    url = "https://www.googleapis.com/upload/youtube/v3/videos"
    params = {"uploadType": "resumable", "part": "snippet,status"}

    payload: Dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    if tags:
        payload["snippet"]["tags"] = tags

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mime_type,
        "X-Upload-Content-Length": str(file_size),
    }

    resp = requests.post(url, params=params, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    upload_url = resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube resumable init did not return Location header")
    return upload_url


def youtube_resumable_upload_put(access_token: str, upload_url: str, file_path: Path, *, mime_type: str) -> str:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": mime_type,
    }
    with file_path.open("rb") as f:
        resp = requests.put(upload_url, headers=headers, data=f, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    vid = str(data.get("id") or "").strip()
    if not vid:
        raise RuntimeError("Upload succeeded but no video id returned")
    return vid


def record_attempt(state: Dict[str, Any], item: VideoItem, *, result: str, video_id: str = "", error: str = "") -> None:
    items = state.setdefault("items", {})
    rec = items.get(item.video_url) if isinstance(items, dict) else None
    if not isinstance(rec, dict):
        rec = {"attempts": 0}
        items[item.video_url] = rec

    rec["video_url"] = item.video_url
    rec["filename"] = item.filename
    rec["manifest"] = item.manifest_name
    rec["title"] = item.title
    rec["destination_url"] = item.destination_url
    rec["result"] = result
    rec["attempts"] = int(rec.get("attempts") or 0) + 1
    rec["video_id"] = video_id
    if error:
        rec["error"] = error

    state.setdefault("runs", []).append(
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "video_url": item.video_url,
            "result": result,
            "video_id": video_id,
        }
    )


def main() -> None:
    all_items = read_all_items()
    if not all_items:
        raise SystemExit(f"No manifest items found in {MANIFEST_DIR}")

    state = load_or_init_state()
    item = pick_next_item(state, all_items)
    if not item:
        print("No eligible video to post (all posted or exhausted attempts).")
        return

    title = _truncate(item.title.strip(), TITLE_MAX)
    description = build_description(item)
    tags = build_tags(item)

    access_token = get_access_token()

    with tempfile.TemporaryDirectory() as td:
        local_path = Path(td) / item.filename
        print(f"Downloading: {item.video_url}")
        download_video(item.video_url, local_path)

        file_size = local_path.stat().st_size
        mime_type = "video/mp4"

        print("Init upload...")
        upload_url = youtube_resumable_upload_init(
            access_token,
            file_size=file_size,
            mime_type=mime_type,
            title=title,
            description=description,
            tags=tags,
            privacy_status=DEFAULT_PRIVACY_STATUS,
            category_id=DEFAULT_CATEGORY_ID,
            made_for_kids=DEFAULT_MADE_FOR_KIDS,
        )

        print("Uploading bytes...")
        try:
            video_id = youtube_resumable_upload_put(access_token, upload_url, local_path, mime_type=mime_type)
            record_attempt(state, item, result="success", video_id=video_id)
            save_json_atomic(STATE_PATH, state)
            print(f"SUCCESS video_id={video_id}")
        except Exception as e:
            record_attempt(state, item, result="failed", error=str(e))
            save_json_atomic(STATE_PATH, state)
            raise


if __name__ == "__main__":
    main()

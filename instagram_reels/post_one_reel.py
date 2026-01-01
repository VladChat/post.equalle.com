# ============================================
# File: instagram_reels/post_one_reel.py
# Purpose: Post exactly 1 Instagram Reel per run (from local manifests) and persist independent state.
#
# Key robustness improvements:
# - Preflight checks for video_url (200, Content-Type, Content-Length, redirects).
# - Container retry logic: create new container if status_code=ERROR (including upload failures like 2207076).
# - URL strategy: try original URL first; if upload fails, try "direct" resolved URL (after redirects).
# - Better logging + state persistence (preflight, upload_url_used, last container status).
#
# Notes (Meta docs):
# - Publishing requires media hosted on a publicly accessible server; Meta cURLs the media URL.
# - Container status must be read with fields=status_code,status (no error_message for ShadowIGMediaBuilder).
# ============================================

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


# ----- Config (safe defaults; override via env) -----

DEFAULT_IG_USER_ID = "17841422239487755"
DEFAULT_GRAPH_API_VERSION = "v21.0"

MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

CAPTION_MAX = 2200
MAX_ATTEMPTS_PER_VIDEO = 3

# Container status polling
STATUS_POLL_TIMEOUT_SEC = int(os.getenv("IG_STATUS_POLL_TIMEOUT_SEC", "900"))
STATUS_POLL_INTERVAL_SEC = int(os.getenv("IG_STATUS_POLL_INTERVAL_SEC", "10"))

# Retry strategy
MAX_CONTAINER_RETRIES_PER_URL = int(os.getenv("IG_MAX_CONTAINER_RETRIES_PER_URL", "3"))
SLEEP_BETWEEN_CONTAINER_RETRIES_SEC = int(os.getenv("IG_SLEEP_BETWEEN_CONTAINER_RETRIES_SEC", "20"))

# URL preflight strategy
PREFLIGHT_RANGE_BYTES = int(os.getenv("IG_PREFLIGHT_RANGE_BYTES", "1"))  # 1 byte is enough to validate content-type
ALLOW_DIRECT_URL_FALLBACK = (os.getenv("IG_ALLOW_DIRECT_URL_FALLBACK", "true").strip().lower() in ("1", "true", "yes"))

# Networking
HTTP_TIMEOUT_SEC = int(os.getenv("IG_HTTP_TIMEOUT_SEC", "60"))


@dataclass(frozen=True)
class ReelItem:
    manifest_name: str
    video_url: str
    filename: str
    title: str
    description: str


def repo_root_from_this_file() -> Path:
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


# ----------------------------
# URL PRE-FLIGHT / RESOLUTION
# ----------------------------

def _is_https_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme.lower() == "https"
    except Exception:
        return False


def preflight_video_url(url: str) -> Dict[str, Any]:
    """
    Verify the URL is fetchable as a video by a generic HTTP client:
    - must be https
    - should return 200 (after redirects)
    - content-type should start with video/
    - content-length should be present (best effort)
    We do a tiny range GET to avoid downloading the whole file.
    """
    out: Dict[str, Any] = {
        "url": url,
        "ok": False,
        "final_url": None,
        "status_code": None,
        "content_type": None,
        "content_length": None,
        "accept_ranges": None,
        "redirected": None,
        "error": None,
    }

    if not _is_https_url(url):
        out["error"] = "video_url must be HTTPS"
        return out

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
    }
    # Try a tiny range request: bytes=0-0 (1 byte) or configured size
    # Many CDNs will answer 206; some answer 200.
    range_end = max(0, PREFLIGHT_RANGE_BYTES - 1)
    headers["Range"] = f"bytes=0-{range_end}"

    try:
        resp = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=HTTP_TIMEOUT_SEC)
        out["status_code"] = resp.status_code
        out["final_url"] = resp.url
        out["redirected"] = (resp.url != url)

        ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        cl = resp.headers.get("Content-Length")
        ar = resp.headers.get("Accept-Ranges")

        out["content_type"] = ct or None
        out["content_length"] = cl
        out["accept_ranges"] = ar

        # Important: close stream immediately (do not download)
        try:
            resp.close()
        except Exception:
            pass

        # Evaluate "ok"
        # Accept 200 or 206 for range GET
        if resp.status_code not in (200, 206):
            out["error"] = f"HTTP {resp.status_code}"
            return out

        # Must not be HTML (common failure with share links)
        if ct.startswith("text/") or ct in ("text/html", "application/xhtml+xml"):
            out["error"] = f"Not a direct video file (Content-Type={ct})"
            return out

        if not ct.startswith("video/") and ct not in ("application/octet-stream",):
            # Some servers return octet-stream for mp4; allow it.
            out["error"] = f"Unexpected Content-Type={ct}"
            return out

        out["ok"] = True
        return out

    except Exception as e:
        out["error"] = str(e)
        return out


def build_url_candidates(original_url: str) -> List[Tuple[str, str]]:
    """
    Returns list of (label, url) candidates.
    Strategy:
      1) original url (best if it issues fresh redirect signatures)
      2) direct resolved url (fallback; may help if Meta rejects redirects)
    """
    candidates: List[Tuple[str, str]] = [("original", original_url)]

    if not ALLOW_DIRECT_URL_FALLBACK:
        return candidates

    pf = preflight_video_url(original_url)
    final_url = (pf.get("final_url") or "").strip()
    if final_url and final_url != original_url:
        candidates.append(("direct", final_url))

    return candidates


# ----------------------------
# IG PUBLISH FLOW
# ----------------------------

def create_reel_container(
    ig_user_id: str,
    token: str,
    version: str,
    video_url: str,
    caption: str,
    *,
    share_to_feed: bool,
) -> str:
    """
    POST /{ig-user-id}/media
      media_type=REELS
      video_url=<url>
      caption=<caption>
      share_to_feed=true|false
    """
    url = f"{graph_base(version)}/{ig_user_id}/media"

    data = {
        "access_token": token,
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
    }

    resp = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SEC)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create_container failed: HTTP {resp.status_code}: {resp.text[:800]}")
    j = resp.json()
    cid = (j.get("id") or "").strip()
    if not cid:
        raise RuntimeError(f"create_container missing id: {j}")
    return cid


def get_container_status(container_id: str, token: str, version: str) -> Dict[str, Any]:
    """
    GET /{ig-container-id}?fields=status_code,status
    ShadowIGMediaBuilder does NOT support error_message field.
    """
    url = f"{graph_base(version)}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": token,
    }
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SEC)
    if resp.status_code != 200:
        raise RuntimeError(f"container_status failed: HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def _extract_error_code(text: str) -> Optional[str]:
    # Finds 7-digit subcodes like 2207076 in error text.
    if not text:
        return None
    m = re.search(r"\b(22\d{5})\b", text)
    return m.group(1) if m else None


def wait_container_finished(container_id: str, token: str, version: str) -> Dict[str, Any]:
    deadline = time.time() + STATUS_POLL_TIMEOUT_SEC
    last: Dict[str, Any] = {}

    while time.time() < deadline:
        last = get_container_status(container_id, token, version)
        status_code = str(last.get("status_code") or "").upper().strip()

        if status_code == "FINISHED":
            return last

        if status_code == "ERROR":
            detail = str(last.get("status") or last)
            code = _extract_error_code(detail)
            raise RuntimeError(f"container ERROR: {detail}" + (f" (subcode={code})" if code else ""))

        time.sleep(STATUS_POLL_INTERVAL_SEC)

    return last


def publish_container(ig_user_id: str, token: str, version: str, creation_id: str) -> str:
    url = f"{graph_base(version)}/{ig_user_id}/media_publish"
    resp = requests.post(url, data={"access_token": token, "creation_id": creation_id}, timeout=HTTP_TIMEOUT_SEC)
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
    upload_url_used: Optional[str] = None,
    upload_url_label: Optional[str] = None,
    preflight: Optional[Dict[str, Any]] = None,
    container_id: Optional[str] = None,
    media_id: Optional[str] = None,
    container_status_last: Optional[Dict[str, Any]] = None,
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

    if upload_url_used:
        rec["upload_url_used"] = upload_url_used
    if upload_url_label:
        rec["upload_url_label"] = upload_url_label
    if preflight is not None:
        rec["preflight"] = preflight
    if container_id:
        rec["container_id"] = str(container_id)
    if media_id:
        rec["media_id"] = str(media_id)
    if container_status_last is not None:
        rec["container_status_last"] = container_status_last
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
            "upload_url_used": upload_url_used,
            "upload_url_label": upload_url_label,
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

    # Preflight original URL (store in state for debugging)
    pf_original = preflight_video_url(item.video_url)
    print("[preflight] original:", json.dumps(pf_original, ensure_ascii=False))

    if dry_run:
        update

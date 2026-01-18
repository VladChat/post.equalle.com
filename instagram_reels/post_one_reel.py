# ============================================
# File: instagram_reels/post_one_reel.py
# Purpose: Post exactly 1 Instagram Reel per run (from local manifests) and persist independent state.
#
# Reliability strategy:
# - Prefer BINARY upload: download video on runner -> resumable upload bytes to Meta (rupload).
# - URL-based publishing remains as optional fallback.
#
# Key debug goals:
# - Always print enough logs to understand selection, API calls, and state writes.
#
# Resumable response note:
# - Meta may return 'uri' instead of 'upload_url'. We support BOTH.
#   Example: {'id': '...', 'uri': 'https://rupload.facebook.com/ig-api-upload/v24.0/...'}
#
# Cover selection:
# - Random thumb_offset (0..7000 ms) to pick a cover frame from 0 to 7 seconds.
# ============================================

from __future__ import annotations

import json
import os
import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


# -------------------------
# Defaults / ENV overrides
# -------------------------

DEFAULT_IG_USER_ID = os.getenv("IG_USER_ID_DEFAULT", "17841422239487755").strip()
DEFAULT_GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION_DEFAULT", "v21.0").strip()

MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

CAPTION_MAX = 2200
MAX_ATTEMPTS_PER_VIDEO = int(os.getenv("IG_MAX_ATTEMPTS_PER_VIDEO", "3"))

# Polling
STATUS_POLL_TIMEOUT_SEC = int(os.getenv("IG_STATUS_POLL_TIMEOUT_SEC", "900"))
STATUS_POLL_INTERVAL_SEC = int(os.getenv("IG_STATUS_POLL_INTERVAL_SEC", "10"))

# Upload retry (for transient Meta rupload flaps)
# Default: 3 attempts total, delays 30s -> 90s -> 180s (override via IG_RUPLOAD_RETRY_DELAYS_SEC="30,90,180")
MAX_RUPLOAD_ATTEMPTS = int(os.getenv("IG_RUPLOAD_MAX_ATTEMPTS", "3"))
_RUPLOAD_DELAYS_RAW = (os.getenv("IG_RUPLOAD_RETRY_DELAYS_SEC", "30,90,180") or "").strip()


def _parse_retry_delays(raw: str) -> List[int]:
    out: List[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
            if v > 0:
                out.append(v)
        except Exception:
            continue
    return out or [30, 90, 180]


RUPLOAD_RETRY_DELAYS_SEC = _parse_retry_delays(_RUPLOAD_DELAYS_RAW)

# Upload modes:
# - "binary" (preferred): download video and upload bytes to Meta resumable endpoint
# - "url": Meta fetches video_url itself
UPLOAD_MODE = (os.getenv("IG_REELS_UPLOAD_MODE", "binary").strip().lower() or "binary")
if UPLOAD_MODE not in ("binary", "url"):
    UPLOAD_MODE = "binary"

# Download / network
HTTP_TIMEOUT_SEC = int(os.getenv("IG_HTTP_TIMEOUT_SEC", "60"))
DOWNLOAD_TIMEOUT_SEC = int(os.getenv("IG_DOWNLOAD_TIMEOUT_SEC", "300"))
DOWNLOAD_CHUNK_SIZE = int(os.getenv("IG_DOWNLOAD_CHUNK_SIZE", str(1024 * 1024)))  # 1 MiB


@dataclass(frozen=True)
class ReelItem:
    manifest_name: str
    video_url: str
    filename: str
    title: str
    description: str


# -------------------------
# Helpers
# -------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


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


def graph_base(version: str) -> str:
    version = (version or DEFAULT_GRAPH_API_VERSION).strip()
    if not version.startswith("v"):
        version = "v" + version
    return f"https://graph.facebook.com/{version}"


def _is_https(url: str) -> bool:
    try:
        return urlparse(url).scheme.lower() == "https"
    except Exception:
        return False


def debug_list_dir(path: Path, title: str) -> None:
    log(f"--- {title}: {path} ---")
    if not path.exists():
        log("  (missing)")
        return
    if path.is_file():
        log("  (file)")
        return
    for p in sorted(path.glob("*")):
        log(f"  - {p.name}")


def _is_retriable_rupload_error(err_text: str) -> bool:
    """
    Best-effort classification for Meta rupload transient flaps.
    We retry on:
      - ProcessingFailedError (seen in the wild)
      - retriable=true in debug_info
      - HTTP 429 / timeouts / 5xx (if present in message)
    """
    t = (err_text or "").lower()
    if "processingfailederror" in t:
        return True
    if '"retriable":true' in t or "retriable\":true" in t:
        return True
    if "http 429" in t:
        return True
    if "http 5" in t:  # crude but useful for messages like "HTTP 500/502/503"
        return True
    if "timeout" in t or "timed out" in t:
        return True
    if "connection reset" in t or "connection aborted" in t:
        return True
    return False


# -------------------------
# Manifest + state selection
# -------------------------

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


def diagnose_why_no_item(manifest_dir: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "manifest_dir_exists": manifest_dir.exists(),
        "manifests_found": [],
        "per_manifest": [],
        "state_items_count": len((state.get("items") or {})),
    }

    if not manifest_dir.exists():
        return out

    for name in MANIFEST_FILES_ORDER:
        p = manifest_dir / name
        if not p.exists():
            continue
        out["manifests_found"].append(name)
        try:
            data = load_json(p)
            items = data.get("items")
            if not isinstance(items, list):
                out["per_manifest"].append({"name": name, "error": "items is not a list"})
                continue

            total = len(items)
            pending = 0
            success = 0
            maxed = 0
            bad = 0
            for raw in items:
                if not isinstance(raw, dict):
                    bad += 1
                    continue
                try:
                    it = ensure_required_fields(raw, name)
                except Exception:
                    bad += 1
                    continue

                rec = (state.get("items") or {}).get(it.video_url) or {}
                if rec.get("result") == "success":
                    success += 1
                    continue
                attempts = int(rec.get("attempts", 0) or 0)
                if attempts >= MAX_ATTEMPTS_PER_VIDEO:
                    maxed += 1
                    continue
                pending += 1

            out["per_manifest"].append(
                {
                    "name": name,
                    "total": total,
                    "pending": pending,
                    "success": success,
                    "maxed": maxed,
                    "bad": bad,
                }
            )
        except Exception as e:
            out["per_manifest"].append({"name": name, "error": str(e)})

    return out


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


# -------------------------
# Download (for binary mode)
# -------------------------

def download_to_tempfile(video_url: str, filename_hint: str) -> Tuple[Path, int]:
    if not _is_https(video_url):
        raise RuntimeError("video_url must be HTTPS for binary download")

    safe_name = (filename_hint or "video.mp4").strip() or "video.mp4"

    headers = {"User-Agent": "ig-reels-binary-uploader/1.0"}
    start = time.time()

    with requests.get(video_url, stream=True, headers=headers, timeout=HTTP_TIMEOUT_SEC, allow_redirects=True) as r:
        if r.status_code != 200:
            raise RuntimeError(f"download failed: HTTP {r.status_code}: {r.text[:300]}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="ig_reels_"))
        out_path = tmp_dir / safe_name

        size = 0
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                size += len(chunk)
                if time.time() - start > DOWNLOAD_TIMEOUT_SEC:
                    raise RuntimeError("download timeout (took too long)")

        if size <= 0:
            raise RuntimeError("download produced empty file")

        return out_path, size


# -------------------------
# Instagram Graph API calls
# -------------------------

def _random_thumb_offset_ms() -> int:
    # Random cover frame from 0..7 seconds (milliseconds)
    return random.randint(0, 7000)


def create_reel_container_url_mode(
    ig_user_id: str,
    token: str,
    version: str,
    video_url: str,
    caption: str,
    *,
    share_to_feed: bool,
) -> str:
    """
    URL mode: Meta fetches video_url itself.
    POST /{ig-user-id}/media
      media_type=REELS
      video_url=...
      caption=...
      share_to_feed=true|false
      thumb_offset=<ms>  (random 0..7000)
    """
    url = f"{graph_base(version)}/{ig_user_id}/media"
    data = {
        "access_token": token,
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
        "thumb_offset": str(_random_thumb_offset_ms()),
    }
    resp = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SEC)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create_container(url) failed: HTTP {resp.status_code}: {resp.text[:800]}")
    j = resp.json()
    cid = (j.get("id") or "").strip()
    if not cid:
        raise RuntimeError(f"create_container(url) missing id: {j}")
    return cid


def create_reel_container_resumable(
    ig_user_id: str,
    token: str,
    version: str,
    caption: str,
    *,
    share_to_feed: bool,
) -> Dict[str, Any]:
    """
    Resumable mode (binary):
    POST /{ig-user-id}/media
      media_type=REELS
      caption=...
      share_to_feed=true|false
      upload_type=resumable
      thumb_offset=<ms>  (random 0..7000)

    Meta may return:
      - upload_url
      - OR uri (rupload endpoint)
    """
    url = f"{graph_base(version)}/{ig_user_id}/media"
    data = {
        "access_token": token,
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
        "upload_type": "resumable",
        "thumb_offset": str(_random_thumb_offset_ms()),
    }
    resp = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SEC)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create_container(resumable) failed: HTTP {resp.status_code}: {resp.text[:800]}")
    j = resp.json()

    cid = (j.get("id") or "").strip()
    rupload_url = (j.get("upload_url") or j.get("uri") or "").strip()

    if not cid:
        raise RuntimeError(f"create_container(resumable) missing id: {j}")
    if not rupload_url:
        raise RuntimeError(f"create_container(resumable) missing upload endpoint (upload_url/uri): {j}")

    return {"id": cid, "rupload_url": rupload_url, "raw": j}


def resumable_upload_bytes(rupload_url: str, token: str, file_path: Path, file_size: int) -> Dict[str, Any]:
    data = file_path.read_bytes()
    if len(data) != int(file_size):
        raise RuntimeError(f"file size mismatch: expected {file_size}, got {len(data)}")

    headers = {
        "Authorization": f"OAuth {token}",
        "Content-Type": "application/octet-stream",
        "offset": "0",  # <-- restored (as requested)
        "file_size": str(int(file_size)),
        "Content-Length": str(int(file_size)),
    }

    resp = requests.post(rupload_url, headers=headers, data=data, timeout=max(HTTP_TIMEOUT_SEC, 300))
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"resumable_upload failed: HTTP {resp.status_code}: {resp.text[:800]}")

    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text[:800]}


def get_container_status(container_id: str, token: str, version: str) -> Dict[str, Any]:
    url = f"{graph_base(version)}/{container_id}"
    params = {"fields": "status_code,status", "access_token": token}
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SEC)
    if resp.status_code != 200:
        raise RuntimeError(f"container_status failed: HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def wait_container_finished(container_id: str, token: str, version: str) -> Dict[str, Any]:
    deadline = time.time() + STATUS_POLL_TIMEOUT_SEC
    last: Dict[str, Any] = {}

    while time.time() < deadline:
        last = get_container_status(container_id, token, version)
        sc = str(last.get("status_code") or "").upper().strip()
        st = last.get("status")
        log(f"[container] id={container_id} status_code={sc} status={st}")

        if sc == "FINISHED":
            return last
        if sc == "ERROR":
            raise RuntimeError(f"container ERROR: {st}")

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


# -------------------------
# State updates
# -------------------------

def update_state(
    state: Dict[str, Any],
    item: ReelItem,
    result: str,
    *,
    mode: str,
    container_id: Optional[str] = None,
    media_id: Optional[str] = None,
    upload_url_used: Optional[str] = None,
    upload_resp: Optional[Dict[str, Any]] = None,
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
            "result": result,
            "attempts": attempts,
            "last_ts_utc": utc_now_iso(),
            "mode": mode,
        }
    )
    if container_id:
        rec["container_id"] = str(container_id)
    if media_id:
        rec["media_id"] = str(media_id)
    if upload_url_used:
        rec["upload_url_used"] = upload_url_used
    if upload_resp is not None:
        rec["upload_resp"] = upload_resp
    if container_status_last is not None:
        rec["container_status_last"] = container_status_last
    if error:
        rec["error"] = error

    st_items[item.video_url] = rec

    state.setdefault("runs", []).append(
        {
            "ts_utc": utc_now_iso(),
            "result": result,
            "mode": mode,
            "manifest": item.manifest_name,
            "video_url": item.video_url,
            "filename": item.filename,
            "container_id": container_id,
            "media_id": media_id,
            "error": error,
        }
    )


# -------------------------
# Main
# -------------------------

def main() -> int:
    log("=== IG REELS: post_one_reel.py START ===")

    token = (
        os.getenv("IG_ACCESS_TOKEN")
        or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or os.getenv("FB_PAGE_TOKEN")
        or ""
    ).strip()

    if not token:
        log("ERROR: Missing IG_ACCESS_TOKEN (or INSTAGRAM_ACCESS_TOKEN / META_ACCESS_TOKEN / FB_PAGE_TOKEN).")
        return 2

    ig_user_id = (os.getenv("IG_USER_ID") or os.getenv("IG_BUSINESS_ID") or DEFAULT_IG_USER_ID).strip()
    version = (os.getenv("GRAPH_API_VERSION") or DEFAULT_GRAPH_API_VERSION).strip()
    share_to_feed = (os.getenv("IG_REELS_SHARE_TO_FEED") or "true").strip().lower() in ("1", "true", "yes")
    dry_run = (os.getenv("IG_REELS_DRY_RUN") or os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes")

    repo_root = repo_root_from_this_file()
    manifest_dir = repo_root / "instagram_reels" / "manifests"
    state_path = repo_root / "instagram_reels" / "state" / "instagram_reels_post_state.json"

    log(f"Repo root: {repo_root}")
    log(f"Manifest dir: {manifest_dir}")
    log(f"State path: {state_path}")
    log(f"Config: ig_user_id={ig_user_id} version={version} share_to_feed={share_to_feed} upload_mode={UPLOAD_MODE} dry_run={dry_run}")

    debug_list_dir(repo_root / "instagram_reels", "instagram_reels dir")
    debug_list_dir(manifest_dir, "manifests")
    debug_list_dir(state_path.parent, "state dir")

    if state_path.exists():
        state = load_json(state_path)
        log(f"Loaded state: items={len(state.get('items') or {})} runs={len(state.get('runs') or [])}")
    else:
        state = {"version": 1, "rotation": {}, "items": {}, "runs": []}
        log("State file missing -> created new state object")

    # Select item
    item = None
    try:
        item = pick_next_item(manifest_dir, state)
    except Exception as e:
        log(f"ERROR while selecting item: {e}")
        diag = diagnose_why_no_item(manifest_dir, state)
        log("Selection diagnostics:\n" + json.dumps(diag, ensure_ascii=False, indent=2))
        save_json_atomic(state_path, state)
        return 1

    if not item:
        log("No pending IG reels found (all posted or max attempts reached).")
        diag = diagnose_why_no_item(manifest_dir, state)
        log("No-item diagnostics:\n" + json.dumps(diag, ensure_ascii=False, indent=2))
        save_json_atomic(state_path, state)
        return 0

    caption = build_caption(item.title, item.description)

    log("Selected item:")
    log(f"  manifest : {item.manifest_name}")
    log(f"  filename : {item.filename}")
    log(f"  video_url: {item.video_url}")
    log(f"  caption  : {caption}")

    if dry_run:
        update_state(state, item, "failed", mode="dry_run", error="DRY RUN (no API calls)")
        save_json_atomic(state_path, state)
        log("DRY RUN complete. State updated for visibility.")
        return 0

    tmp_file: Optional[Path] = None
    container_id: Optional[str] = None
    media_id: Optional[str] = None
    upload_resp: Optional[Dict[str, Any]] = None
    last_container_status: Optional[Dict[str, Any]] = None

    try:
        if UPLOAD_MODE == "binary":
            log("Mode=binary: downloading video -> resumable upload to Meta")

            tmp_file, size = download_to_tempfile(item.video_url, item.filename)
            log(f"Downloaded to: {tmp_file} size={size} bytes")

            created = create_reel_container_resumable(
                ig_user_id=ig_user_id,
                token=token,
                version=version,
                caption=caption,
                share_to_feed=share_to_feed,
            )
            container_id = created["id"]
            rupload_url = created["rupload_url"]
            log(f"Created resumable container: id={container_id}")
            log(f"Rupload URL: {rupload_url}")
            log("Create response raw: " + json.dumps(created.get("raw") or {}, ensure_ascii=False))

            # Retry ONLY the rupload call for transient Meta flaps
            last_upload_err: Optional[str] = None
            attempts_total = max(1, int(MAX_RUPLOAD_ATTEMPTS))
            for attempt in range(1, attempts_total + 1):
                try:
                    upload_resp = resumable_upload_bytes(rupload_url, token, tmp_file, size)
                    log("Upload response: " + json.dumps(upload_resp, ensure_ascii=False))
                    last_upload_err = None
                    break
                except Exception as e:
                    last_upload_err = str(e)[:1500]
                    if attempt < attempts_total and _is_retriable_rupload_error(last_upload_err):
                        delay = RUPLOAD_RETRY_DELAYS_SEC[min(attempt - 1, len(RUPLOAD_RETRY_DELAYS_SEC) - 1)]
                        log(f"[rupload] attempt {attempt}/{attempts_total} failed (retriable). Sleeping {delay}s then retry...")
                        time.sleep(delay)
                        continue
                    raise

            if last_upload_err:
                raise RuntimeError(last_upload_err)

            last_container_status = wait_container_finished(container_id, token, version)

            media_id = publish_container(ig_user_id, token, version, container_id)
            log(f"PUBLISHED OK: media_id={media_id}")

            update_state(
                state,
                item,
                "success",
                mode="binary",
                container_id=container_id,
                media_id=media_id,
                upload_url_used=rupload_url,
                upload_resp=upload_resp,
                container_status_last=last_container_status,
                error=None,
            )
            save_json_atomic(state_path, state)
            log("State saved (success).")
            return 0

        # URL mode fallback
        log("Mode=url: Meta will fetch video_url itself (less reliable).")
        container_id = create_reel_container_url_mode(
            ig_user_id=ig_user_id,
            token=token,
            version=version,
            video_url=item.video_url,
            caption=caption,
            share_to_feed=share_to_feed,
        )
        log(f"Created URL container: id={container_id}")

        last_container_status = wait_container_finished(container_id, token, version)

        media_id = publish_container(ig_user_id, token, version, container_id)
        log(f"PUBLISHED OK: media_id={media_id}")

        update_state(
            state,
            item,
            "success",
            mode="url",
            container_id=container_id,
            media_id=media_id,
            upload_url_used=item.video_url,
            upload_resp=None,
            container_status_last=last_container_status,
            error=None,
        )
        save_json_atomic(state_path, state)
        log("State saved (success).")
        return 0

    except Exception as e:
        err = str(e)[:1500]
        log(f"FAILED: {err}")

        update_state(
            state,
            item,
            "failed",
            mode=UPLOAD_MODE,
            container_id=container_id,
            media_id=media_id,
            upload_url_used=item.video_url,
            upload_resp=upload_resp,
            container_status_last=last_container_status,
            error=err,
        )
        save_json_atomic(state_path, state)
        log("State saved (failed).")
        return 1

    finally:
        try:
            if tmp_file and tmp_file.exists():
                tmp_dir = tmp_file.parent
                try:
                    tmp_file.unlink()
                except Exception:
                    pass
                try:
                    tmp_dir.rmdir()
                except Exception:
                    pass
                log("Cleaned up temp file.")
        except Exception:
            pass

        log("=== IG REELS: post_one_reel.py END ===")


if __name__ == "__main__":
    raise SystemExit(main())

# /pinterest/post_one_video_pin.py
# Purpose: Post exactly 1 video Pin using manifests (round-robin), then persist success/failure to pinterest/state/pinterest_post_state.json.

from __future__ import annotations

import json
import os
import time
import tempfile
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


API_BASE = "https://api.pinterest.com/v5"

# Stable order (round-robin cursor rotates through these)
MANIFEST_FILES_ORDER = ["drywall.json", "wood.json", "wet.json", "metal.json", "plastic.json"]

TITLE_MAX = 80
DESC_MAX = 300
ALT_MAX = 120

MAX_ATTEMPTS_PER_VIDEO = 3
MEDIA_POLL_TIMEOUT_SEC = 180
MEDIA_POLL_INTERVAL_SEC = 3


@dataclass
class PinItem:
    manifest_name: str
    filename: str
    video_url: str
    destination_url: str
    board_id: str
    title: str
    description: str
    alt: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root_from_this_file() -> Path:
    """
    Finds repo root robustly no matter where this file lives.
    We look upwards for markers: requirements.txt and .github directory.
    """
    cur = Path(__file__).resolve()
    for parent in [cur.parent] + list(cur.parents):
        if (parent / "requirements.txt").exists() and (parent / ".github").exists():
            return parent
    # fallback (shouldn't happen)
    return cur.parents[1]


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip()


def ensure_required_fields(pin: Dict[str, Any], manifest_name: str) -> PinItem:
    video_url = (pin.get("video_url") or "").strip()
    destination_url = (pin.get("destination", {}) or {}).get("url", "")
    destination_url = (destination_url or "").strip()

    board = pin.get("board", {}) or {}
    board_id = (board.get("id") or "").strip()

    title = clip(pin.get("title", ""), TITLE_MAX)
    description = clip(pin.get("description", ""), DESC_MAX)
    alt = clip(pin.get("alt", ""), ALT_MAX)

    filename = (pin.get("filename") or "").strip()  # optional; used only for logs if present

    missing = []
    if not video_url:
        missing.append("video_url")
    if not destination_url:
        missing.append("destination.url")
    if not board_id:
        missing.append("board.id")
    if not title:
        missing.append("title")
    if not description:
        missing.append("description")
    if not alt:
        missing.append("alt")

    if missing:
        raise ValueError(f"[{manifest_name}] pin is missing required fields: {', '.join(missing)}")

    if not (destination_url.startswith("http://") or destination_url.startswith("https://")):
        raise ValueError(f"[{manifest_name}] destination.url is not http(s): {destination_url}")

    if not (video_url.startswith("http://") or video_url.startswith("https://")):
        raise ValueError(f"[{manifest_name}] video_url is not http(s): {video_url}")

    return PinItem(
        manifest_name=manifest_name,
        filename=filename,
        video_url=video_url,
        destination_url=destination_url,
        board_id=board_id,
        title=title,
        description=description,
        alt=alt,
    )


def get_manifest_paths(manifest_dir: Path) -> List[Path]:
    ordered: List[Path] = []
    for name in MANIFEST_FILES_ORDER:
        p = manifest_dir / name
        if p.exists():
            ordered.append(p)

    if ordered:
        return ordered

    return sorted(manifest_dir.glob("*.json"))


def load_manifest_items(manifest_path: Path) -> List[PinItem]:
    manifest_name = manifest_path.name
    data = load_json(manifest_path)

    pins = data.get("pins")
    if not isinstance(pins, list):
        raise ValueError(f"[{manifest_name}] expected top-level 'pins' as array")

    items: List[PinItem] = []
    for raw in pins:
        if not isinstance(raw, dict):
            continue
        items.append(ensure_required_fields(raw, manifest_name))
    return items


def load_state(state_path: Path) -> Dict[str, Any]:
    base = {"version": 1, "cursor": {"manifest_index": 0}, "items": {}, "runs": []}

    if not state_path.exists():
        return base

    try:
        data = load_json(state_path)
        if not isinstance(data, dict):
            return base

        data.setdefault("version", 1)
        data.setdefault("items", {})
        data.setdefault("runs", [])
        data.setdefault("cursor", {"manifest_index": 0})

        if not isinstance(data["items"], dict):
            data["items"] = {}
        if not isinstance(data["runs"], list):
            data["runs"] = []
        if not isinstance(data["cursor"], dict):
            data["cursor"] = {"manifest_index": 0}
        if "manifest_index" not in data["cursor"] or not isinstance(data["cursor"]["manifest_index"], int):
            data["cursor"]["manifest_index"] = 0

        return data

    except Exception:
        return base


def is_item_eligible(it: PinItem, state: Dict[str, Any]) -> bool:
    st_items = state.get("items", {}) or {}
    rec = st_items.get(it.video_url) or {}
    if rec.get("result") == "success":
        return False
    attempts = int(rec.get("attempts", 0) or 0)
    if attempts >= MAX_ATTEMPTS_PER_VIDEO:
        return False
    return True


def pick_next_item_round_robin(manifest_paths: List[Path], state: Dict[str, Any]) -> Tuple[Optional[PinItem], Optional[int]]:
    if not manifest_paths:
        return None, None

    n = len(manifest_paths)
    start = int((state.get("cursor", {}) or {}).get("manifest_index", 0) or 0) % n

    for offset in range(n):
        idx = (start + offset) % n
        items = load_manifest_items(manifest_paths[idx])
        for it in items:
            if is_item_eligible(it, state):
                return it, idx

    return None, None


def advance_cursor(state: Dict[str, Any], manifest_paths: List[Path], used_manifest_index: Optional[int]) -> None:
    if not manifest_paths:
        return

    n = len(manifest_paths)
    cur = int((state.get("cursor", {}) or {}).get("manifest_index", 0) or 0) % n

    if used_manifest_index is None:
        nxt = (cur + 1) % n
    else:
        nxt = (used_manifest_index + 1) % n

    state.setdefault("cursor", {})["manifest_index"] = nxt


def pinterest_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def register_media_upload(token: str) -> Dict[str, Any]:
    url = f"{API_BASE}/media"
    resp = requests.post(url, headers=pinterest_headers(token), json={"media_type": "video"}, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"media/register failed: HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    for k in ("media_id", "upload_url", "upload_parameters"):
        if k not in data:
            raise RuntimeError(f"media/register response missing '{k}': {data}")
    return data


def download_video_to_temp(video_url: str) -> Tuple[str, str]:
    name_guess = video_url.split("/")[-1] or "video.mp4"
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    with requests.get(video_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return tmp_path, name_guess


def upload_video_to_s3(upload_url: str, upload_parameters: Dict[str, Any], temp_path: str, filename: str) -> None:
    fields = {str(k): str(v) for k, v in (upload_parameters or {}).items()}

    with open(temp_path, "rb") as f:
        files = {"file": (filename, f, "video/mp4")}
        resp = requests.post(upload_url, data=fields, files=files, timeout=180)

    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"s3/upload failed: HTTP {resp.status_code}: {resp.text[:500]}")


def poll_media_status(token: str, media_id: str) -> str:
    url = f"{API_BASE}/media/{media_id}"
    deadline = time.time() + MEDIA_POLL_TIMEOUT_SEC

    last_status = "registered"
    while time.time() < deadline:
        resp = requests.get(url, headers=pinterest_headers(token), timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"media/status failed: HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        last_status = (data.get("status") or "").lower()

        if last_status == "succeeded":
            return "succeeded"
        if last_status == "failed":
            return "failed"

        time.sleep(MEDIA_POLL_INTERVAL_SEC)

    return last_status


def create_video_pin(token: str, item: PinItem, media_id: str) -> Dict[str, Any]:
    url = f"{API_BASE}/pins"
    payload = {
        "board_id": item.board_id,
        "title": item.title,
        "description": item.description,
        "alt_text": item.alt,
        "link": item.destination_url,
        "media_source": {
            "source_type": "video_id",
            "media_id": str(media_id),
        },
    }
    resp = requests.post(url, headers=pinterest_headers(token), json=payload, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"pins/create failed: HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def update_state_for_attempt(
    state: Dict[str, Any],
    item: PinItem,
    result: str,
    *,
    pin_id: Optional[str] = None,
    media_id: Optional[str] = None,
    cover_image_url: Optional[str] = None,
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
            "board_id": item.board_id,
            "destination_url": item.destination_url,
            "title": item.title,
            "result": result,  # "success" | "failed"
            "attempts": attempts,
            "last_ts_utc": utc_now_iso(),
        }
    )
    if pin_id:
        rec["pin_id"] = str(pin_id)
    if media_id:
        rec["media_id"] = str(media_id)
    if cover_image_url:
        rec["cover_image_url"] = cover_image_url
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
            "pin_id": pin_id,
            "media_id": media_id,
            "error": error,
        }
    )


def try_git_commit_push(repo_root: Path, state_path: Path) -> None:
    if os.getenv("GITHUB_ACTIONS", "").lower() != "true":
        return

    rel = state_path.relative_to(repo_root).as_posix()

    def run(cmd: List[str]) -> Tuple[int, str]:
        p = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()

    code, out = run(["git", "add", rel])
    if code != 0:
        print(f"[git] add failed: {out}")
        return

    code, out = run(["git", "status", "--porcelain"])
    if code != 0:
        print(f"[git] status failed: {out}")
        return
    if not out.strip():
        return

    msg = "Update pinterest post state [skip ci]"
    code, out = run(["git", "commit", "-m", msg])
    if code != 0:
        print(f"[git] commit failed: {out}")
        return

    code, out = run(["git", "push"])
    if code != 0:
        print(f"[git] push failed: {out}")
        return


def main() -> int:
    token = os.getenv("PINTEREST_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: Missing env PINTEREST_ACCESS_TOKEN")
        return 2

    repo_root = repo_root_from_this_file()
    manifest_dir = repo_root / "pinterest" / "manifests"
    state_path = repo_root / "pinterest" / "state" / "pinterest_post_state.json"

    state = load_state(state_path)
    manifest_paths = get_manifest_paths(manifest_dir)

    item, used_manifest_index = pick_next_item_round_robin(manifest_paths, state)
    if not item:
        advance_cursor(state, manifest_paths, used_manifest_index=None)
        save_json_atomic(state_path, state)
        try_git_commit_push(repo_root, state_path)
        print("No pending pins found (all posted or max attempts reached).")
        return 0

    media_id = None
    temp_path = None

    try:
        temp_path, name_guess = download_video_to_temp(item.video_url)

        reg = register_media_upload(token)
        media_id = str(reg["media_id"])
        upload_url = reg["upload_url"]
        upload_params = reg["upload_parameters"]

        upload_video_to_s3(upload_url, upload_params, temp_path, name_guess)

        status = poll_media_status(token, media_id)
        if status != "succeeded":
            raise RuntimeError(f"media processing status: {status}")

        created = create_video_pin(token, item, media_id)
        pin_id = created.get("id")

        cover = None
        try:
            media = created.get("media") or {}
            cover = media.get("cover_image_url")
        except Exception:
            cover = None

        update_state_for_attempt(
            state,
            item,
            "success",
            pin_id=str(pin_id) if pin_id else None,
            media_id=media_id,
            cover_image_url=cover,
            error=None,
        )

        advance_cursor(state, manifest_paths, used_manifest_index)

        save_json_atomic(state_path, state)
        try_git_commit_push(repo_root, state_path)

        print(f"OK: Posted 1 pin. pin_id={pin_id} media_id={media_id} manifest={item.manifest_name}")
        return 0

    except Exception as e:
        err = str(e)

        update_state_for_attempt(
            state,
            item,
            "failed",
            pin_id=None,
            media_id=media_id,
            cover_image_url=None,
            error=err[:1000],
        )

        advance_cursor(state, manifest_paths, used_manifest_index)

        save_json_atomic(state_path, state)
        try_git_commit_push(repo_root, state_path)

        print(f"FAILED: {err}")
        return 1

    finally:
        if temp_path and Path(temp_path).exists():
            try:
                Path(temp_path).unlink()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())

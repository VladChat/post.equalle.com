# /pinterest/post_one_video_pin.py
# Purpose: Post exactly 1 video Pin using daily rotating manifests, then persist success/failure to pinterest/state/pinterest_post_state.json.

from __future__ import annotations

import json
import os
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import random


API_BASE = "https://api.pinterest.com/v5"

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


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def repo_root_from_this_file() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip()


def filename_from_url(url: str) -> str:
    return (url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1] or "video.mp4").strip()


def ensure_required_fields(pin: Dict[str, Any], manifest_name: str) -> PinItem:
    video_url = (pin.get("video_url") or "").strip()
    destination_url = ((pin.get("destination", {}) or {}).get("url") or "").strip()
    board_id = ((pin.get("board", {}) or {}).get("id") or "").strip()

    title = clip(pin.get("title", ""), TITLE_MAX)
    description = clip(pin.get("description", ""), DESC_MAX)
    alt = clip(pin.get("alt", ""), ALT_MAX)

    missing = []
    if not video_url: missing.append("video_url")
    if not destination_url: missing.append("destination.url")
    if not board_id: missing.append("board.id")
    if not title: missing.append("title")
    if not description: missing.append("description")
    if not alt: missing.append("alt")

    if missing:
        raise ValueError(f"[{manifest_name}] missing fields: {', '.join(missing)}")

    return PinItem(
        manifest_name=manifest_name,
        filename=filename_from_url(video_url),
        video_url=video_url,
        destination_url=destination_url,
        board_id=board_id,
        title=title,
        description=description,
        alt=alt,
    )


def load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {"version": 1, "rotation": {}, "items": {}, "runs": []}
    try:
        return load_json(state_path)
    except Exception:
        return {"version": 1, "rotation": {}, "items": {}, "runs": []}


def manifest_cycle_for_today(state: Dict[str, Any]) -> List[str]:
    rot = state.setdefault("rotation", {})
    today = utc_today()
    idx = int(rot.get("manifest_index", -1))

    if rot.get("last_day") != today:
        idx = (idx + 1) % len(MANIFEST_FILES_ORDER)
        rot["manifest_index"] = idx
        rot["last_day"] = today

    return MANIFEST_FILES_ORDER[idx:] + MANIFEST_FILES_ORDER[:idx]


def pick_next_item(manifest_dir: Path, state: Dict[str, Any]) -> Optional[PinItem]:
    print("[pin][pick] selecting next item…")

    for name in manifest_cycle_for_today(state):
        path = manifest_dir / name
        if not path.exists():
            continue

        print(f"[pin][pick] checking manifest: {name}")
        data = load_json(path)

        for raw in data.get("pins", []):
            item = ensure_required_fields(raw, name)
            rec = state.get("items", {}).get(item.video_url, {})
            if rec.get("result") == "success":
                continue
            if int(rec.get("attempts", 0)) >= MAX_ATTEMPTS_PER_VIDEO:
                continue

            print(f"[pin][pick] selected video: {item.video_url}")
            print(f"[pin][pick] destination_url: {item.destination_url}")
            print(f"[pin][pick] board_id: {item.board_id}")
            return item

    return None


def pinterest_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def register_media_upload(token: str) -> Dict[str, Any]:
    print("[pin][media] registering media upload")
    resp = requests.post(f"{API_BASE}/media", headers=pinterest_headers(token), json={"media_type": "video"})
    print("[pin][media] register status:", resp.status_code)
    if resp.status_code not in (200, 201):
        raise RuntimeError(resp.text)
    return resp.json()


def download_video_to_temp(video_url: str) -> Tuple[str, str]:
    print("[pin][media] downloading video:", video_url)
    name = filename_from_url(video_url)
    fd, tmp = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    with requests.get(video_url, stream=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)

    print("[pin][media] downloaded to:", tmp)
    return tmp, name


def create_video_pin(token: str, item: PinItem, media_id: str) -> Dict[str, Any]:
    cover_time = random.randint(1, 7)

    payload = {
        "board_id": item.board_id,
        "title": item.title,
        "description": item.description,
        "alt_text": item.alt,
        "link": item.destination_url,
        "media_source": {
            "source_type": "video_id",
            "media_id": media_id,
            "cover_image_key_frame_time": cover_time,
        },
    }

    print("[pin][create] POST /v5/pins")
    print("[pin][create] board_id:", item.board_id)
    print("[pin][create] link:", item.destination_url)
    print("[pin][create] title:", item.title)
    print("[pin][create] payload keys:", list(payload.keys()))

    resp = requests.post(
        f"{API_BASE}/pins",
        headers=pinterest_headers(token),
        json=payload,
        timeout=60,
    )

    print("[pin][create] response status:", resp.status_code)
    print("[pin][create] response body:", resp.text[:800])

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"pins/create failed: HTTP {resp.status_code}: {resp.text}")

    return resp.json()


def main() -> int:
    token = os.getenv("PINTEREST_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: Missing PINTEREST_ACCESS_TOKEN")
        return 2

    repo_root = repo_root_from_this_file()
    manifest_dir = repo_root / "pinterest" / "manifests"
    state_path = repo_root / "pinterest" / "state" / "pinterest_post_state.json"

    state = load_state(state_path)
    item = pick_next_item(manifest_dir, state)
    if not item:
        print("[pin] nothing to post")
        return 0

    temp_path = None
    media_id = None

    try:
        temp_path, name = download_video_to_temp(item.video_url)
        reg = register_media_upload(token)
        media_id = reg["media_id"]

        print("[pin][media] uploading to S3")
        requests.post(
            reg["upload_url"],
            data={str(k): str(v) for k, v in reg["upload_parameters"].items()},
            files={"file": (name, open(temp_path, "rb"), "video/mp4")},
        )

        print("[pin][media] polling status…")
        while True:
            r = requests.get(f"{API_BASE}/media/{media_id}", headers=pinterest_headers(token))
            status = (r.json().get("status") or "").lower()
            print("[pin][media] status:", status)
            if status in ("succeeded", "failed"):
                break
            time.sleep(3)

        if status != "succeeded":
            raise RuntimeError("media processing failed")

        create_video_pin(token, item, media_id)
        print("[pin] SUCCESS")
        return 0

    except Exception as e:
        print("[pin] FAILED:", str(e))
        return 1

    finally:
        if temp_path and Path(temp_path).exists():
            Path(temp_path).unlink()


if __name__ == "__main__":
    raise SystemExit(main())

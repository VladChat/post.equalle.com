# ============================================
# File: youtube-post/comment_worker.py
# Purpose:
# - Post ONE first comment under the most recent successful YouTube upload
# - No env/secret toggles
# - Deterministic, state-driven logic
#
# FINAL LOGIC:
# - commented              -> DONE forever
# - commented_unverified   -> scheduled verification
# - skipped / failed       -> retry after cooldown
# ============================================

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests
from youtube_auth import get_access_token


# -----------------------------
# POLICY (CODE ONLY)
# -----------------------------
COMMENT_PROBABILITY = 1.0          # 0..1
MAX_COMMENT_ATTEMPTS = 2           # real POST attempts
VERIFY_DELAY_SEC = 60 * 30         # 30 min after POST
MAX_VERIFY_ATTEMPTS = 3
SKIP_RETRY_SEC = 60 * 60            # 1 hour


TEMPLATES = [
    "Light pressure with {grit} grit usually blends faster than pushing hard—let the Silicon Carbide abrasive do the cutting. Are you sanding wood, metal, drywall, or paint today?",
    "If the scratch pattern looks uneven, do a few light crosshatch passes and re-check under side light. Are you sanding wet or dry on {surface}?",
    "Keep the sanding block flat so you don’t dig grooves at the edges—especially on corners and seams.",
    "For {surface} work, feather the edges first, then refine the center so the blend disappears.",
    "If the paper loads up, rinse or replace it—clean paper cuts cleaner.",
]


# -----------------------------
# HELPERS
# -----------------------------
def base_dir() -> Path:
    return Path(__file__).resolve().parent


def load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(p: Path, data: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def now() -> float:
    return time.time()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_rng(seed: str) -> random.Random:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return random.Random(int(h[:8], 16))


def extract_video_id(url: str) -> str:
    if not url:
        return ""
    for rx in [
        r"/shorts/([A-Za-z0-9_-]{6,})",
        r"[?&]v=([A-Za-z0-9_-]{6,})",
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
    ]:
        m = re.search(rx, url)
        if m:
            return m.group(1)
    return ""


def surface_from_manifest(m: str) -> str:
    return (m or "").replace(".json", "").lower() or "surface"


def parse_grit(t: str) -> Optional[str]:
    if not t:
        return None
    m = re.search(r"(\d{2,4})\s*grit", t.lower())
    return m.group(1) if m else None


# -----------------------------
# YOUTUBE API
# -----------------------------
def post_comment(token: str, video_id: str, text: str) -> str:
    r = requests.post(
        "https://www.googleapis.com/youtube/v3/commentThreads",
        params={"part": "snippet"},
        headers={"Authorization": f"Bearer {token}"},
        json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}},
        timeout=60,
    )
    r.raise_for_status()
    return str(r.json().get("id") or "unknown")


def comment_exists(token: str, cid: str) -> bool:
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/commentThreads",
        params={"part": "id", "id": cid},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code == 404:
        return False
    r.raise_for_status()
    return bool(r.json().get("items"))


# -----------------------------
# CORE LOGIC
# -----------------------------
def iter_success_runs(post_state: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    runs = post_state.get("runs") or []
    if isinstance(runs, list):
        for r in reversed(runs):
            vid = r.get("youtube_video_id") or r.get("video_id") or extract_video_id(r.get("video_url", ""))
            if r.get("result") == "success" and vid:
                rr = dict(r)
                rr["youtube_video_id"] = vid
                yield rr


def pick_video(post_state: Dict[str, Any], cstate: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    items = cstate.setdefault("items", {})

    for run in iter_success_runs(post_state):
        vid = run["youtube_video_id"]
        rec = items.get(vid, {})
        st = rec.get("comment_status")

        # DONE forever
        if st == "commented":
            continue

        # unverified -> check if time to verify
        if st == "commented_unverified":
            if now() < rec.get("verify_after_ts", 0):
                continue
            return run, rec

        # skipped / failed -> retry after cooldown
        if st in {"skipped", "failed"}:
            if now() < rec.get("retry_after_ts", 0):
                continue
            return run, rec

        # new video
        return run, rec

    return None


# -----------------------------
# MAIN
# -----------------------------
def main() -> int:
    base = base_dir()
    post_p = base / "state" / "youtube_post_state.json"
    comm_p = base / "state" / "youtube_comment_state.json"

    if not post_p.exists():
        print("No post state.")
        return 0

    post_state = load_json(post_p)
    cstate = load_json(comm_p) if comm_p.exists() else {"version": 1, "items": {}, "runs": []}

    token = get_access_token()
    picked = pick_video(post_state, cstate)

    if not picked:
        print("No eligible video.")
        return 0

    run, rec = picked
    vid = run["youtube_video_id"]
    items = cstate["items"]

    # ---------------- verify path
    if rec.get("comment_status") == "commented_unverified":
        cid = rec.get("comment_id")
        tries = int(rec.get("verify_attempts", 0)) + 1

        if cid and comment_exists(token, cid):
            rec["comment_status"] = "commented"
            rec["comment_verified_ts"] = now_iso()
            print(f"VERIFIED: comment exists for {vid}")
        else:
            if tries >= MAX_VERIFY_ATTEMPTS:
                rec.pop("comment_status", None)  # allow repost
                rec.pop("comment_id", None)
                print(f"VERIFY FAILED: will repost later {vid}")
            else:
                rec["verify_attempts"] = tries
                rec["verify_after_ts"] = now() + VERIFY_DELAY_SEC
                print(f"VERIFY RETRY scheduled for {vid}")

        items[vid] = rec
        save_json(comm_p, cstate)
        return 0

    # ---------------- decide comment or skip
    rng = stable_rng(f"{vid}:{now()}")
    if COMMENT_PROBABILITY < 1.0 and rng.random() >= COMMENT_PROBABILITY:
        rec.update({
            "comment_status": "skipped",
            "retry_after_ts": now() + SKIP_RETRY_SEC,
            "comment_skipped_ts": now_iso(),
        })
        items[vid] = rec
        save_json(comm_p, cstate)
        print(f"SKIPPED: {vid}")
        return 0

    # ---------------- POST comment
    text = TEMPLATES[stable_rng(vid).randrange(len(TEMPLATES))]
    text = text.format(grit="this", surface=surface_from_manifest(run.get("manifest")))

    try:
        cid = post_comment(token, vid, text)
        rec.update({
            "comment_status": "commented_unverified",
            "comment_id": cid,
            "comment_text": text,
            "comment_attempts": rec.get("comment_attempts", 0) + 1,
            "commented_ts": now_iso(),
            "verify_after_ts": now() + VERIFY_DELAY_SEC,
        })
        cstate.setdefault("runs", []).append({
            "ts": now_iso(),
            "video_id": vid,
            "result": "commented_unverified",
            "comment_id": cid,
        })
        print(f"POSTED: comment for {vid}")
    except Exception as e:
        rec.update({
            "comment_status": "failed",
            "retry_after_ts": now() + SKIP_RETRY_SEC,
            "error": str(e),
        })
        print(f"FAILED: {vid} {e}")

    items[vid] = rec
    save_json(comm_p, cstate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

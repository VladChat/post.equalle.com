# ============================================
# File: youtube-post/comment_worker.py
# Purpose: Post a single "first comment" under the most recent successfully uploaded YouTube video,
#          using TWO state files:
#          - youtube/state/youtube_post_state.json  (read-only)
#          - youtube/state/youtube_comment_state.json (write)
# Notes:
# - Best practice: comment is delayed and optional.
# - Safety: 10% of posts are skipped (no comment), 90% get exactly 1 comment.
# - No repeats: comment state records comment_status/comment_id to prevent duplicates.
# - Jitter: optional random delay (default up to 1 hour).
# ============================================

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from youtube_auth import get_access_token


# Comment policy
COMMENT_PROBABILITY = 0.90  # 90% comment, 10% skip
MAX_COMMENT_ATTEMPTS = 2

# Jitter (random delay to look natural)
DEFAULT_JITTER_MAX_SEC = 36

# 8–12 templates (short, human-like, no links)
TEMPLATES = [
    "Light pressure with {grit} grit usually blends faster than pushing hard. What are you sanding today?",
    "If the scratch pattern looks uneven, do a few crosshatch passes and re-check. Sanding wet or dry?",
    "Keep the block flat so you don’t dig grooves at the edges. Are you using a sanding block or hand-only?",
    "For {surface} work, feather the edges first, then refine the center. What part is giving you trouble?",
    "If the paper starts loading up, wipe/rinse it and keep going—clean cuts cleaner. Does it clog on your surface?",
    "After sanding, wipe dust and check under a bright light from the side. Do the lines disappear evenly?",
    "If you’re jumping grits, don’t skip too far—blend one step at a time. What grit did you start with?",
    "Before the next coat, clean the surface well so dust doesn’t telegraph through. Do you wipe down between coats?",
    "If scratches stand out after paint/primer, the previous grit marks weren’t fully blended. What grit are you finishing with?",
    "Don’t chase one spot too long—blend the area wider and re-check. Are the edges still visible?",
    "If you’re getting random deep lines, the paper may be loaded or folded. Are you using fresh sheets?",
    "Quick check: if it still feels scratchy, you may need one grit lower for a short blend. Want a simple grit ladder?",
]


def base_dir_from_this_file() -> Path:
    # youtube-post/comment_worker.py -> base dir = youtube-post/
    return Path(__file__).resolve().parent



def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def utc_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def stable_rng(seed_text: str) -> random.Random:
    """Deterministic RNG per seed_text (stable across retries)."""
    h = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    seed = int(h[:8], 16)
    return random.Random(seed)


def parse_grit(text: str) -> Optional[str]:
    """Extract grit like '180' or '180–220' from filename/title/description patterns."""
    if not text:
        return None
    t = text.lower()

    m = re.search(r"(\d{2,4})\s*(?:[-_–]\s*(\d{2,4}))?\s*[_\s-]*grit(?=\b|[_-])", t)
    if m:
        a = m.group(1)
        b = m.group(2)
        if b and b != a:
            return f"{a}–{b}"
        return a

    m = re.search(r"grit[\s:_-]*(\d{2,4})(?:\s*[-_–]\s*(\d{2,4}))?(?=\b|[_-]|\s|$)", t)
    if m:
        a = m.group(1)
        b = m.group(2)
        if b and b != a:
            return f"{a}–{b}"
        return a

    return None


def surface_from_manifest(manifest_name: str) -> str:
    name = (manifest_name or "").replace(".json", "").strip().lower()
    mapping = {
        "drywall": "drywall",
        "wood": "wood",
        "metal": "metal",
        "plastic": "plastic",
        "wet": "wet-sanding",
    }
    return mapping.get(name, name or "surface")


def find_latest_success_post(post_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find latest successful upload run entry with youtube_video_id."""
    runs = post_state.get("runs") or []
    for run in reversed(runs):
        if not isinstance(run, dict):
            continue
        if run.get("result") != "success":
            continue
        vid = str(run.get("youtube_video_id") or "").strip()
        if not vid:
            continue
        return run
    return None


def youtube_post_comment_http(*, access_token: str, video_id: str, text: str) -> str:
    """Post a top-level comment and return commentThread id."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {"part": "snippet"}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=utf-8"}
    body = {"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}

    resp = requests.post(url, params=params, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    cid = str(payload.get("id") or "").strip()
    return cid or "unknown"


def main() -> int:
    base_dir = base_dir_from_this_file()

    post_state_path = base_dir / "state" / "youtube_post_state.json"
    comment_state_path = base_dir / "state" / "youtube_comment_state.json"

    if not post_state_path.exists():
        print("No post state yet (nothing to comment).")
        return 0

    post_state = load_json(post_state_path)
    run = find_latest_success_post(post_state)
    if not run:
        print("No eligible successful YouTube uploads found for commenting yet.")
        return 0

    video_id = str(run.get("youtube_video_id") or "").strip()
    video_url = str(run.get("video_url") or "").strip()
    manifest = str(run.get("manifest") or "").strip()

    # Load or init comment state
    if comment_state_path.exists():
        cstate = load_json(comment_state_path)
    else:
        cstate = {"version": 1, "items": {}, "runs": []}

    items = cstate.setdefault("items", {})
    if not isinstance(items, dict):
        cstate["items"] = {}
        items = cstate["items"]

    rec = items.get(video_id) or {}

    status = str(rec.get("comment_status") or "").strip().lower()
    if status in ("commented", "skipped"):
        print(f"Already processed: {status}. video_id={video_id}")
        return 0

    attempts = int(rec.get("comment_attempts", 0) or 0)
    if attempts >= MAX_COMMENT_ATTEMPTS:
        print(f"Max comment attempts reached. video_id={video_id}")
        return 0

    # --------- JITTER ----------
    try:
        jitter_max = int((os.getenv("YOUTUBE_COMMENT_JITTER_MAX_SEC") or str(DEFAULT_JITTER_MAX_SEC)).strip())
    except Exception:
        jitter_max = DEFAULT_JITTER_MAX_SEC
    if jitter_max < 0:
        jitter_max = 0

    if jitter_max > 0:
        jitter_seed = f"{video_id}|{utc_today()}"
        jrng = stable_rng(jitter_seed)
        delay = jrng.randint(0, jitter_max)
        if delay > 0:
            print(f"[comment_worker] jitter sleep: {delay}s (max={jitter_max}s) video_id={video_id}")
            time.sleep(delay)

    # Stable decision per video
    plan = rec.get("comment_plan") if isinstance(rec.get("comment_plan"), dict) else {}
    if plan.get("decision") in ("comment", "skip"):
        decision = plan["decision"]
        template_idx = int(plan.get("template_idx", 0) or 0) % len(TEMPLATES)
    else:
        rng = stable_rng(video_id)
        decision = "comment" if rng.random() < COMMENT_PROBABILITY else "skip"
        template_idx = rng.randrange(len(TEMPLATES))
        plan = {"decision": decision, "template_idx": template_idx}

    rec.update(
        {
            "video_id": video_id,
            "video_url": video_url,
            "manifest": manifest,
            "comment_plan": plan,
        }
    )

    if decision == "skip":
        rec["comment_status"] = "skipped"
        rec["comment_skipped_ts_utc"] = utc_now_iso()
        rec["comment_skipped_reason"] = "policy_10pct_skip"
        items[video_id] = rec
        save_json_atomic(comment_state_path, cstate)
        print(f"SKIP: Policy skip (10%). video_id={video_id} manifest={manifest}")
        return 0

    # Build message using post_state item details if available
    post_items = post_state.get("items") or {}
    post_rec = post_items.get(video_url) if isinstance(post_items, dict) else {}

    filename = str((post_rec or {}).get("filename") or "")
    title = str((post_rec or {}).get("title") or "")
    desc = str((post_rec or {}).get("description") or "")

    grit = parse_grit(filename) or parse_grit(title) or parse_grit(desc) or "this"
    surface = surface_from_manifest(manifest)

    msg = TEMPLATES[template_idx].format(grit=grit, surface=surface).strip()

    # Persist attempt before calling API
    attempts += 1
    rec["comment_attempts"] = attempts
    rec["comment_last_try_ts_utc"] = utc_now_iso()
    rec["comment_text"] = msg
    rec["comment_status"] = "pending"
    items[video_id] = rec
    save_json_atomic(comment_state_path, cstate)

    dry_run = (os.getenv("YOUTUBE_COMMENT_DRY_RUN") or os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes")
    if dry_run:
        rec["comment_status"] = "dry_run"
        items[video_id] = rec
        cstate.setdefault("runs", []).append(
            {"ts_utc": utc_now_iso(), "video_id": video_id, "result": "dry_run", "template_idx": template_idx}
        )
        save_json_atomic(comment_state_path, cstate)
        print(f"DRY RUN: would comment on video_id={video_id}: {msg}")
        return 0

    # OAuth access token
    try:
        access_token = get_access_token()
    except Exception as e:
        rec["comment_status"] = "failed"
        rec["comment_error"] = str(e)[:1500]
        items[video_id] = rec
        cstate.setdefault("runs", []).append(
            {"ts_utc": utc_now_iso(), "video_id": video_id, "result": "failed", "error": str(e)[:500]}
        )
        save_json_atomic(comment_state_path, cstate)
        print(f"FAILED: {e}")
        return 2

    try:
        cid = youtube_post_comment_http(access_token=access_token, video_id=video_id, text=msg)

        rec["comment_status"] = "commented"
        rec["comment_id"] = cid
        rec["commented_ts_utc"] = utc_now_iso()
        rec.pop("comment_error", None)
        items[video_id] = rec

        cstate.setdefault("runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_id": video_id,
                "video_url": video_url,
                "manifest": manifest,
                "result": "commented",
                "comment_id": cid,
                "template_idx": template_idx,
            }
        )
        save_json_atomic(comment_state_path, cstate)

        print(f"OK: Commented. video_id={video_id} comment_id={cid} manifest={manifest}")
        return 0
    except requests.HTTPError as e:
        err = (getattr(e.response, "text", "") or str(e))
        rec["comment_status"] = "failed"
        rec["comment_error"] = err[:1500]
        items[video_id] = rec
        cstate.setdefault("runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_id": video_id,
                "video_url": video_url,
                "manifest": manifest,
                "result": "failed",
                "error": err[:500],
                "template_idx": template_idx,
            }
        )
        save_json_atomic(comment_state_path, cstate)
        print(f"FAILED: {err}")
        return 1

    except Exception as e:
        rec["comment_status"] = "failed"
        rec["comment_error"] = str(e)[:1500]
        items[video_id] = rec
        cstate.setdefault("runs", []).append(
            {"ts_utc": utc_now_iso(), "video_id": video_id, "result": "failed", "error": str(e)[:500]},
        )
        save_json_atomic(comment_state_path, cstate)
        print(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

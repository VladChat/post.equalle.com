# ============================================
# File: facebook_reels/comment_worker.py
# Purpose: Post a single "first comment" under the most recent successfully published FB Reel,
#          using the shared facebook_reels post state file.
# Notes:
# - Separate from posting workflow (best practice): comment is delayed and optional.
# - Safety: 20% of posts are skipped (no comment), 80% get exactly 1 comment.
# - No repeats: state records comment_status/comment_id to prevent duplicates.
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


DEFAULT_GRAPH_API_VERSION = "v21.0"
STATE_REL_PATH = Path("facebook_reels/state/facebook_reels_post_state.json")

# Comment policy
COMMENT_PROBABILITY = 0.80  # 80% comment, 20% skip
MAX_COMMENT_ATTEMPTS = 2

# 5–7 templates (human-like, short, no links)
TEMPLATES = [
    "Quick tip: Use light pressure with {grit} grit and keep strokes consistent. What surface are you sanding?",
    "If scratches still show, step back one grit and blend again. What grit are you using next?",
    "Keep the block flat—don’t dig the edges. Are you sanding wet or dry on this project?",
    "For {surface} prep: feather the edges first, then refine. What’s the hardest part so far?",
    "If the paper loads up, rinse/clean it and keep moving. Want a simple grit guide? Comment “GRIT”.",
    "After sanding, wipe dust and check under a bright light. Did the scratch pattern even out?",
    "Small circles for blending, straight passes for leveling. What finish are you aiming for?",
]


def repo_root_from_this_file() -> Path:
    # facebook_reels/comment_worker.py -> repo root = two levels up
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def graph_base(version: str) -> str:
    version = (version or DEFAULT_GRAPH_API_VERSION).strip()
    if not version.startswith("v"):
        version = "v" + version
    return f"https://graph.facebook.com/{version}"


def stable_rng(seed_text: str) -> random.Random:
    """
    Deterministic RNG per video_id (or url). This prevents reruns from changing
    skip/comment decision and template selection.
    """
    h = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    seed = int(h[:8], 16)
    return random.Random(seed)


def parse_grit(text: str) -> Optional[str]:
    """
    Extract grit like '180' or '180–220' from filename/title/description patterns.
    Accepts: 180_grit, 180-220_grit, 180_220_grit, '180 grit', etc.
    """
    if not text:
        return None
    t = text.lower()

    # Prefer explicit 'grit' markers to avoid accidentally capturing the trailing index like '-021'.
    # Accepts: 180_grit, 180-grit, 180 grit, 180–220_grit, etc.
    m = re.search(r"(\d{2,4})\s*(?:[-_–]\s*(\d{2,4}))?\s*[_\s-]*grit(?=\b|[_-])", t)
    if m:
        a = m.group(1)
        b = m.group(2)
        if b and b != a:
            return f"{a}–{b}"
        return a

    # Also accept: 'grit 180' / 'grit:180'
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


def find_latest_success_to_comment(state: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Returns (run_entry, item_record) for the latest successful run that:
    - has a video_id
    - has not been commented/skipped yet
    """
    runs = state.get("runs") or []
    items = state.get("items") or {}

    for run in reversed(runs):
        if not isinstance(run, dict):
            continue
        if run.get("result") != "success":
            continue

        video_id = (run.get("video_id") or "").strip()
        video_url = (run.get("video_url") or "").strip()
        if not video_id or not video_url:
            continue

        rec = items.get(video_url) or {}
        comment_status = (rec.get("comment_status") or "").strip().lower()
        if comment_status in ("commented", "skipped"):
            continue

        # If previous attempts exceeded, skip
        attempts = int(rec.get("comment_attempts", 0) or 0)
        if attempts >= MAX_COMMENT_ATTEMPTS:
            continue

        return run, rec

    return None, None


def post_comment(video_id: str, token: str, version: str, message: str) -> str:
    """
    POST /{video_id}/comments
    Returns comment_id.
    """
    url = f"{graph_base(version)}/{video_id}/comments"
    resp = requests.post(url, data={"access_token": token, "message": message}, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"comment failed: HTTP {resp.status_code}: {resp.text[:800]}")
    data = resp.json()
    cid = (data.get("id") or "").strip()
    if not cid:
        # Sometimes API returns success without id; still treat as success but log placeholder
        cid = "unknown"
    return cid


def main() -> int:
    token = (
        os.getenv("FB_PAGE_TOKEN")
        or os.getenv("FB_PAGE_ACCESS_TOKEN")
        or os.getenv("FACEBOOK_PAGE_TOKEN")
        or ""
    ).strip()
    if not token:
        print("ERROR: Missing env FB_PAGE_TOKEN (or FB_PAGE_ACCESS_TOKEN / FACEBOOK_PAGE_TOKEN)")
        return 2

    version = (os.getenv("GRAPH_API_VERSION") or DEFAULT_GRAPH_API_VERSION).strip()

    repo_root = repo_root_from_this_file()
    state_path = repo_root / STATE_REL_PATH

    if not state_path.exists():
        print(f"No state file yet: {STATE_REL_PATH} (nothing to comment).")
        return 0

    state = load_json(state_path)

    run, rec = find_latest_success_to_comment(state)
    if not run:
        print("No eligible successful reels found for commenting (already commented/skipped or none posted yet).")
        return 0

    video_id = str(run.get("video_id")).strip()
    video_url = str(run.get("video_url")).strip()
    manifest = str(run.get("manifest") or rec.get("manifest") or "").strip()

    # Determine (or reuse) plan for this video
    plan = rec.get("comment_plan") or {}
    if not isinstance(plan, dict):
        plan = {}

    if plan.get("decision") in ("comment", "skip"):
        decision = plan["decision"]
        template_idx = int(plan.get("template_idx", 0) or 0) % len(TEMPLATES)
    else:
        rng = stable_rng(video_id or video_url)
        decision = "comment" if rng.random() < COMMENT_PROBABILITY else "skip"
        template_idx = rng.randrange(len(TEMPLATES))
        plan = {"decision": decision, "template_idx": template_idx}

    # Ensure record exists in items
    items = state.setdefault("items", {})
    if not isinstance(items, dict):
        state["items"] = {}
        items = state["items"]
    if video_url and video_url not in items:
        items[video_url] = {}
    rec2 = items.get(video_url) or {}

    # Save plan to record (so reruns are stable)
    rec2["comment_plan"] = plan

    if decision == "skip":
        rec2["comment_status"] = "skipped"
        rec2["comment_skipped_ts_utc"] = utc_now_iso()
        rec2["comment_skipped_reason"] = "policy_20pct_skip"
        items[video_url] = rec2
        save_json_atomic(state_path, state)
        print(f"SKIP: Policy skip (20%). video_id={video_id} manifest={manifest}")
        return 0

    # Build message
    filename = str(rec2.get("filename") or "")
    title = str(rec2.get("title") or "")
    desc = str(rec2.get("description") or "")

    grit = parse_grit(filename) or parse_grit(title) or parse_grit(desc) or "this"
    surface = surface_from_manifest(manifest)

    msg = TEMPLATES[template_idx].format(grit=grit, surface=surface).strip()

    # Attempt comment
    attempts = int(rec2.get("comment_attempts", 0) or 0) + 1
    rec2["comment_attempts"] = attempts
    rec2["comment_last_try_ts_utc"] = utc_now_iso()
    rec2["comment_text"] = msg
    rec2["comment_status"] = "pending"
    items[video_url] = rec2
    save_json_atomic(state_path, state)

    dry_run = (os.getenv("FB_REELS_COMMENT_DRY_RUN") or os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes")
    if dry_run:
        rec2["comment_status"] = "dry_run"
        items[video_url] = rec2
        save_json_atomic(state_path, state)
        print(f"DRY RUN: would comment on video_id={video_id}: {msg}")
        return 0

    try:
        cid = post_comment(video_id=video_id, token=token, version=version, message=msg)
        rec2["comment_status"] = "commented"
        rec2["comment_id"] = cid
        rec2["commented_ts_utc"] = utc_now_iso()
        rec2.pop("comment_error", None)
        items[video_url] = rec2

        state.setdefault("comment_runs", []).append(
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
        save_json_atomic(state_path, state)

        print(f"OK: Commented on Reel. video_id={video_id} comment_id={cid} manifest={manifest}")
        return 0

    except Exception as e:
        rec2["comment_status"] = "failed"
        rec2["comment_error"] = str(e)[:1500]
        items[video_url] = rec2

        state.setdefault("comment_runs", []).append(
            {
                "ts_utc": utc_now_iso(),
                "video_id": video_id,
                "video_url": video_url,
                "manifest": manifest,
                "result": "failed",
                "error": str(e)[:500],
                "template_idx": template_idx,
            }
        )
        save_json_atomic(state_path, state)

        print(f"FAILED: {e}")
        # Non-zero so workflow shows failure; retriable if attempts < MAX_COMMENT_ATTEMPTS
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

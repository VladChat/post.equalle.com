# ============================================
# File: youtube-post/comment_worker.py
# Purpose: Post a single "first comment" under the most recent successfully uploaded YouTube video,
#          using TWO state files:
#          - youtube-post/state/youtube_post_state.json      (read-only)
#          - youtube-post/state/youtube_comment_state.json   (write)
# Notes:
# - Best practice: comment is delayed and optional.
# - No repeats by default: 1 comment per video unless comment is missing (deleted/hidden).
# - Fix: scan recent uploads until we find an eligible video (not only the latest run).
# - Fix: verify that "commented" commentThread still exists; if missing -> retry later.
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
COMMENT_PROBABILITY = 0.90  # 90% comment, 10% skip (override with YOUTUBE_COMMENT_ALWAYS=1)
MAX_COMMENT_ATTEMPTS = 2

# Jitter (random delay to look natural)
DEFAULT_JITTER_MAX_SEC = 36

# 8–12 templates (short, human-like, no links)
TEMPLATES = [
    "Light pressure with {grit} grit usually blends faster than pushing hard—let the Silicon Carbide abrasive do the cutting. Are you sanding wood, metal, drywall, or paint today?",
    "If the scratch pattern looks uneven, do a few light crosshatch passes and re-check under side light. Are you sanding wet or dry on {surface}?",
    "Keep the sanding block flat so you don’t dig grooves at the edges—especially on corners and seams. Are you using a block, a pad, or hand-only?",
    "For {surface} work, feather the edges first, then refine the center so the blend disappears into the surrounding area. What part is giving you trouble—edges, center, or corners?",
    "If the paper starts loading up, wipe/rinse it and keep going—clean paper cuts more consistently. Does your {surface} clog fast when sanding?",
    "After sanding, wipe dust and check under a bright light from the side to reveal remaining lines and waves. Do the marks disappear evenly across the whole area?",
    "If you’re jumping grits, don’t skip too far—blend one step at a time so previous scratches don’t telegraph through primer or paint. What grit did you start with?",
    "Before the next coat, clean the surface so dust doesn’t show through paint, stain, or clear coat—tack cloth or damp wipe helps. Do you wipe down between coats?",
    "If scratches stand out after primer/paint, the previous grit marks weren’t fully blended—go back one step briefly and re-feather. What grit are you finishing with now?",
    "Don’t chase one spot too long—blend the area wider and re-check so you don’t create a low spot. Are the edges still visible on your {surface}?",
    "If you’re getting random deep lines, the sheet may be loaded, folded, or contaminated—swap to a fresh 9x11 sheet and keep strokes light. Are you using fresh sheets?",
    "Quick check: if it still feels scratchy after {grit}, drop one grit lower for a short blend, then return to {grit} to refine. Want a simple grit ladder for your project?",
    "For paint prep on {surface}, sand just until the sheen turns uniformly dull—no shiny islands left behind. Are you prepping for primer, repaint, or touch-up?",
    "On drywall mud, keep pressure light and use longer strokes—short aggressive strokes can leave ridges you’ll see after paint. Are you sanding a seam, patch, or corner?",
    "For metal sanding on {surface}, wipe the surface often to clear swarf—built-up dust can scratch deeper than your target grit. Are you removing rust or refining a finish?",
    "For wet sanding, a quick rinse keeps the scratch pattern tighter and helps prevent clogging—especially above 400 grit. Are you using a spray bottle or dipping the sheet?",
    "When sanding curves on {surface}, wrap the sheet around a soft pad so you keep contact without creating flat spots. Is it a curve, radius, or tight inside corner?",
    "If you see pigtails or swirl marks, reduce pressure and change direction—then finish with straight, consistent passes. Are you sanding by hand or with a sander?",
    "Between coats of paint or clear coat on {surface}, use a light touch and stop as soon as the surface feels even—over-sanding can cut through edges. Which coat are you on?",
    "For wood sanding, follow the grain on the final passes after crosshatch blending—grain-direction finishing hides micro-scratches better. What wood type are you working with?",
    "If the surface feels smooth but still looks cloudy, your scratches may be too coarse—step up one grit and re-check under strong light. What finish are you aiming for on {surface}?",
    "On plastic or resin {surface}, keep the sheet moving and avoid heat buildup—heat can smear and clog the abrasive. Are you sanding dry or doing a controlled wet sand?",
    "If you’re trying to level a bump, mark the area lightly with pencil and sand until the marks fade evenly—great for spotting highs and lows. Want the pencil-check method for {surface}?",
    "For auto body sanding on {surface}, keep overlaps consistent and use a clean wipe between grit changes—leftover grit can cause deeper scratches. Are you sanding primer, clear coat, or a blend panel?",
    "If you’re unsure which grit to grab next, match it to the goal: shape, level, smooth, or polish—each step should remove the last step’s scratches. What result do you want: faster removal or a finer finish?",
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


def iter_success_runs(post_state: Dict[str, Any]):
    """Yield success runs from newest to oldest with youtube_video_id present."""
    runs = post_state.get("runs") or []
    for run in reversed(runs):
        if not isinstance(run, dict):
            continue
        if run.get("result") != "success":
            continue
        vid = str(run.get("youtube_video_id") or "").strip()
        if not vid:
            continue
        yield run


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


def youtube_commentthread_exists(*, access_token: str, comment_thread_id: str) -> bool:
    """Best-effort: verify that commentThread still exists."""
    if not comment_thread_id or comment_thread_id == "unknown":
        return False
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {"part": "id", "id": comment_thread_id}
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    data = resp.json() or {}
    items = data.get("items") or []
    return bool(items)


def pick_eligible_video_run(
    *,
    post_state: Dict[str, Any],
    comment_state: Dict[str, Any],
    access_token_for_verify: Optional[str],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Return (run, rec) for the newest video that needs a comment.
    Fix: do NOT stop at the latest run if it's already processed; scan backwards.
    Fix: if state says 'commented' but commentThread is missing, allow retry.
    """
    items = comment_state.setdefault("items", {})
    if not isinstance(items, dict):
        comment_state["items"] = {}
        items = comment_state["items"]

    retry_skipped = (os.getenv("YOUTUBE_COMMENT_RETRY_SKIPPED") or "").strip().lower() in ("1", "true", "yes")

    for run in iter_success_runs(post_state):
        video_id = str(run.get("youtube_video_id") or "").strip()
        if not video_id:
            continue

        rec = items.get(video_id) or {}
        status = str(rec.get("comment_status") or "").strip().lower()

        # Allow retry if previously commented but comment is gone
        if status == "commented":
            cid = str(rec.get("comment_id") or "").strip()
            if access_token_for_verify and cid:
                try:
                    if youtube_commentthread_exists(access_token=access_token_for_verify, comment_thread_id=cid):
                        continue  # truly commented, skip this video
                    # Missing: mark and allow retry
                    rec["comment_status"] = "missing"
                    rec["comment_missing_detected_ts_utc"] = utc_now_iso()
                    items[video_id] = rec
                except Exception:
                    # If verify fails, keep existing status and move on to next run
                    continue
            else:
                continue  # no way to verify; keep conservative behavior

        if status == "skipped" and not retry_skipped:
            continue

        attempts = int(rec.get("comment_attempts", 0) or 0)
        if attempts >= MAX_COMMENT_ATTEMPTS:
            continue

        return run, rec

    return None


def main() -> int:
    base_dir = base_dir_from_this_file()

    post_state_path = base_dir / "state" / "youtube_post_state.json"
    comment_state_path = base_dir / "state" / "youtube_comment_state.json"

    if not post_state_path.exists():
        print("No post state yet (nothing to comment).")
        return 0

    post_state = load_json(post_state_path)

    # Load or init comment state
    if comment_state_path.exists():
        cstate = load_json(comment_state_path)
    else:
        cstate = {"version": 1, "items": {}, "runs": []}

    # Get token early (also used for verifying "commented but missing")
    try:
        access_token = get_access_token()
    except Exception as e:
        # If we can't auth, we also can't verify; keep state unchanged.
        print(f"FAILED: cannot get access token: {e}")
        return 2

    picked = pick_eligible_video_run(post_state=post_state, comment_state=cstate, access_token_for_verify=access_token)
    if not picked:
        print("No eligible successful YouTube uploads found for commenting yet.")
        # Save in case we marked something as missing during scan
        save_json_atomic(comment_state_path, cstate)
        return 0

    run, rec = picked
    video_id = str(run.get("youtube_video_id") or "").strip()
    video_url = str(run.get("video_url") or "").strip()
    manifest = str(run.get("manifest") or "").strip()

    # JITTER
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

    # Decision
    always_comment = (os.getenv("YOUTUBE_COMMENT_ALWAYS") or "").strip().lower() in ("1", "true", "yes")

    plan = rec.get("comment_plan") if isinstance(rec.get("comment_plan"), dict) else {}
    if plan.get("decision") in ("comment", "skip") and not always_comment:
        decision = plan["decision"]
        template_idx = int(plan.get("template_idx", 0) or 0) % len(TEMPLATES)
    else:
        rng = stable_rng(video_id)
        decision = "comment" if (always_comment or rng.random() < COMMENT_PROBABILITY) else "skip"
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

    items = cstate.setdefault("items", {})
    if not isinstance(items, dict):
        cstate["items"] = {}
        items = cstate["items"]

    if decision == "skip" and not always_comment:
        rec["comment_status"] = "skipped"
        rec["comment_skipped_ts_utc"] = utc_now_iso()
        rec["comment_skipped_reason"] = "policy_skip"
        items[video_id] = rec
        save_json_atomic(comment_state_path, cstate)
        print(f"SKIP: Policy skip. video_id={video_id} manifest={manifest}")
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
    attempts = int(rec.get("comment_attempts", 0) or 0) + 1
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

    try:
        cid = youtube_post_comment_http(access_token=access_token, video_id=video_id, text=msg)

        # Verify existence; if missing -> do NOT lock as commented
        exists = False
        try:
            exists = youtube_commentthread_exists(access_token=access_token, comment_thread_id=cid)
        except Exception:
            exists = False

        if not exists:
            rec["comment_status"] = "missing"
            rec["comment_id"] = cid
            rec["comment_missing_detected_ts_utc"] = utc_now_iso()
            items[video_id] = rec
            cstate.setdefault("runs", []).append(
                {
                    "ts_utc": utc_now_iso(),
                    "video_id": video_id,
                    "video_url": video_url,
                    "manifest": manifest,
                    "result": "missing",
                    "comment_id": cid,
                    "template_idx": template_idx,
                }
            )
            save_json_atomic(comment_state_path, cstate)
            print(f"WARNING: posted comment but cannot verify it exists. Will retry later. video_id={video_id} comment_id={cid}")
            return 0

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

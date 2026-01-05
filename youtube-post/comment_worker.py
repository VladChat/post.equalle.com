# ============================================
# File: youtube-post/comment_worker.py
# Purpose: Post a single "first comment" under the most recent successfully uploaded YouTube video,
#          using TWO state files:
#          - youtube-post/state/youtube_post_state.json      (read-only)
#          - youtube-post/state/youtube_comment_state.json   (write)
#
# Fixes (2026-01-05):
# - DO NOT immediately verify comment existence after POST (YouTube often lags).
# - Add verification on subsequent runs for commented_unverified/commented.
#   If commentThread still not found after a delay -> mark not_found and allow one retry.
# - Preserve COMMENT_PROBABILITY logic.
# - Add helpful diagnostics + direct YouTube links for commentThread IDs.
# ============================================

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Iterator, List

import requests

from youtube_auth import get_access_token


# Comment policy
COMMENT_PROBABILITY = 0.90  # override with YOUTUBE_COMMENT_ALWAYS=1
MAX_COMMENT_ATTEMPTS = 2

# Jitter
DEFAULT_JITTER_MAX_SEC = 36

# Verification
VERIFY_DELAY_SEC = 180  # do not verify earlier than this after "commented_ts_utc"

# Templates (expanded by you)
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
    h = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    seed = int(h[:8], 16)
    return random.Random(seed)


def parse_grit(text: str) -> Optional[str]:
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


def extract_video_id_from_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip()

    m = re.search(r"/shorts/([A-Za-z0-9_-]{6,})", u)
    if m:
        return m.group(1)

    m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", u)
    if m:
        return m.group(1)

    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", u)
    if m:
        return m.group(1)

    return ""


def normalize_run(run: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(run)

    vid = (
        str(r.get("youtube_video_id") or "").strip()
        or str(r.get("video_id") or "").strip()
        or str(r.get("yt_video_id") or "").strip()
    )
    if not vid:
        vid = extract_video_id_from_url(str(r.get("youtube_url") or "").strip())
    if not vid:
        vid = extract_video_id_from_url(str(r.get("url") or "").strip())
    if not vid:
        vid = extract_video_id_from_url(str(r.get("video_link") or "").strip())

    r["youtube_video_id"] = vid

    res = str(r.get("result") or "").strip().lower()
    if not res:
        res = str(r.get("status") or "").strip().lower()
    r["result"] = res

    return r


def iter_success_runs(post_state: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    success_values = {"success", "uploaded", "posted", "ok", "done"}

    runs = post_state.get("runs") or []
    norm_runs: List[Dict[str, Any]] = []
    if isinstance(runs, list) and runs:
        for raw in runs:
            if isinstance(raw, dict):
                norm_runs.append(normalize_run(raw))

    if not norm_runs:
        items = post_state.get("items") or {}
        if isinstance(items, dict):
            for k, v in items.items():
                if not isinstance(v, dict):
                    continue
                rr = dict(v)
                rr.setdefault("video_url", rr.get("video_url") or k)
                rr.setdefault("manifest", rr.get("manifest") or rr.get("manifest_name") or "")
                rr = normalize_run(rr)
                norm_runs.append(rr)

    for run in reversed(norm_runs):
        res = str(run.get("result") or "").lower()
        if res not in success_values:
            continue
        vid = str(run.get("youtube_video_id") or "").strip()
        if not vid:
            continue
        yield run


def youtube_post_comment_http(*, access_token: str, video_id: str, text: str) -> str:
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


def yt_comment_link(video_id: str, comment_thread_id: str) -> str:
    if not video_id or not comment_thread_id:
        return ""
    return f"https://www.youtube.com/watch?v={video_id}&lc={comment_thread_id}"


def reconcile_legacy_missing(cstate: Dict[str, Any]) -> bool:
    items = cstate.get("items")
    if not isinstance(items, dict):
        return False

    changed = False
    for vid, rec in items.items():
        if not isinstance(rec, dict):
            continue
        status = str(rec.get("comment_status") or "").strip().lower()
        if status == "missing":
            rec["comment_status"] = "commented_unverified"
            rec["comment_reconciled_ts_utc"] = utc_now_iso()
            items[vid] = rec
            changed = True
    return changed


def verify_pass(*, access_token: str, cstate: Dict[str, Any]) -> bool:
    """
    Verify older commented_unverified/commented records.
    If not found after delay -> mark not_found and allow one retry.
    """
    items = cstate.get("items")
    if not isinstance(items, dict):
        return False

    now = time.time()
    changed = False

    for vid, rec in list(items.items()):
        if not isinstance(rec, dict):
            continue

        status = str(rec.get("comment_status") or "").strip().lower()
        if status not in {"commented_unverified", "commented"}:
            continue

        cid = str(rec.get("comment_id") or "").strip()
        ts = str(rec.get("commented_ts_utc") or "").strip()

        # no timestamp -> don't verify
        if not cid or not ts:
            continue

        # parse ISO-ish: YYYY-MM-DDTHH:MM:SSZ
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$", ts)
        if not m:
            continue

        # convert to epoch (UTC) without datetime import
        # crude but stable: use time.strptime
        try:
            t_struct = time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
            posted_epoch = time.mktime(t_struct)  # local, but good enough for delay check
        except Exception:
            continue

        if (now - posted_epoch) < VERIFY_DELAY_SEC:
            continue

        try:
            exists = youtube_commentthread_exists(access_token=access_token, comment_thread_id=cid)
        except Exception as e:
            rec["comment_verify_error"] = str(e)[:500]
            items[vid] = rec
            # don't change status on verify failures (avoid duplicates)
            continue

        if exists:
            if status != "commented":
                rec["comment_status"] = "commented"
                rec["comment_verified_ts_utc"] = utc_now_iso()
                items[vid] = rec
                changed = True
        else:
            # comment thread not found -> mark not_found and allow one retry even if attempts were burned by legacy logic
            rec["comment_status"] = "not_found"
            rec["comment_not_found_ts_utc"] = utc_now_iso()

            attempts = int(rec.get("comment_attempts", 0) or 0)
            if attempts >= MAX_COMMENT_ATTEMPTS:
                rec["comment_attempts"] = max(0, MAX_COMMENT_ATTEMPTS - 1)
                rec["comment_attempts_reopened_ts_utc"] = utc_now_iso()

            items[vid] = rec
            changed = True

    return changed


def pick_eligible_video_run(
    *,
    post_state: Dict[str, Any],
    comment_state: Dict[str, Any],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
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

        # DONE states
        if status in {"commented", "commented_unverified"}:
            continue

        if status == "skipped" and not retry_skipped:
            continue

        attempts = int(rec.get("comment_attempts", 0) or 0)
        if attempts >= MAX_COMMENT_ATTEMPTS:
            continue

        return run, rec

    return None


def debug_no_eligible(post_state: Dict[str, Any], cstate: Dict[str, Any]) -> None:
    items = cstate.get("items") if isinstance(cstate.get("items"), dict) else {}
    lines: List[str] = []
    for run in iter_success_runs(post_state):
        vid = str(run.get("youtube_video_id") or "").strip()
        manifest = str(run.get("manifest") or "").strip()
        rec = items.get(vid, {}) if isinstance(items, dict) else {}
        status = str(rec.get("comment_status") or "").strip().lower() or "none"
        attempts = int(rec.get("comment_attempts", 0) or 0)
        plan = rec.get("comment_plan") if isinstance(rec.get("comment_plan"), dict) else {}
        decision = str(plan.get("decision") or "")
        lines.append(f"- video_id={vid} manifest={manifest} status={status} attempts={attempts} plan_decision={decision}")

    if lines:
        print("[debug] Success videos seen + comment-state:")
        for s in lines[:50]:
            print(s)


def main() -> int:
    base_dir = base_dir_from_this_file()

    post_state_path = base_dir / "state" / "youtube_post_state.json"
    comment_state_path = base_dir / "state" / "youtube_comment_state.json"

    if not post_state_path.exists():
        print("No post state yet (nothing to comment).")
        return 0

    post_state = load_json(post_state_path)

    if comment_state_path.exists():
        cstate = load_json(comment_state_path)
    else:
        cstate = {"version": 1, "items": {}, "runs": []}

    changed = False
    changed = reconcile_legacy_missing(cstate) or changed

    try:
        access_token = get_access_token()
    except Exception as e:
        print(f"FAILED: cannot get access token: {e}")
        return 2

    # Verify older posted comments (after delay) and reopen one retry if truly not found
    changed = verify_pass(access_token=access_token, cstate=cstate) or changed
    if changed:
        save_json_atomic(comment_state_path, cstate)

    picked = pick_eligible_video_run(post_state=post_state, comment_state=cstate)
    if not picked:
        runs = post_state.get("runs")
        items = post_state.get("items")
        runs_n = len(runs) if isinstance(runs, list) else 0
        items_n = len(items) if isinstance(items, dict) else 0
        print(f"No eligible successful YouTube uploads found for commenting yet. post_state_runs={runs_n} post_state_items={items_n}")
        debug_no_eligible(post_state, cstate)
        return 0

    run, rec = picked
    video_id = str(run.get("youtube_video_id") or "").strip()
    video_url = str(run.get("video_url") or "").strip()
    manifest = str(run.get("manifest") or "").strip()

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

    rec.update({"video_id": video_id, "video_url": video_url, "manifest": manifest, "comment_plan": plan})

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

    post_items = post_state.get("items") or {}
    post_rec = None
    if isinstance(post_items, dict) and video_url:
        post_rec = post_items.get(video_url)
    if not isinstance(post_rec, dict):
        post_rec = {}

    filename = str((post_rec or {}).get("filename") or "")
    title = str((post_rec or {}).get("title") or "")
    desc = str((post_rec or {}).get("description") or "")

    grit = parse_grit(filename) or parse_grit(title) or parse_grit(desc) or "this"
    surface = surface_from_manifest(manifest)
    msg = TEMPLATES[template_idx].format(grit=grit, surface=surface).strip()

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
        cstate.setdefault("runs", []).append({"ts_utc": utc_now_iso(), "video_id": video_id, "result": "dry_run", "template_idx": template_idx})
        save_json_atomic(comment_state_path, cstate)
        print(f"DRY RUN: would comment on video_id={video_id}: {msg}")
        return 0

    try:
        cid = youtube_post_comment_http(access_token=access_token, video_id=video_id, text=msg)

        # Do NOT immediately verify here.
        rec["comment_status"] = "commented_unverified"
        rec["comment_id"] = cid
        rec["commented_ts_utc"] = utc_now_iso()
        rec.pop("comment_error", None)
        items[video_id] = rec

        cstate.setdefault("runs", []).append(
            {"ts_utc": utc_now_iso(), "video_id": video_id, "video_url": video_url, "manifest": manifest, "result": "commented_unverified", "comment_id": cid, "template_idx": template_idx}
        )
        save_json_atomic(comment_state_path, cstate)

        link = yt_comment_link(video_id, cid)
        if link:
            print(f"OK: Comment posted (unverified). video_id={video_id} comment_id={cid}")
            print(f"Open comment: {link}")
        else:
            print(f"OK: Comment posted (unverified). video_id={video_id} comment_id={cid}")
        return 0

    except requests.HTTPError as e:
        err = (getattr(e.response, "text", "") or str(e))
        rec["comment_status"] = "failed"
        rec["comment_error"] = err[:1500]
        items[video_id] = rec
        cstate.setdefault("runs", []).append(
            {"ts_utc": utc_now_iso(), "video_id": video_id, "video_url": video_url, "manifest": manifest, "result": "failed", "error": err[:500], "template_idx": template_idx}
        )
        save_json_atomic(comment_state_path, cstate)
        print(f"FAILED: {err}")
        return 1

    except Exception as e:
        rec["comment_status"] = "failed"
        rec["comment_error"] = str(e)[:1500]
        items[video_id] = rec
        cstate.setdefault("runs", []).append({"ts_utc": utc_now_iso(), "video_id": video_id, "result": "failed", "error": str(e)[:500]})
        save_json_atomic(comment_state_path, cstate)
        print(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

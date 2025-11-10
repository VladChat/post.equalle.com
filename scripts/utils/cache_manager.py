import json
from typing import List, Dict, Any, Set
from pathlib import Path

# ==========================================================
# cache_manager.py
# Shared helpers to manage cached posts (queue) and publish state.
#
# Design:
# - Cache is a list[post] sorted by recency (newest first).
# - State keeps a set of 'published' links per platform:
#     {
#       "published": {
#         "facebook": ["https://.../a", ".../b"],
#         "instagram": []
#       }
#     }
#   We only store links to avoid duplication.
# ==========================================================

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "cache" / "latest_posts.json"
STATE_PATH = ROOT / "data" / "state.json"

def _safe_read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def load_cache() -> List[Dict[str, Any]]:
    """Return cached posts list (may be empty)."""
    return _safe_read_json(CACHE_PATH, [])

def save_cache(posts: List[Dict[str, Any]]) -> None:
    """Write full cache safely."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")

def load_state() -> Dict[str, Any]:
    """Return state dict with 'published' map; create default if missing."""
    state = _safe_read_json(STATE_PATH, {})
    if "published" not in state or not isinstance(state["published"], dict):
        state["published"] = {}
    return state

def save_state(state: Dict[str, Any]) -> None:
    """Persist state."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def append_new_posts(new_posts: List[Dict[str, Any]], max_keep: int = 200) -> (int, int):
    """
    Add new posts to cache (front), skip duplicates by 'link'.
    Returns: (added_count, total_after).
    """
    cache = load_cache()
    known: Set[str] = {p.get("link", "") for p in cache}
    to_add = [p for p in new_posts if p.get("link") and p["link"] not in known]
    if to_add:
        cache = to_add + cache
        # Optional pruning for long caches (best practice to keep repo lean)
        if len(cache) > max_keep:
            cache = cache[:max_keep]
        save_cache(cache)
    return len(to_add), len(cache)

def was_published(platform: str, link: str) -> bool:
    """Check if a given link was already published for the platform."""
    state = load_state()
    published = state.get("published", {}).get(platform, [])
    return link in published

def mark_published(platform: str, link: str, max_keep: int = 300) -> None:
    """
    Mark link as published for platform. Keep only last N for compactness.
    """
    state = load_state()
    pub = state.setdefault("published", {}).setdefault(platform, [])
    if link not in pub:
        pub.append(link)
        if len(pub) > max_keep:
            # keep only most recent tail
            pub[:] = pub[-max_keep:]
        save_state(state)

def next_unpublished(platform: str) -> Dict[str, Any] | None:
    """Return the next post from cache that wasn't published to the given platform yet."""
    cache = load_cache()
    for post in cache:
        link = post.get("link")
        if not link:
            continue
        if not was_published(platform, link):
            return post
    return None

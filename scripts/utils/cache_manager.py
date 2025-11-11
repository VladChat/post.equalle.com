import json
from typing import List, Dict, Any, Set
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "cache" / "latest_posts.json"
STATE_PATH = ROOT / "data" / "state.json"

def _safe_read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def load_cache() -> List[Dict[str, Any]]:
    return _safe_read_json(CACHE_PATH, [])

def save_cache(posts: List[Dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")

def load_state() -> Dict[str, Any]:
    state = _safe_read_json(STATE_PATH, {})
    if "published" not in state or not isinstance(state.get("published"), dict):
        state["published"] = {}
    return state

def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def append_new_posts(new_posts: List[Dict[str, Any]], max_keep: int = 200) -> (int, int):
    cache = load_cache()
    known: Set[str] = {p.get("link", "") for p in cache}
    to_add = [p for p in new_posts if p.get("link") and p["link"] not in known]
    if to_add:
        cache = to_add + cache
        if len(cache) > max_keep:
            cache = cache[:max_keep]
        save_cache(cache)
    return len(to_add), len(cache)

def was_published(platform: str, link: str) -> bool:
    state = load_state()
    published = state.get("published", {}).get(platform, [])
    return link in published

def mark_published(platform: str, link: str, max_keep: int = 300) -> None:
    state = load_state()
    pub = state.setdefault("published", {}).setdefault(platform, [])
    if link not in pub:
        pub.append(link)
        if len(pub) > max_keep:
            pub[:] = pub[-max_keep:]
        save_state(state)

def next_unpublished(platform: str):
    cache = load_cache()
    for post in cache:
        link = post.get("link")
        if not link:
            continue
        if not was_published(platform, link):
            return post
    return None

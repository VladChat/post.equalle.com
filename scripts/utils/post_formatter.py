from typing import Dict, List

def _normalize_hashtags(tags: List[str] | None, limit: int | None = None) -> str:
    tags = tags or []
    if limit is not None:
        tags = tags[:limit]
    return " ".join([t if t.startswith("#") else f"#{t}" for t in tags])

def format_facebook(post: Dict) -> str:
    title = post.get("title", "").strip()
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    parts = [p for p in [title, summary, f"Read more: {link}"] if p]
    return "\n\n".join(parts)

def format_instagram(post: Dict) -> str:
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    tags = _normalize_hashtags(post.get("hashtags"), limit=15)
    parts = [p for p in [summary, link, tags] if p]
    return "\n\n".join(parts)[:2200]

def format_pinterest(post: Dict) -> str:
    title = post.get("title", "").strip()
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    return "\n".join([p for p in [title, summary, link] if p])[:500]

def format_twitter(post: Dict) -> str:
    title = post.get("title", "").strip()
    link = post.get("link", "").strip()
    tags = _normalize_hashtags(post.get("hashtags"), limit=3)
    return " ".join([t for t in [title, link, tags] if t])[:280]

def format_youtube(post: Dict) -> str:
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    return "\n\n".join([p for p in [summary, f"Full article: {link}"] if p])[:5000]

from typing import Dict, List

# ==========================================================
# post_formatter.py
# Build captions per platform from a normalized post dict:
# {
#   "title": str,
#   "summary": str,
#   "link": str,
#   "image": Optional[str],
#   "hashtags": List[str],
#   "published": str
# }
# ==========================================================

def _normalize_hashtags(tags: List[str] | None, limit: int | None = None) -> str:
    tags = tags or []
    if limit is not None:
        tags = tags[:limit]
    # ensure each starts with '#', join with space
    return " ".join([t if t.startswith("#") else f"#{t}" for t in tags])

def format_facebook(post: Dict) -> str:
    """Facebook caption: title, summary, link."""
    title = post.get("title", "").strip()
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    parts = [p for p in [title, summary, f"Read more: {link}"] if p]
    return "\n\n".join(parts)

def format_instagram(post: Dict) -> str:
    """Instagram caption: summary, link, ~15 hashtags."""
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    tags = _normalize_hashtags(post.get("hashtags"), limit=15)
    parts = [p for p in [summary, link, tags] if p]
    caption = "\n\n".join(parts)
    return caption[:2200]  # IG limit

def format_pinterest(post: Dict) -> str:
    """Pinterest description: title + summary + link."""
    title = post.get("title", "").strip()
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    parts = [p for p in [title, summary, link] if p]
    return "\n".join(parts)[:500]

def format_twitter(post: Dict) -> str:
    """X/Twitter (280 chars): title + link + ≤3 hashtags."""
    title = post.get("title", "").strip()
    link = post.get("link", "").strip()
    tags = _normalize_hashtags(post.get("hashtags"), limit=3)
    base = " ".join([t for t in [title, link, tags] if t])
    return base[:280]

def format_youtube(post: Dict) -> str:
    """YouTube description (short intro + link)."""
    summary = post.get("summary", "").strip()
    link = post.get("link", "").strip()
    parts = [p for p in [summary, f"Full article: {link}"] if p]
    return "\n\n".join(parts)[:5000]

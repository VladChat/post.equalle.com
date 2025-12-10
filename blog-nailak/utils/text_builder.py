# ============================================
# File: blog-nailak/utils/text_builder.py
# Purpose: Build platform-specific text from RSS Post
# ============================================

from __future__ import annotations

import html
import re
from typing import Dict

from rss.rss_parser import Post


def _strip_html(text: str) -> str:
    if not text:
        return ""
    # Remove HTML tags and unescape entities
    no_tags = re.sub(r"<[^>]+>", "", text)
    return html.unescape(no_tags).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_facebook_message(post: Post) -> str:
    """Short, readable text for Facebook feed."""
    desc = _strip_html(post.description or post.summary)
    desc = _truncate(desc, 400)

    lines = [
        post.title.strip(),
        "",
        desc,
        "",
        f"Read the full guide: {post.link}",
        "",
        "#sandpaper #sanding #eQualle",
    ]
    return "\n".join(line for line in lines if line is not None)


def build_instagram_caption(post: Post) -> str:
    """Caption style for Instagram."""
    desc = _strip_html(post.description or post.summary)
    desc = _truncate(desc, 800)

    lines = [
        post.title.strip(),
        "",
        desc,
        "",
        f"Full article on our blog: {post.link}",
        "",
        "#sandpaper #sanding #woodworking #autobody #eQualle",
    ]
    return "\n".join(line for line in lines if line is not None)


def build_pinterest_payload(post: Post, image_url: str) -> Dict[str, object]:
    """Returns JSON payload for /v5/pins endpoint."""
    desc = _strip_html(post.description or post.summary)
    desc = _truncate(desc, 500)

    payload: Dict[str, object] = {
        "title": _truncate(post.title.strip(), 100),
        "description": desc,
        "link": post.link,
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }
    return payload


def build_facebook_comment(post: Post) -> str:
    """Короткий follow-up комментарий к Facebook-посту:
    - без ссылки
    - 1–2 предложения
    - привязан к теме статьи
    """
    title = (post.title or "").strip()
    desc = _strip_html(post.description or post.summary)
    desc = _truncate(desc, 180)

    if title:
        return (
            f"If this topic comes up in your next sanding project, "
            f"save this post so you can revisit the steps from “{title}”."
        )

    return (
        "Quick tip: small changes in grit selection and sanding pressure usually give "
        "bigger improvements than buying new tools. Test on a scrap surface first."
    )


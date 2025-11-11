# ============================================================
# File: scripts/utils/fb_post_formatter.py
# Purpose: Build clean, structured Facebook captions from RSS data
# Author: Vladislav Doroshenko / eQualle Automation
# ============================================================

from typing import Dict, List
import re
import logging

logger = logging.getLogger("fb_post_formatter")


def _normalize_hashtags(categories: List[str] | None, limit: int = 10) -> str:
    """
    Converts XML <category> tags into lowercase hashtags.
    Keeps only alphanumeric characters, limits to 10.
    Example: ["Floor & Deck Sanding", "grit-220"] → "#floordecksanding #grit220"
    """
    categories = categories or []
    clean_tags = []
    for c in categories[:limit]:
        tag = re.sub(r"[^a-zA-Z0-9]", "", c.lower())  # remove symbols
        if tag:
            clean_tags.append(f"#{tag}")
    return " ".join(clean_tags)


def format_facebook(post: Dict) -> str:
    """
    Builds a rich Facebook caption using RSS item fields:
      - title
      - description
      - summary (first paragraph, stripped of HTML)
      - link
      - categories (as hashtags)
    """

    title = post.get("title", "").strip()
    desc = post.get("description", "").strip()
    link = post.get("link", "").strip()
    categories = post.get("categories", [])
    summary_html = post.get("summary", "")

    hashtags = _normalize_hashtags(categories)

    # Extract short readable text from <summary> if available
    summary_text = ""
    if summary_html:
        summary_text = re.sub(r"<[^>]+>", "", summary_html).strip()
        if len(summary_text) > 450:
            summary_text = summary_text[:450].rstrip() + "…"

    # === Build final caption ===
    parts = [
        f"🟢 {title}",
        "",
        desc,
        summary_text,
        "",
        f"👉 {link}",      # Clean, clickable Facebook-safe link (no HTML)
        "",
        hashtags,
    ]

    caption = "\n".join(p for p in parts if p)

    # Limit length (Facebook limit ~63,000 chars, but 5k is safe)
    caption = caption[:5000]

    logger.info(f"✅ Facebook caption built ({len(caption)} chars)")
    return caption

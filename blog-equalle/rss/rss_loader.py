# ============================================
# File: blog-equalle/rss/rss_loader.py
# Purpose: Download and parse RSS feed from blog.equalle.com
# ============================================

from __future__ import annotations

import os
from typing import List, Optional

import feedparser

from .rss_parser import parse_feed, Post


def load_posts(limit: Optional[int] = None) -> List[Post]:
    """Loads RSS feed and returns a list of Post objects (sorted by date desc)."""
    rss_url = os.getenv("BLOG_RSS_URL", "https://blog.equalle.com/index.xml")
    print(f"[rss][loader] Loading RSS: {rss_url}")

    feed = feedparser.parse(rss_url)

    if getattr(feed, "bozo", False):
        # feed.bozo_exception may contain parsing error
        print(f"[rss][loader][WARN] Problem parsing feed: {getattr(feed, 'bozo_exception', None)!r}")

    posts = parse_feed(feed, limit=limit)
    print(f"[rss][loader] Parsed posts: {len(posts)}")
    return posts

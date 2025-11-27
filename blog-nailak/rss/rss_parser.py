# ============================================
# File: blog-nailak/rss/rss_parser.py
# Purpose: Convert feedparser result into internal Post objects
# ============================================

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

from dateutil import parser as dateparser


@dataclass
class Post:
    title: str
    link: str
    published: Optional[datetime]
    summary: str
    description: str
    image_facebook: Optional[str]
    image_instagram: Optional[str]
    image_pinterest: Optional[str]
    image_generic: Optional[str]


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return dateparser.parse(str(value))
    except Exception:
        return None


def _extract_card_url_from_list(items: Any, platform: str) -> Optional[str]:
    """Extracts card URLs like /cards/facebook/, /cards/instagram/, /cards/pinterest/."""
    if not items:
        return None

    target = f"/cards/{platform}/"

    for item in items:
        url = None

        if isinstance(item, dict):
            url = item.get("url") or item.get("href") or item.get("hrefsrc")
        else:
            url = getattr(item, "url", None) or getattr(item, "href", None)

        if url and target in url:
            return url

    return None


def _extract_generic_image(entry: Any) -> Optional[str]:
    media_contents = getattr(entry, "media_content", []) or entry.get("media_content", [])
    for item in media_contents:
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if url:
            return url

    media_thumbnails = getattr(entry, "media_thumbnail", []) or entry.get("media_thumbnail", [])
    for item in media_thumbnails:
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if url:
            return url

    return None


def _extract_cards(entry: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    media_contents = getattr(entry, "media_content", []) or entry.get("media_content", [])
    media_thumbnails = getattr(entry, "media_thumbnail", []) or entry.get("media_thumbnail", [])
    links = getattr(entry, "links", []) or entry.get("links", [])

    facebook = (
        _extract_card_url_from_list(media_contents, "facebook")
        or _extract_card_url_from_list(media_thumbnails, "facebook")
        or _extract_card_url_from_list(links, "facebook")
    )
    instagram = (
        _extract_card_url_from_list(media_contents, "instagram")
        or _extract_card_url_from_list(media_thumbnails, "instagram")
        or _extract_card_url_from_list(links, "instagram")
    )
    pinterest = (
        _extract_card_url_from_list(media_contents, "pinterest")
        or _extract_card_url_from_list(media_thumbnails, "pinterest")
        or _extract_card_url_from_list(links, "pinterest")
    )

    return facebook, instagram, pinterest


def parse_feed(feed: Any, limit: Optional[int] = None) -> List[Post]:
    posts: List[Post] = []

    entries = getattr(feed, "entries", []) or feed.get("entries", [])

    for entry in entries:
        link = getattr(entry, "link", "") or entry.get("link")
        title = (getattr(entry, "title", "") or entry.get("title", "")).strip()

        if not link or not title:
            continue

        published = _parse_datetime(
            getattr(entry, "published", None) or entry.get("pubDate")
        )

        summary = getattr(entry, "summary", "") or entry.get("summary", "") or ""
        description = getattr(entry, "description", "") or entry.get("description", "") or ""

        fb_img, ig_img, pin_img = _extract_cards(entry)
        generic_img = _extract_generic_image(entry)

        post = Post(
            title=title,
            link=link,
            published=published,
            summary=summary,
            description=description,
            image_facebook=fb_img,
            image_instagram=ig_img,
            image_pinterest=pin_img,
            image_generic=generic_img,
        )
        posts.append(post)

    posts.sort(key=lambda p: p.published or datetime.min, reverse=True)

    if limit is not None and limit > 0:
        posts = posts[:limit]

    return posts

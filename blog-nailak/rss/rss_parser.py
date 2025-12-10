# ============================================
# File: blog-equalle/rss/rss_parser.py
# Purpose: Convert feedparser result into internal Post objects
# ============================================

from __future__ import annotations

from dataclasses import dataclass, field
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
    # Новое поле: список категорий из RSS (первая категория = главная)
    categories: List[str] = field(default_factory=list)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return dateparser.parse(str(value))
    except Exception:
        return None


def _extract_card_url_from_list(items: Any, platform: str) -> Optional[str]:
    """Looks for /cards/{platform}/ in media_content, media_thumbnail, links, etc."""
    if not items:
        return None

    target = f"/cards/{platform}/"
    for item in items:
        url = None
        if isinstance(item, dict):
            url = item.get("url") or item.get("href") or item.get("hrefsrc")
        else:
            url = getattr(item, "url", None) or getattr(item, "href", None)

        if not url:
            continue
        if target in url:
            return url
    return None


def _extract_generic_image(entry: Any) -> Optional[str]:
    # Try media:content with .webp or brand image as fallback
    media_contents = getattr(entry, "media_content", []) or entry.get("media_content", [])
    for item in media_contents:
        url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
        if url:
            return url

    # Try thumbnails
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


def _extract_categories(entry: Any) -> List[str]:
    """
    Extracts categories/tags from feedparser entry.

    - В первую очередь читаем entry.tags (обычный случай для <category>).
    - Дополнительно учитываем одиночное поле entry.category, если оно есть.
    - Возвращаем упорядоченный список строк без дубликатов.
    """
    categories: List[str] = []

    # feedparser обычно кладёт <category> в entry.tags
    tags = getattr(entry, "tags", None) or entry.get("tags", None)
    if tags:
        for tag in tags:
            term = None
            if isinstance(tag, dict):
                term = tag.get("term") or tag.get("label")
            else:
                term = getattr(tag, "term", None) or getattr(tag, "label", None)

            if term:
                value = str(term).strip()
                if value and value not in categories:
                    categories.append(value)

    # На всякий случай — одиночное поле category
    single_cat = getattr(entry, "category", None) or entry.get("category", None)
    if single_cat:
        value = str(single_cat).strip()
        if value and value not in categories:
            categories.append(value)

    return categories


def parse_feed(feed: Any, limit: Optional[int] = None) -> List[Post]:
    posts: List[Post] = []

    entries = getattr(feed, "entries", []) or feed.get("entries", [])
    for entry in entries:
        # feedparser entries behave like dict + attributes
        link = getattr(entry, "link", "") or entry.get("link")
        title = (getattr(entry, "title", "") or entry.get("title", "")).strip()
        if not link or not title:
            continue

        published = _parse_datetime(getattr(entry, "published", None) or entry.get("pubDate"))
        summary = getattr(entry, "summary", "") or entry.get("summary", "") or ""
        description = getattr(entry, "description", "") or entry.get("description", "") or ""

        fb_img, ig_img, pin_img = _extract_cards(entry)
        generic_img = _extract_generic_image(entry)
        categories = _extract_categories(entry)

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
            categories=categories,
        )
        posts.append(post)

    # Sort newest first
    posts.sort(key=lambda p: p.published or datetime.min, reverse=True)

    if limit is not None and limit > 0:
        posts = posts[:limit]

    return posts

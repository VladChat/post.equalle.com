# ============================================================
# File: scripts/utils/fb_post_formatter.py
# Purpose:
#   Форматтер для Facebook-постов.
#   Используется в scripts/post_to_facebook.py.
# ============================================================

from __future__ import annotations
import logging
import re
from typing import Dict, List, Optional

# Лимит Facebook подписи (примерно 2000 символов)
FACEBOOK_CAP = 2000
# Максимум хэштегов, чтобы не засорять текст
FACEBOOK_TAG_LIMIT = 8

logger = logging.getLogger("fb_post_formatter")


# ---------------------------
# Вспомогательные функции
# ---------------------------
def _truncate(text: str, limit: int, suffix: str = "") -> str:
    """Обрезает строку до limit символов, добавляя суффикс, если нужно."""
    if len(text) <= limit:
        return text
    cut = limit - len(suffix) if suffix else limit
    truncated = text[:cut] + suffix
    logger.debug("Truncated text from %d to %d", len(text), len(truncated))
    return truncated


def _sanitize_hashtag(raw: str) -> Optional[str]:
    """Очищает тег: убирает #, пробелы и неалфанумерные символы."""
    if not raw:
        return None
    s = raw.strip().lstrip("#").strip()
    if not s:
        return None
    s = re.sub(r"[^\w]", "", s, flags=re.UNICODE)
    return s or None


def _normalize_hashtags(tags: Optional[List[str]], limit: Optional[int] = None) -> str:
    """Создаёт строку из хэштегов (#tag1 #tag2 …)."""
    tags = tags or []
    unique = set()
    result = []
    for t in tags:
        clean = _sanitize_hashtag(t)
        if not clean:
            continue
        low = clean.lower()
        if low in unique:
            continue
        unique.add(low)
        result.append(f"#{clean}")
    if limit:
        result = result[:limit]
    hashtags = " ".join(result)
    logger.debug("Normalized %d hashtags → %s", len(result), hashtags)
    return hashtags


def _parts_join(parts: List[str], sep: str = "\n\n") -> str:
    """Склеивает непустые части текста."""
    return sep.join([p for p in parts if p])


# ---------------------------
# Основная функция форматирования
# ---------------------------
def format_facebook(post: Dict) -> str:
    """
    Формирует подпись для Facebook:
      Title

      Summary

      Read more: <link>

      #tag1 #tag2 ...
    """
    title = (post.get("title") or "").strip()
    summary = (post.get("summary") or "").strip()
    link = (post.get("link") or "").strip()
    hashtags = _normalize_hashtags(post.get("hashtags"), limit=FACEBOOK_TAG_LIMIT)

    caption = _parts_join([title, summary, f"Read more: {link}", hashtags])
    caption = _truncate(caption, FACEBOOK_CAP, suffix="…")
    logger.debug(
        "Facebook caption ready (len=%d, title=%r, tags=%d)",
        len(caption), title[:60], len(hashtags.split()) if hashtags else 0
    )
    return caption

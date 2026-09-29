"""News cleaning layer.

Takes normalized items from serp_service and makes them safe and consistent:
strips HTML, validates required fields, removes duplicates, fills missing fields.
It contains no SERP-specific logic.
"""
import html
import re
from typing import Any
from urllib.parse import urlparse

MAX_TITLE_LENGTH = 300
MAX_SNIPPET_LENGTH = 500
MAX_SOURCE_LENGTH = 100

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def clean_articles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cleaned, valid, de-duplicated articles in their original order."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    cleaned: list[dict[str, Any]] = []

    for item in items or []:
        article = _clean_article(item)
        if article is None:
            continue

        url_key = article["url"].rstrip("/").lower()
        title_key = _NON_ALNUM_RE.sub("", article["title"].lower())
        if url_key in seen_urls or title_key in seen_titles:
            continue

        seen_urls.add(url_key)
        seen_titles.add(title_key)
        cleaned.append(article)

    return cleaned


def _clean_article(item: Any) -> dict[str, Any] | None:
    """Clean one article; return None if it is missing a usable title or URL."""
    if not isinstance(item, dict):
        return None

    title = _clean_text(item.get("title"), MAX_TITLE_LENGTH)
    url = _safe_url(item.get("url"))
    if not title or not url:
        return None

    article_id = item.get("id")
    if not isinstance(article_id, str) or not article_id.strip():
        return None

    return {
        "id": article_id.strip(),
        "title": title,
        "source": _clean_text(item.get("source"), MAX_SOURCE_LENGTH) or "Unknown source",
        "url": url,
        "snippet": _clean_text(item.get("snippet"), MAX_SNIPPET_LENGTH) or "",
        "published_at": _clean_text(item.get("published_at"), MAX_SOURCE_LENGTH) or None,
        "image_url": _safe_url(item.get("image_url")),
    }


def _clean_text(value: Any, max_length: int) -> str:
    """Strip HTML tags/entities, collapse whitespace, and truncate."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def _safe_url(value: Any) -> str | None:
    """Accept only absolute http(s) URLs; anything else becomes None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return value
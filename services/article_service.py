"""Article detail fetching: a full-size image and an excerpt of the article text.

SERP results only carry a short snippet and a small thumbnail. For an article that appeared in a
recent search, this module downloads the publisher's page on the server and extracts:

    {"id": str, "image_url": str | None, "paragraphs": [str, ...], "truncated": bool}

Safety:
  * The browser sends only an article id. The URL comes from a server-side table filled by the
    search route, so callers cannot make the server fetch arbitrary URLs.
  * Every request (and every redirect hop) must resolve to a public IP address: loopback,
    private, link-local and other non-global addresses are refused.
  * Downloads are size- and time-limited and must be HTML.

Only an excerpt (MAX_TEXT_CHARS) is returned; the page links to the original for the full article.
Failures are raised as ArticleError with a user-safe message and HTTP status code.
"""
import copy
import ipaddress
import logging
import re
import socket
import threading
from collections import OrderedDict
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import trafilatura

from config.config import Config

logger = logging.getLogger(__name__)

MAX_REMEMBERED = 500
MAX_CACHED = 200
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
MAX_TEXT_CHARS = 1500
MAX_PARAGRAPHS = 8
MIN_PARAGRAPH_CHARS = 40
_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_REDIRECT_STATUS = (301, 302, 303, 307, 308)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AINewscast/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}

_known: "OrderedDict[str, str]" = OrderedDict()          # article id -> url (from search results)
_cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()  # article id -> extracted details
_lock = threading.Lock()


class ArticleError(Exception):
    """A failure loading article details, safe to show to end users."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def remember_articles(articles: list[dict[str, Any]]) -> None:
    """Record id -> url for cleaned search results so their details can be fetched later."""
    with _lock:
        for article in articles:
            _known[article["id"]] = article["url"]
            _known.move_to_end(article["id"])
        while len(_known) > MAX_REMEMBERED:
            _known.popitem(last=False)


def get_details(article_id: str) -> dict[str, Any]:
    if not isinstance(article_id, str) or not _ID_RE.match(article_id):
        raise ArticleError("Article not found.", 404)
    with _lock:
        cached = _cache.get(article_id)
        if cached is not None:
            return copy.deepcopy(cached)
        url = _known.get(article_id)
    if not url:
        raise ArticleError("Article not found. Please search again.", 404)

    html, final_url = _download(url)
    details = _extract(article_id, html, final_url)

    with _lock:
        _cache[article_id] = copy.deepcopy(details)
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return details


# ---------------------------------------------------------------------------
# Download (with SSRF protection)
# ---------------------------------------------------------------------------

def _assert_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ArticleError("Unable to load that article.", 400)
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise ArticleError("Unable to load that article.", 502)
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            logger.warning("Blocked article fetch to a non-public address")
            raise ArticleError("Unable to load that article.", 400)


def _download(url: str) -> tuple[bytes, str]:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _assert_public(current)
        try:
            response = requests.get(
                current, headers=_HEADERS, timeout=Config.REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False, stream=True,
            )
        except requests.RequestException as exc:
            logger.warning("Article fetch failed: %s", type(exc).__name__)
            raise ArticleError("Unable to load that article.", 502)

        with response:
            if response.status_code in _REDIRECT_STATUS:
                location = response.headers.get("Location")
                if not location:
                    raise ArticleError("Unable to load that article.", 502)
                current = urljoin(current, location)
                continue
            if response.status_code != 200:
                logger.info("Article fetch returned HTTP %s", response.status_code)
                raise ArticleError("Unable to load that article.", 502)
            if "html" not in response.headers.get("Content-Type", "").lower():
                raise ArticleError("Unable to load that article.", 415)

            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break  # the text we need is near the top; ignore the rest
            return b"".join(chunks), current
    raise ArticleError("Unable to load that article.", 502)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _extract(article_id: str, html: bytes, page_url: str) -> dict[str, Any]:
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True)
        metadata = trafilatura.extract_metadata(html)
    except Exception:
        logger.warning("Article extraction failed", exc_info=True)
        raise ArticleError("Unable to read that article.", 502)

    paragraphs, truncated = _excerpt(text or "")
    image_url = _absolute_http_url(getattr(metadata, "image", None), page_url)
    if not paragraphs and not image_url:
        raise ArticleError("No more details are available for this article.", 404)
    return {"id": article_id, "image_url": image_url, "paragraphs": paragraphs, "truncated": truncated}


def _excerpt(text: str) -> tuple[list[str], bool]:
    paragraphs: list[str] = []
    used = 0
    for raw in text.split("\n"):
        paragraph = " ".join(raw.split())
        if len(paragraph) < MIN_PARAGRAPH_CHARS:
            continue  # skip captions, bylines and menu leftovers
        room = MAX_TEXT_CHARS - used
        if room <= 0 or len(paragraphs) >= MAX_PARAGRAPHS:
            return paragraphs, True
        if len(paragraph) > room:
            cut = paragraph[:room]
            cut = cut[: cut.rfind(" ")] if " " in cut else cut
            paragraphs.append(cut.rstrip(" ,;:") + "\u2026")
            return paragraphs, True
        paragraphs.append(paragraph)
        used += len(paragraph)
    return paragraphs, False


def _absolute_http_url(value: Any, base: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(base, value.strip())
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else None

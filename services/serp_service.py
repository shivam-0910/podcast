"""SERP API communication (SerpApi, Google News results).

This module is the ONLY place that knows SERP's raw response format.
It returns news items in the app's own normalized structure:

    {
        "id": str, "title": str, "source": str | None, "url": str,
        "snippet": str | None, "published_at": str | None, "image_url": str | None
    }

Failures are raised as SerpError carrying a user-safe message and an HTTP
status code. Raw exceptions, URLs and API keys are never included in it.
"""
import hashlib
import logging
from typing import Any

import requests

from config.config import Config

logger = logging.getLogger(__name__)

SERP_ENDPOINT = "https://serpapi.com/search.json"


class SerpError(Exception):
    """A failure talking to the SERP API, safe to show to end users."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def search_news(query: str) -> list[dict[str, Any]]:
    """Search current news for `query` and return normalized items."""
    payload = _request_news(query)
    return _extract_items(payload)


def _request_news(query: str) -> dict[str, Any]:
    """Call SERP API and return the decoded JSON payload."""
    if not Config.SERP_API_KEY:
        logger.error("SERP_API_KEY is not configured")
        raise SerpError("News search is not configured yet.", 503)

    params = {
        "engine": "google",
        "tbm": "nws",
        "q": query,
        "num": 10,
        "api_key": Config.SERP_API_KEY,
    }

    try:
        response = requests.get(
            SERP_ENDPOINT, params=params, timeout=Config.REQUEST_TIMEOUT_SECONDS
        )
    except requests.Timeout:
        logger.warning("SERP request timed out")
        raise SerpError("The news service took too long to respond.", 504)
    except requests.RequestException as exc:
        # Log only the exception type: its message can contain the full URL (with the API key).
        logger.warning("SERP network error: %s", type(exc).__name__)
        raise SerpError("Unable to reach the news service.", 502)

    if response.status_code in (401, 403):
        logger.error("SERP API rejected the API key (HTTP %s)", response.status_code)
        raise SerpError("Unable to search for news right now.", 502)
    if response.status_code == 429:
        logger.warning("SERP API rate limit hit")
        raise SerpError("Too many searches right now. Please try again shortly.", 429)
    if response.status_code != 200:
        logger.warning("SERP API returned HTTP %s", response.status_code)
        raise SerpError("Unable to search for news right now.", 502)

    try:
        payload = response.json()
    except ValueError:
        logger.warning("SERP API returned invalid JSON")
        raise SerpError("The news service returned an unexpected response.", 502)

    if not isinstance(payload, dict):
        logger.warning("SERP API payload was not a JSON object")
        raise SerpError("The news service returned an unexpected response.", 502)

    _raise_for_payload_error(payload)
    return payload


def _raise_for_payload_error(payload: dict[str, Any]) -> None:
    """SerpApi can report problems inside a 200 response via an 'error' field."""
    error = payload.get("error")
    if not error:
        return

    text = str(error).lower()
    if "hasn't returned any results" in text or "no results" in text:
        return  # empty result, not a failure
    if "run out of searches" in text or "limit" in text:
        logger.warning("SERP API quota/limit error")
        raise SerpError("Too many searches right now. Please try again shortly.", 429)
    if "api key" in text:
        logger.error("SERP API reported an API key problem")
        raise SerpError("Unable to search for news right now.", 502)

    logger.warning("SERP API returned an error in the payload")
    raise SerpError("Unable to search for news right now.", 502)


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull news results out of the payload and normalize each one."""
    raw_results = payload.get("news_results")
    if raw_results is None:
        return []
    if not isinstance(raw_results, list):
        logger.warning("SERP 'news_results' was not a list")
        raise SerpError("The news service returned an unexpected response.", 502)

    items = []
    for raw in raw_results:
        if isinstance(raw, dict):
            items.append(_normalize_item(raw))
    return items


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one raw SERP result to the app's internal news structure."""
    url = raw.get("link")
    source = raw.get("source")
    if isinstance(source, dict):  # some SERP engines return {"name": "..."}
        source = source.get("name")

    return {
        "id": _make_id(url, raw.get("title")),
        "title": raw.get("title"),
        "source": source,
        "url": url,
        "snippet": raw.get("snippet"),
        "published_at": raw.get("date") or raw.get("iso_date"),
        "image_url": raw.get("thumbnail"),
    }


def _make_id(url: Any, title: Any) -> str:
    """Stable short id derived from the article URL (or title as a fallback)."""
    basis = str(url or title or "")
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
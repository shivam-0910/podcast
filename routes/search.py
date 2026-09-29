"""News search endpoint: GET /api/search?q=<topic>"""
import logging

from flask import Blueprint, jsonify, request

from services.news_service import clean_articles
from services.serp_service import SerpError, search_news

logger = logging.getLogger(__name__)

search_bp = Blueprint("search", __name__)

MAX_QUERY_LENGTH = 200


@search_bp.get("/api/search")
def search():
    query = request.args.get("q")
    if query is None:
        return _error("Please enter a topic to search for.", 400)

    query = " ".join(query.split())  # trim and collapse whitespace/control chars
    if not query:
        return _error("Please enter a topic to search for.", 400)
    if len(query) > MAX_QUERY_LENGTH:
        return _error(f"Topic is too long (max {MAX_QUERY_LENGTH} characters).", 400)

    try:
        raw_items = search_news(query)
        articles = clean_articles(raw_items)
    except SerpError as exc:
        return _error(exc.message, exc.status_code)
    except Exception:
        logger.exception("Unexpected error during news search")
        return _error("Unable to search for news right now. Please try again.", 500)

    return jsonify({"query": query, "count": len(articles), "results": articles})


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code
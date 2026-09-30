"""Article details endpoint: GET /api/article/<article_id>

Returns {id, image_url, paragraphs, truncated} for an article from a recent search.
The id is the one returned by /api/search; the server looks the URL up itself.
"""
from flask import Blueprint, jsonify

from services.article_service import ArticleError, get_details

article_bp = Blueprint("article", __name__)


@article_bp.get("/api/article/<article_id>")
def details(article_id: str):
    try:
        return jsonify(get_details(article_id))
    except ArticleError as exc:
        return jsonify({"error": exc.message}), exc.status_code

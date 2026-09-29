"""News results page: GET /news?q=<topic>

Serves the page shell only. The page's JavaScript (static/js/news.js)
fetches the actual results from /api/search.
"""
from flask import Blueprint, render_template

news_bp = Blueprint("news", __name__)


@news_bp.get("/news")
def news_page():
    return render_template("news.html")
"""Episode routes.

    POST /api/episode/create    generate an episode from selected articles
    GET  /api/episode/<id>      load a previously created episode
    GET  /conversation?id=<id>  the conversation screen (page shell; player.js loads the episode)

Create request JSON:
    {"articles": [{id, title, source, url, snippet, published_at, image_url}, ...],
     "language": "en", "topic": "optional search topic"}

The server does not store search results, so the browser sends the selected articles' data.
It is re-validated with news_service.clean_articles before use.
"""
import logging

from flask import Blueprint, jsonify, render_template, request

from config.config import Config
from services.conversation_service import ConversationError
from services.episode_service import create_episode, get_episode
from services.news_service import clean_articles

logger = logging.getLogger(__name__)

episode_bp = Blueprint("episode", __name__)

ARTICLE_FIELDS = ("id", "title", "source", "url", "snippet", "published_at", "image_url")
MAX_TOPIC_LENGTH = 200


@episode_bp.get("/conversation")
def conversation_page():
    return render_template("conversation.html", languages=Config.SUPPORTED_LANGUAGES)


@episode_bp.post("/api/episode/create")
def create():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Invalid request.", 400)

    raw_articles = body.get("articles")
    if not isinstance(raw_articles, list) or not raw_articles:
        return _error("Select at least one article.", 400)
    if len(raw_articles) > Config.MAX_ARTICLES_PER_EPISODE:
        return _error(f"You can select up to {Config.MAX_ARTICLES_PER_EPISODE} articles.", 400)

    language = body.get("language", Config.DEFAULT_LANGUAGE)
    if not isinstance(language, str) or language not in Config.SUPPORTED_LANGUAGES:
        return _error("That language is not supported.", 400)

    topic = body.get("topic", "")
    topic = " ".join(topic.split())[:MAX_TOPIC_LENGTH] if isinstance(topic, str) else ""

    # Keep only known fields, then clean/validate/de-duplicate like search results.
    picked = [
        {field: item.get(field) for field in ARTICLE_FIELDS}
        for item in raw_articles
        if isinstance(item, dict)
    ]
    articles = clean_articles(picked)
    if not articles:
        return _error("The selected articles are not valid. Please search again.", 400)

    try:
        episode = create_episode(articles, language, topic)
    except ConversationError as exc:
        return _error(exc.message, exc.status_code)
    except Exception:
        logger.exception("Unexpected error creating episode")
        return _error("Unable to create the podcast right now. Please try again.", 500)

    return jsonify(episode)


@episode_bp.get("/api/episode/<episode_id>")
def fetch(episode_id: str):
    episode = get_episode(episode_id)
    if episode is None:
        return _error("Episode not found. It may have expired, so please create it again.", 404)
    return jsonify(episode)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code

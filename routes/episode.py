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

from flask import Blueprint, Response, jsonify, render_template, request

from config.config import Config
from services.article_service import add_article_text
from services.conversation_service import ConversationError
from services.episode_service import create_episode, get_episode, update_episode_voices
from services.news_service import clean_articles
from services import tts_service
from services.tts_service import TTSError

logger = logging.getLogger(__name__)

episode_bp = Blueprint("episode", __name__)

ARTICLE_FIELDS = ("id", "title", "source", "url", "snippet", "published_at", "image_url")
MAX_TOPIC_LENGTH = 200
VOICE_SAMPLE_TEXT = {
    "en": "Hello, welcome to your AI news podcast.",
    "hi": "नमस्कार, आपके एआई समाचार पॉडकास्ट में आपका स्वागत है।",
    "bn": "নমস্কার, আপনার এআই সংবাদ পডকাস্টে স্বাগতম।",
    "te": "నమస్కారం, మీ ఏఐ వార్తల పోడ్‌కాస్ట్‌కు స్వాగతం.",
    "ta": "வணக்கம், உங்கள் ஏஐ செய்தி பாட்காஸ்டுக்கு வரவேற்கிறோம்.",
}


@episode_bp.get("/conversation")
def conversation_page():
    try:
        voice_options = tts_service.voice_options_by_language()
    except TTSError:
        voice_options = {}
    return render_template(
        "conversation.html",
        languages=Config.SUPPORTED_LANGUAGES,
        voice_options=voice_options,
    )


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

    voices = body.get("voices")
    if voices is not None:
        if not isinstance(voices, dict) or any(
            not isinstance(voices.get(speaker), str) or not voices[speaker].strip()
            for speaker in ("host_a", "host_b")
        ):
            return _error("Choose a voice for both hosts.", 400)
        voices = {speaker: voices[speaker].strip() for speaker in ("host_a", "host_b")}

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

    articles = add_article_text(articles)  # adds a longer "text" excerpt where the page can be read

    try:
        episode = create_episode(articles, language, topic, voices)
    except (ConversationError, TTSError) as exc:
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


@episode_bp.get("/api/tts/sample")
def voice_sample():
    language = request.args.get("language", "")
    speaker = request.args.get("speaker", "")
    voice_id = request.args.get("voice_id", "").strip()
    if language not in VOICE_SAMPLE_TEXT or speaker not in ("host_a", "host_b") or not voice_id:
        return _error("That voice sample request is invalid.", 400)

    try:
        result = tts_service.generate_speech(VOICE_SAMPLE_TEXT[language], speaker, language, voice_id)
    except TTSError as exc:
        return _error(exc.message, exc.status_code)
    return Response(
        result.audio,
        mimetype=result.mime_type,
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )


@episode_bp.post("/api/episode/<episode_id>/voices")
def update_voices(episode_id: str):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Choose a voice for both hosts.", 400)
    voices = body.get("voices")
    if not isinstance(voices, dict) or any(
        not isinstance(voices.get(speaker), str) or not voices[speaker].strip()
        for speaker in ("host_a", "host_b")
    ):
        return _error("Choose a voice for both hosts.", 400)

    try:
        episode = update_episode_voices(
            episode_id,
            {speaker: voices[speaker].strip() for speaker in ("host_a", "host_b")},
        )
    except TTSError as exc:
        return _error(exc.message, exc.status_code)
    if episode is None:
        return _error("Episode not found. Please create it again.", 404)
    return jsonify(episode)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code

"""News results page: GET /news?q=<topic>

Serves the page shell only. The page's JavaScript (static/js/news.js)
fetches the actual results from /api/search.

The page also renders the language selector. Every language in Config.SUPPORTED_LANGUAGES is
listed; the ones the current TTS provider cannot speak are shown disabled ("coming soon").
"""
import logging

from flask import Blueprint, render_template

from config.config import Config
from services import tts_service
from services.tts_service import TTSError

logger = logging.getLogger(__name__)

news_bp = Blueprint("news", __name__)


@news_bp.get("/news")
def news_page():
    languages, default_language = _language_options()
    return render_template("news.html", languages=languages, default_language=default_language)


def _language_options() -> tuple[list[dict], str]:
    """Return ([{code, name, available}, ...], default_code) for the language <select>."""
    try:
        available = set(tts_service.supported_languages())
    except TTSError:
        # Provider misconfigured: don't lock the user out of the page. Creating an episode will
        # report the real problem with a clear message.
        logger.warning("Could not read the TTS provider's languages; showing all languages")
        available = set(Config.SUPPORTED_LANGUAGES)

    options = [
        {"code": code, "name": name, "available": code in available}
        for code, name in Config.SUPPORTED_LANGUAGES.items()
    ]

    default = Config.DEFAULT_LANGUAGE
    if default not in available:
        default = next((o["code"] for o in options if o["available"]), Config.DEFAULT_LANGUAGE)
    return options, default

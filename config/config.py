"""Central application configuration.

All environment-variable access lives here so the rest of the app
imports settings from one place.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Secrets / API keys (never sent to the frontend)
    SERP_API_KEY: str = os.getenv("SERP_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "") or "dev-only-insecure-key"

    # Paths
    DATABASE_PATH: Path = BASE_DIR / "data" / "podcast.db"
    AUDIO_DIR: Path = BASE_DIR / "audio"

    # Supported languages: code -> display name
    SUPPORTED_LANGUAGES: dict = {
        "en": "English",
        "hi": "Hindi",
        "or": "Odia",
        "bn": "Bengali",
        "te": "Telugu",
        "ta": "Tamil",
    }
    DEFAULT_LANGUAGE: str = "en"

    # Groq (conversation generation). The model can be overridden with the optional GROQ_MODEL env var.
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    GROQ_TIMEOUT_SECONDS: int = 60
    MAX_ARTICLES_PER_EPISODE: int = 5

    # Text-to-speech. TTS_PROVIDER selects a provider registered in services/tts_service.py.
    # "offline" uses installed Windows SAPI voices; "edge" uses Microsoft's online voices.
    _DEFAULT_TTS_PROVIDER: str = "offline" if os.name == "nt" else "edge"
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", _DEFAULT_TTS_PROVIDER).strip().lower() or _DEFAULT_TTS_PROVIDER
    TTS_MAX_WORKERS: int = 1  # serialize TTS requests for Windows SAPI and Edge stability
    EDGE_TTS_PROXY: str = os.getenv("EDGE_TTS_PROXY", "").strip()

    # App settings
    HOST: str = "127.0.0.1"
    PORT: int = 5000
    DEBUG: bool = os.getenv("FLASK_DEBUG", "1") == "1"
    REQUEST_TIMEOUT_SECONDS: int = 15

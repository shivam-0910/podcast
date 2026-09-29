"""Episode coordination.

Coordinates:  selected articles -> conversation generation -> TTS per line -> episode object.
It contains no SERP, Groq or TTS vendor details: it calls conversation_service and tts_service.

Audio is stored as one file per conversation line, never one big file:

    audio/<episode_id>/001_host_a.<ext>
    audio/<episode_id>/002_host_b.<ext>
    ...

and each segment's "audio_url" points at routes/audio.py (/audio/<episode_id>/<file>).
The file extension comes from the TTS provider (the mock provider produces .wav).

Episodes are kept in a small in-memory store so the conversation screen can load them by id.
This is temporary: Step 14 replaces it with SQLite persistence (episodes survive restarts).
When an episode is evicted from the store its audio folder is deleted, so disk use stays bounded.
"""
import copy
import logging
import os
import re
import shutil
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from config.config import Config
from services import tts_service
from services.conversation_service import generate_conversation
from services.tts_service import TTSError

logger = logging.getLogger(__name__)

MAX_STORED_EPISODES = 100
_EPISODE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_RETRYABLE_TTS_STATUS = (502, 504)

_store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_store_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_episode(articles: list[dict[str, Any]], language: str, topic: str = "") -> dict[str, Any]:
    """Generate the conversation, turn every line into an audio file, and remember the episode."""
    # Fail fast (before the Groq call) if the voice provider can't speak this language.
    tts_service.ensure_language_supported(language)

    generated = generate_conversation(articles, language)
    episode_id = uuid.uuid4().hex

    try:
        segments = _build_segments(episode_id, generated["conversation"], language)
    except BaseException:
        _delete_audio(episode_id)  # never leave a half-built episode on disk
        raise

    episode = {
        "episode_id": episode_id,
        "title": generated["episode_title"],
        "topic": topic,
        "language": language,
        "conversation": segments,
    }
    _remember(episode)
    return copy.deepcopy(episode)


def get_episode(episode_id: str) -> dict[str, Any] | None:
    """Return a stored episode, or None if the id is malformed, unknown or expired."""
    if not isinstance(episode_id, str) or not _EPISODE_ID_RE.match(episode_id):
        return None
    with _store_lock:
        episode = _store.get(episode_id)
        return copy.deepcopy(episode) if episode else None


# ---------------------------------------------------------------------------
# Audio segments
# ---------------------------------------------------------------------------

def _audio_dir(episode_id: str) -> Path:
    return Path(Config.AUDIO_DIR) / episode_id


def _build_segments(episode_id: str, turns: list[dict[str, str]], language: str) -> list[dict[str, Any]]:
    """Generate all segment audio files (in parallel) and return segments in conversation order."""
    try:
        _audio_dir(episode_id).mkdir(parents=True, exist_ok=False)
    except OSError:
        logger.exception("Could not create the audio folder")
        raise TTSError("Unable to save the audio right now. Please try again.", 500)

    def render(item: tuple[int, dict[str, str]]) -> dict[str, Any]:
        index, turn = item
        return _render_segment(episode_id, index, turn, language)

    with ThreadPoolExecutor(max_workers=max(1, Config.TTS_MAX_WORKERS)) as pool:
        return list(pool.map(render, enumerate(turns, start=1)))  # keeps conversation order


def _render_segment(episode_id: str, index: int, turn: dict[str, str], language: str) -> dict[str, Any]:
    result = _speech_with_retry(turn["text"], turn["speaker"], language)
    filename = f"{index:03d}_{turn['speaker']}.{result.extension}"

    try:
        _write_atomic(_audio_dir(episode_id) / filename, result.audio)
    except OSError:
        logger.exception("Could not write an audio segment")
        raise TTSError("Unable to save the audio right now. Please try again.", 500)

    return {
        "id": index,
        "speaker": turn["speaker"],
        "text": turn["text"],
        "audio_url": f"/audio/{episode_id}/{filename}",
    }


def _speech_with_retry(text: str, speaker: str, language: str):
    """One retry for transient provider failures (502/504); other errors are final."""
    try:
        return tts_service.generate_speech(text, speaker, language)
    except TTSError as exc:
        if exc.status_code not in _RETRYABLE_TTS_STATUS:
            raise
        logger.info("Retrying TTS after a transient failure")
        return tts_service.generate_speech(text, speaker, language)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file + rename so readers never see a half-written audio file."""
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "wb") as handle:
        handle.write(data)
    os.replace(temp, path)


def _delete_audio(episode_id: str) -> None:
    if _EPISODE_ID_RE.match(episode_id):
        shutil.rmtree(_audio_dir(episode_id), ignore_errors=True)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

def _remember(episode: dict[str, Any]) -> None:
    evicted: list[str] = []
    with _store_lock:
        _store[episode["episode_id"]] = copy.deepcopy(episode)
        while len(_store) > MAX_STORED_EPISODES:
            old_id, _ = _store.popitem(last=False)  # drop the oldest
            evicted.append(old_id)
    for old_id in evicted:
        _delete_audio(old_id)

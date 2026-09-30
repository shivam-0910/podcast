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
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
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


def init_storage() -> None:
    """Create the SQLite backing store and restore any previously saved episodes into memory."""
    db_path = Path(Config.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                episode_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    _load_persisted_episodes()


def _db_path() -> Path:
    return Path(Config.DATABASE_PATH)


def _load_persisted_episodes() -> None:
    db_path = _db_path()
    if not db_path.exists():
        return

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT episode_id, payload FROM episodes ORDER BY created_at DESC"
        ).fetchall()

    for episode_id, payload in rows:
        try:
            episode = json.loads(payload)
        except (TypeError, ValueError):
            logger.warning("Ignoring malformed persisted episode: %s", episode_id)
            continue
        if not isinstance(episode, dict):
            continue
        episode_id = str(episode.get("episode_id") or episode_id)
        if not _EPISODE_ID_RE.match(episode_id):
            continue
        with _store_lock:
            _store[episode_id] = copy.deepcopy(episode)


def _persist_episode(episode: dict[str, Any]) -> None:
    if not isinstance(episode, dict) or not episode.get("episode_id"):
        return

    try:
        with sqlite3.connect(_db_path()) as conn:
            conn.execute(
                """
                INSERT INTO episodes (episode_id, payload)
                VALUES (?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET payload = excluded.payload
                """,
                (episode["episode_id"], json.dumps(episode, ensure_ascii=False, separators=(",", ":"))),
            )
            conn.commit()
    except sqlite3.Error:
        logger.exception("Could not persist episode %s", episode.get("episode_id"))


def _delete_persisted_episode(episode_id: str) -> None:
    if not isinstance(episode_id, str) or not _EPISODE_ID_RE.match(episode_id):
        return
    try:
        with sqlite3.connect(_db_path()) as conn:
            conn.execute("DELETE FROM episodes WHERE episode_id = ?", (episode_id,))
            conn.commit()
    except sqlite3.Error:
        logger.exception("Could not delete persisted episode %s", episode_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_episode(
    articles: list[dict[str, Any]],
    language: str,
    topic: str = "",
    voices: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate the conversation, turn every line into an audio file, and remember the episode."""
    # Fail fast (before the Groq call) if the voice provider can't speak this language.
    provider = tts_service.ensure_language_supported(language)
    selected_voices = {
        speaker: provider.voice_for(speaker, language, voices.get(speaker) if voices else None)
        for speaker in ("host_a", "host_b")
    }

    generated = generate_conversation(articles, language)
    episode_id = uuid.uuid4().hex

    try:
        segments = _build_segments(episode_id, generated["conversation"], language, selected_voices)
    except BaseException:
        _delete_audio(episode_id)  # never leave a half-built episode on disk
        raise

    episode = {
        "episode_id": episode_id,
        "title": generated["episode_title"],
        "topic": topic,
        "language": language,
        "voices": selected_voices,
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
        if episode is not None:
            return copy.deepcopy(episode)

    persisted = _fetch_persisted_episode(episode_id)
    if persisted is not None:
        _remember(persisted)
        return copy.deepcopy(persisted)
    return None


def _fetch_persisted_episode(episode_id: str) -> dict[str, Any] | None:
    db_path = _db_path()
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
    except sqlite3.Error:
        logger.exception("Could not load persisted episode %s", episode_id)
        return None

    if row is None:
        return None
    try:
        episode = json.loads(row[0])
    except (TypeError, ValueError):
        logger.warning("Persisted episode %s was malformed and was ignored.", episode_id)
        return None
    if isinstance(episode, dict):
        return episode
    return None


def update_episode_voices(episode_id: str, voices: dict[str, str]) -> dict[str, Any] | None:
    """Regenerate an episode's audio with new voices, keeping old files until all succeed."""
    episode = get_episode(episode_id)
    if episode is None:
        return None

    language = episode["language"]
    provider = tts_service.ensure_language_supported(language)
    selected_voices = {
        speaker: provider.voice_for(speaker, language, voices[speaker])
        for speaker in ("host_a", "host_b")
    }
    audio_dir = _audio_dir(episode_id)
    if not audio_dir.is_dir():
        raise TTSError("Episode audio is no longer available. Please create the podcast again.", 404)

    staging_dir = audio_dir / (".voice-update-" + uuid.uuid4().hex)
    cache_version = uuid.uuid4().hex
    try:
        staging_dir.mkdir()

        def render(item: tuple[int, dict[str, Any]]) -> dict[str, Any]:
            index, segment = item
            result = _speech_with_retry(
                segment["text"], segment["speaker"], language, selected_voices[segment["speaker"]]
            )
            filename = f"{index:03d}_{segment['speaker']}.{result.extension}"
            _write_atomic(staging_dir / filename, result.audio)
            return {
                "id": segment["id"],
                "speaker": segment["speaker"],
                "text": segment["text"],
                "audio_url": f"/audio/{episode_id}/{filename}?v={cache_version}",
            }

        with ThreadPoolExecutor(max_workers=max(1, Config.TTS_MAX_WORKERS)) as pool:
            segments = list(pool.map(render, enumerate(episode["conversation"], start=1)))

        for segment in segments:
            filename = segment["audio_url"].split("?", 1)[0].rsplit("/", 1)[-1]
            os.replace(staging_dir / filename, audio_dir / filename)

        new_files = {
            segment["audio_url"].split("?", 1)[0].rsplit("/", 1)[-1]
            for segment in segments
        }
        for old_segment in episode["conversation"]:
            old_filename = old_segment["audio_url"].split("?", 1)[0].rsplit("/", 1)[-1]
            if old_filename not in new_files:
                (audio_dir / old_filename).unlink(missing_ok=True)
    except TTSError:
        raise
    except OSError:
        logger.exception("Could not replace episode audio")
        raise TTSError("Unable to update episode audio right now. Please try again.", 500) from None
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    episode["voices"] = selected_voices
    episode["conversation"] = segments
    _remember(episode)
    return copy.deepcopy(episode)


# ---------------------------------------------------------------------------
# Audio segments
# ---------------------------------------------------------------------------

def _audio_dir(episode_id: str) -> Path:
    return Path(Config.AUDIO_DIR) / episode_id


def _build_segments(
    episode_id: str,
    turns: list[dict[str, str]],
    language: str,
    voices: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Generate all segment audio files (in parallel) and return segments in conversation order."""
    try:
        _audio_dir(episode_id).mkdir(parents=True, exist_ok=False)
    except OSError:
        logger.exception("Could not create the audio folder")
        raise TTSError("Unable to save the audio right now. Please try again.", 500)

    def render(item: tuple[int, dict[str, str]]) -> dict[str, Any]:
        index, turn = item
        return _render_segment(episode_id, index, turn, language, voices)

    with ThreadPoolExecutor(max_workers=max(1, Config.TTS_MAX_WORKERS)) as pool:
        return list(pool.map(render, enumerate(turns, start=1)))  # keeps conversation order


def _render_segment(
    episode_id: str,
    index: int,
    turn: dict[str, str],
    language: str,
    voices: dict[str, str] | None = None,
) -> dict[str, Any]:
    voice_id = voices.get(turn["speaker"]) if voices else None
    result = _speech_with_retry(turn["text"], turn["speaker"], language, voice_id)
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


def _speech_with_retry(text: str, speaker: str, language: str, voice_id: str | None = None):
    """One retry for transient provider failures (502/504); other errors are final."""
    def generate():
        if voice_id is None:
            return tts_service.generate_speech(text, speaker, language)
        return tts_service.generate_speech(text, speaker, language, voice_id)

    try:
        return generate()
    except TTSError as exc:
        if exc.status_code not in _RETRYABLE_TTS_STATUS:
            raise
        logger.info("Retrying TTS after a transient failure in 1 second")
        time.sleep(1)
        return generate()


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
    _persist_episode(episode)
    for old_id in evicted:
        _delete_audio(old_id)
        _delete_persisted_episode(old_id)


init_storage()

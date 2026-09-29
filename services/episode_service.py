"""Episode coordination.

Coordinates: selected articles -> conversation generation -> episode object.
It contains no SERP, Groq or TTS implementation details. TTS/audio is added in Steps 9-10,
so for now every segment has "audio_url": None.

Episodes are kept in a small in-memory store so the conversation screen can load them by id.
This is temporary: Step 14 replaces it with SQLite persistence (episodes survive restarts).
"""
import copy
import re
import threading
import uuid
from collections import OrderedDict
from typing import Any

from services.conversation_service import generate_conversation

MAX_STORED_EPISODES = 100
_EPISODE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_store_lock = threading.Lock()


def create_episode(articles: list[dict[str, Any]], language: str, topic: str = "") -> dict[str, Any]:
    """Build an episode dict for the given (already cleaned) articles and remember it."""
    generated = generate_conversation(articles, language)

    segments = [
        {"id": index, "speaker": turn["speaker"], "text": turn["text"], "audio_url": None}
        for index, turn in enumerate(generated["conversation"], start=1)
    ]

    episode = {
        "episode_id": uuid.uuid4().hex,
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


def _remember(episode: dict[str, Any]) -> None:
    with _store_lock:
        _store[episode["episode_id"]] = copy.deepcopy(episode)
        while len(_store) > MAX_STORED_EPISODES:
            _store.popitem(last=False)  # drop the oldest

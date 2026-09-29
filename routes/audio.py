"""Audio endpoint: GET /audio/<episode_id>/<filename>

Serves the per-line audio segments written by episode_service. Both path parts are strictly
validated, so only files that match  <32 hex chars>/<NNN>_host_a|host_b.<ext>  can be requested
(no path traversal, no directory listing). Range requests are supported so browsers can seek.
"""
import re
from pathlib import Path

from flask import Blueprint, jsonify, send_from_directory
from werkzeug.exceptions import NotFound

from config.config import Config

audio_bp = Blueprint("audio", __name__)

_EPISODE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FILENAME_RE = re.compile(r"^\d{3,4}_host_[ab]\.[a-z0-9]{1,5}$")


@audio_bp.get("/audio/<episode_id>/<filename>")
def serve_segment(episode_id: str, filename: str):
    if not _EPISODE_ID_RE.match(episode_id) or not _FILENAME_RE.match(filename):
        return _not_found()

    directory = Path(Config.AUDIO_DIR) / episode_id
    try:
        return send_from_directory(directory, filename, conditional=True, max_age=3600)
    except NotFound:
        return _not_found()


def _not_found():
    return jsonify({"error": "Audio not found."}), 404

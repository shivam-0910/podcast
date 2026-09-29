"""Text-to-speech abstraction.

The rest of the app only calls:

    generate_speech(text, speaker, language) -> SpeechResult

and never touches a TTS vendor directly. Vendors live behind the small TTSProvider interface and
are registered by name in PROVIDERS; Config.TTS_PROVIDER picks which one is used (default: "edge").

Speakers map to voices per provider:  host_a -> voice A,  host_b -> voice B.

To add a real vendor later:
    1. subclass TTSProvider (set `name`, `voices`, `supported_languages`, implement `synthesize`)
    2. add it to PROVIDERS
    3. set TTS_PROVIDER=<name> and any provider-specific configuration in .env
Nothing else in the app needs to change.

Failures are raised as TTSError with a user-safe message and HTTP status code.
Raw provider errors and API keys are never exposed to callers.
"""
import asyncio
import io
import logging
import math
import wave
from abc import ABC, abstractmethod
from array import array
from dataclasses import dataclass
from typing import Any
import edge_tts

from config.config import Config

logger = logging.getLogger(__name__)

SPEAKERS = ("host_a", "host_b")
MAX_TEXT_LENGTH = 2000


class TTSError(Exception):
    """A failure generating speech, safe to show to end users."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SpeechResult:
    """Audio for one conversation segment. `extension` has no dot (e.g. "mp3", "wav")."""

    audio: bytes
    mime_type: str
    extension: str


class TTSProvider(ABC):
    """Interface every TTS vendor implements."""

    name: str = ""
    voices: dict[str, str] = {}                 # speaker -> vendor voice id
    supported_languages: frozenset[str] = frozenset()

    def voice_for(self, speaker: str, language: str | None = None) -> str:
        return self.voices[speaker]

    @abstractmethod
    def synthesize(self, text: str, voice: str, language: str) -> SpeechResult:
        """Return audio for `text`. May raise TTSError; any other exception is wrapped by the caller."""


# ---------------------------------------------------------------------------
# Mock provider (placeholder so the app is testable without a real TTS vendor)
# ---------------------------------------------------------------------------

class MockTTSProvider(TTSProvider):
    """Generates a soft, pulsing tone as a WAV file. It does NOT speak the words.

    Each host has its own pitch and duration follows the text length, so sequential playback,
    progress and transcript sync can be tested. Needs no API key or network.
    """

    name = "mock"
    voices = {"host_a": "mock-voice-a", "host_b": "mock-voice-b"}
    supported_languages = frozenset(Config.SUPPORTED_LANGUAGES)

    _PITCH_HZ = {"mock-voice-a": 220.0, "mock-voice-b": 140.0}
    _SAMPLE_RATE = 16000
    _CHARS_PER_SECOND = 15.0
    _MIN_SECONDS = 0.6
    _MAX_SECONDS = 30.0

    def synthesize(self, text: str, voice: str, language: str) -> SpeechResult:
        pitch = self._PITCH_HZ[voice]
        seconds = min(max(len(text) / self._CHARS_PER_SECOND, self._MIN_SECONDS), self._MAX_SECONDS)
        total = int(self._SAMPLE_RATE * seconds)
        fade = int(self._SAMPLE_RATE * 0.03)
        two_pi = 2.0 * math.pi

        samples = array("h")
        for n in range(total):
            t = n / self._SAMPLE_RATE
            tone = math.sin(two_pi * pitch * t) + 0.4 * math.sin(two_pi * 2 * pitch * t)
            pulse = 0.55 + 0.45 * math.sin(two_pi * 4.0 * t)          # ~4 "syllables" per second
            edge = min(1.0, n / fade, (total - 1 - n) / fade)         # fade in/out to avoid clicks
            samples.append(int(9000 * tone * pulse * max(edge, 0.0)))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._SAMPLE_RATE)
            wav.writeframes(samples.tobytes() if _LITTLE_ENDIAN else _swapped(samples))
        return SpeechResult(audio=buffer.getvalue(), mime_type="audio/wav", extension="wav")


class EdgeTTSProvider(TTSProvider):
    """Generates speech with Microsoft Edge's online neural voices via edge-tts."""

    name = "edge"
    voices = {
        "host_a": "en-US-AndrewMultilingualNeural",
        "host_b": "en-US-EmmaMultilingualNeural",
    }
    _LANGUAGE_VOICES = {
        "en": voices,
        "hi": {"host_a": "hi-IN-MadhurNeural", "host_b": "hi-IN-SwaraNeural"},
        "bn": {"host_a": "bn-IN-BashkarNeural", "host_b": "bn-IN-TanishaaNeural"},
        "te": {"host_a": "te-IN-MohanNeural", "host_b": "te-IN-ShrutiNeural"},
        "ta": {"host_a": "ta-IN-ValluvarNeural", "host_b": "ta-IN-PallaviNeural"},
    }
    supported_languages = frozenset(_LANGUAGE_VOICES)
    _TIMEOUT_SECONDS = 60

    def voice_for(self, speaker: str, language: str | None = None) -> str:
        if language is None:
            return self.voices[speaker]
        return self._LANGUAGE_VOICES[language][speaker]

    def synthesize(self, text: str, voice: str, language: str) -> SpeechResult:
        async def collect_audio() -> bytes:
            chunks = []
            async for chunk in edge_tts.Communicate(text, voice).stream():
                if chunk["type"] == "audio":
                    data = chunk.get("data")
                    if isinstance(data, bytes):
                        chunks.append(data)
            return b"".join(chunks)

        try:
            audio = asyncio.run(asyncio.wait_for(collect_audio(), timeout=self._TIMEOUT_SECONDS))
        except asyncio.TimeoutError:
            raise TTSError("Voice generation took too long. Please try again.", 504) from None
        except Exception as exc:
            logger.warning("Edge TTS request failed: %s", type(exc).__name__)
            raise TTSError("Unable to generate voice audio right now. Please try again.", 502) from None
        return SpeechResult(audio=audio, mime_type="audio/mpeg", extension="mp3")


_LITTLE_ENDIAN = array("h", [1]).tobytes()[0] == 1


def _swapped(samples: array) -> bytes:
    out = array("h", samples)
    out.byteswap()
    return out.tobytes()


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, type[TTSProvider]] = {
    MockTTSProvider.name: MockTTSProvider,
    EdgeTTSProvider.name: EdgeTTSProvider,
}


def get_provider() -> TTSProvider:
    """Return the provider selected by Config.TTS_PROVIDER."""
    provider_class = PROVIDERS.get(Config.TTS_PROVIDER)
    if provider_class is None:
        logger.error("Unknown TTS_PROVIDER %r (available: %s)", Config.TTS_PROVIDER, ", ".join(PROVIDERS))
        raise TTSError("Voice generation is not configured correctly.", 503)
    return provider_class()


def supported_languages() -> list[str]:
    """Language codes the current provider can speak (used later by the language selector)."""
    provider = get_provider()
    return [code for code in Config.SUPPORTED_LANGUAGES if code in provider.supported_languages]


def ensure_language_supported(language: str) -> TTSProvider:
    """Return the current provider if it can speak `language`, otherwise raise TTSError (400).

    Lets callers fail fast, before spending time on conversation generation.
    """
    if language not in Config.SUPPORTED_LANGUAGES:
        raise TTSError("That language is not supported.", 400)
    provider = get_provider()
    if language not in provider.supported_languages:
        raise TTSError(f"Voices for {Config.SUPPORTED_LANGUAGES[language]} are not available yet.", 400)
    return provider


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_speech(text: str, speaker: str, language: str) -> SpeechResult:
    """Generate speech for one conversation segment.

    speaker:  "host_a" or "host_b"
    language: a code from Config.SUPPORTED_LANGUAGES
    """
    if speaker not in SPEAKERS:
        raise TTSError("Unknown speaker.", 400)
    if language not in Config.SUPPORTED_LANGUAGES:
        raise TTSError("That language is not supported.", 400)
    if not isinstance(text, str) or not text.strip():
        raise TTSError("There is no text to speak.", 400)
    text = text.strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise TTSError("That text is too long to turn into speech.", 400)

    provider = ensure_language_supported(language)

    voice = provider.voice_for(speaker, language)
    try:
        result = provider.synthesize(text, voice, language)
    except TTSError:
        raise
    except Exception as exc:
        # Log only the exception type: provider messages can contain URLs or keys.
        logger.warning("TTS provider %r failed: %s", provider.name, type(exc).__name__)
        raise TTSError("Unable to generate voice audio right now. Please try again.", 502)

    if not _is_valid_result(result):
        logger.warning("TTS provider %r returned an invalid result", provider.name)
        raise TTSError("Unable to generate voice audio right now. Please try again.", 502)
    return result


def _is_valid_result(result: Any) -> bool:
    return (
        isinstance(result, SpeechResult)
        and isinstance(result.audio, bytes)
        and len(result.audio) > 0
        and isinstance(result.extension, str)
        and result.extension.isalnum()
    )

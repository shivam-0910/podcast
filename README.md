# AI News Podcast

## Description

A web application that turns current news on a topic into an AI-generated two-host podcast. It:

- searches current news by topic (SERP API)
- lets users select one or more articles
- uses Groq to create a two-host discussion
- generates two AI voices (TTS)
- displays synchronized transcripts
- provides podcast playback controls
- supports multiple languages

## Tech stack

```text
Python
Flask
HTML
CSS
Vanilla JavaScript
SERP API
Groq
TTS
SQLite
```

## Architecture

```text
User
 ↓
Flask
 ↓
SERP API
 ↓
News
 ↓
User selects news
 ↓
Groq
 ↓
Conversation
 ↓
TTS
 ↓
Audio segments
 ↓
Conversation UI
```

## Setup

```bash
python -m venv venv
```

Activate (Windows):

```bash
venv\Scripts\activate
```

Activate (macOS/Linux):

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your API keys. Optionally set `GROQ_MODEL` in `.env` to use a different Groq model (default: `openai/gpt-oss-120b`). Then run:

```bash
python app.py
```
On Windows, if the virtual environment is not activated, run `venv\Scripts\python.exe app.py` to use the project environment.

Open http://127.0.0.1:5000 in your browser.

## API

- `GET /` search page
- `GET /news?q=<topic>` news results page (fetches `/api/search` from the browser)
- `GET /conversation?id=<episode_id>` conversation screen (opened automatically after CREATE AI PODCAST)
- `GET /audio/<episode_id>/<filename>` serves one audio segment (e.g. `001_host_a.wav`), with Range support
- `GET /api/episode/<episode_id>` returns a created episode, or 404. Episodes are held in memory until SQLite is added in Step 14, so they are lost when the server restarts
- `POST /api/episode/create` body `{articles: [...], language, topic}` returns `{episode_id, title, topic, language, conversation: [{id, speaker, text, audio_url}]}`; `audio_url` is `null` until TTS is added
- `GET /api/health` returns `{"status": "ok"}`
- `GET /api/search?q=<topic>` returns `{"query", "count", "results": [{id, title, source, url, snippet, published_at, image_url}]}`; errors return `{"error": "<message>"}`

## Text-to-speech

`services/tts_service.py` exposes `generate_speech(text, speaker, language)`. Providers sit behind a small `TTSProvider` interface, selected by `TTS_PROVIDER` in `.env` (default `edge`). Edge TTS uses Microsoft Edge's online neural voices without an API key and returns MP3 audio for English, Hindi, Bengali, Telugu, and Tamil. On the conversation page, choose a voice for each host to hear a sample, then apply the choices to regenerate that episode's audio. Choices are remembered per language in the browser. Odia isn't available in the current Edge voice catalog. The `mock` provider returns placeholder WAV tones for playback tests.

To add another provider: subclass `TTSProvider` and register it in `PROVIDERS`.

Audio is stored one file per line, never one big file: `audio/<episode_id>/001_host_a.<ext>`, `002_host_b.<ext>`, and so on. The extension comes from the TTS provider (the mock produces `.wav`). Files are deleted when their episode is evicted from the in-memory store or if episode creation fails. Audio left over from a previous server run is not cleaned up until SQLite persistence is added in Step 14.

## Development status

| Step | Feature | Status |
|------|---------|--------|
| 1 | Project structure, config files | Done |
| 2 | Flask foundation, `/api/health` | Done |
| 3 | Basic frontend (search page) | Done |
| 4 | SERP integration, `GET /api/search?q=<topic>` (backend only) | Done (tested with mocked SERP responses; needs your `SERP_API_KEY` for live results) |
| 5 | News results page with article cards | Done |
| 6 | Article selection (up to 5), selected count, enabling CREATE AI PODCAST | Done (the button saves the selection in the browser session; it does not generate a podcast yet) |
| 7 | Groq conversation generation, `POST /api/episode/create` | Done (tested with mocked Groq responses; needs your `GROQ_API_KEY` for live results) |
| 8 | Conversation screen with Host A / Host B transcript bubbles | Done (transcript only; playback, highlighting and waveform come in Steps 10-12) |
| 9 | TTS abstraction with mock and Edge providers | Done (Edge TTS is the default and needs no API key) |
| 10 | One audio file per line saved in `audio/<episode_id>/`, served at `/audio/<episode_id>/<file>` | Done (the browser page does not play it yet; that is Step 11) |
| 11-12 | Synchronized player and waveform | Not implemented |
| 13 | Language and host voice selection | Done (voice choices are shown for languages supported by the selected TTS provider) |
| 14 | SQLite persistence | Not implemented |

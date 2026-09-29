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

Open http://127.0.0.1:5000 in your browser.

## API

- `GET /` search page
- `GET /news?q=<topic>` news results page (fetches `/api/search` from the browser)
- `GET /conversation?id=<episode_id>` conversation screen (opened automatically after CREATE AI PODCAST)
- `GET /api/episode/<episode_id>` returns a created episode, or 404. Episodes are held in memory until SQLite is added in Step 14, so they are lost when the server restarts
- `POST /api/episode/create` body `{articles: [...], language, topic}` returns `{episode_id, title, topic, language, conversation: [{id, speaker, text, audio_url}]}`; `audio_url` is `null` until TTS is added
- `GET /api/health` returns `{"status": "ok"}`
- `GET /api/search?q=<topic>` returns `{"query", "count", "results": [{id, title, source, url, snippet, published_at, image_url}]}`; errors return `{"error": "<message>"}`

## Text-to-speech

`services/tts_service.py` exposes `generate_speech(text, speaker, language)`. Vendors sit behind a small `TTSProvider` interface, selected by the optional `TTS_PROVIDER` variable in `.env` (default `mock`). The mock provider needs no key and returns a WAV tone (different pitch for Host A and Host B) so playback can be tested before a real voice provider is chosen.

To add a real provider: subclass `TTSProvider`, register it in `PROVIDERS`, then set `TTS_PROVIDER` and `TTS_API_KEY`.

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
| 9 | TTS abstraction (`generate_speech`) with a mock provider | Done (the mock plays a placeholder tone per line, not real speech; no real TTS vendor is connected yet) |
| 10 | Audio segments saved to `audio/` and served to the browser | Not implemented |
| 11-12 | Synchronized player and waveform | Not implemented |
| 13 | Language selection | Not implemented (languages are defined in config only) |
| 14 | SQLite persistence | Not implemented |
# podcast

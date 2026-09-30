# AI News Podcast

Turn today's news on any topic into an AI-generated, two-host podcast, presented as a digital newspaper.

You search a topic, page through the results like a newspaper (one story per page), pick up to five stories, choose a language, and the app writes a conversation between two hosts, speaks it with two different voices, and plays it back with a synchronized transcript.

## Table of contents

1. [Features](#features)
2. [Tech stack](#tech-stack)
3. [The full pipeline](#the-full-pipeline)
4. [Workflow, step by step](#workflow-step-by-step)
5. [Folder structure](#folder-structure)
6. [How each file works](#how-each-file-works)
7. [Module boundaries](#module-boundaries)
8. [API reference](#api-reference)
9. [Configuration](#configuration)
10. [Text-to-speech and voices](#text-to-speech-and-voices)
11. [Setup](#setup)
12. [Security notes](#security-notes)
13. [Troubleshooting](#troubleshooting)
14. [Development status](#development-status)
15. [License](#license)

## Features

- Search current news by topic (SerpApi, Google News results).
- Newspaper-style results: one story per page, with the full-size image and a longer text excerpt loaded from the publisher's page.
- Select up to 5 stories, with a live preview list in the sidebar (jump to a story, or remove it).
- Two-host podcast script written by Groq, grounded in the selected articles only.
- Two distinct AI voices per episode, with a voice picker, voice previews, and "Apply to episode" to re-voice an existing episode.
- Synchronized player: transcript highlighting, progress across all segments, waveform, previous/next, volume, click any line to jump to it.
- Multiple languages: English, Hindi, Bengali, Telugu, Tamil (Odia is defined but has no voice yet).
- One consistent warm, yellowed-newsprint theme across the home, news and podcast pages.

## Tech stack

```text
Backend     Python, Flask
Frontend    HTML, CSS, vanilla JavaScript (no framework, no build step)
News        SerpApi (Google News)
Article     requests + trafilatura (server-side page fetch and text extraction)
AI script   Groq (default model: openai/gpt-oss-120b)
Speech      pyttsx3 / SAPI (offline, Windows), edge-tts (online), or a mock provider
Storage     SQLite (episodes) + one audio file per spoken line on disk
```

## The full pipeline

```text
 Browser: Home page ── topic ──►  /news?q=<topic>
                                        │
                                        ▼
                         GET /api/search?q=<topic>
                                        │
        serp_service ──► news_service ──► article_service.remember_articles
        (SerpApi call,    (clean, validate,  (id -> url table so details can
         normalize)        de-duplicate)      be fetched later by id only)
                                        │
                                        ▼
            Newspaper view (news.js): one story per page
                                        │
              for the visible page + the next one:
              GET /api/article/<id>  ──► article_service
              (SSRF-safe page fetch, trafilatura: full-size image + text excerpt)
                                        │
                     user selects up to 5 stories + a language
                                        │
                                        ▼
                        POST /api/episode/create
                                        │
   routes/episode.py: validate ─► news_service.clean_articles (again)
                                        ─► article_service.add_article_text
                                        │
                                        ▼
   episode_service.create_episode
        1. tts_service.ensure_language_supported   (fail fast before spending Groq calls)
        2. conversation_service.generate_conversation   (Groq -> validated JSON script)
        3. for every line, in parallel:  tts_service.generate_speech
           -> audio/<episode_id>/001_host_a.<ext>, 002_host_b.<ext>, ...
        4. store the episode (SQLite)
                                        │
                                        ▼
          Browser redirects to /conversation?id=<episode_id>
                                        │
   player.js: GET /api/episode/<id> ─► transcript bubbles + player
              GET /audio/<id>/<file> ─► one segment at a time, played in order
              voice picker ─► /api/tts/sample (preview), /api/episode/<id>/voices (apply)
```

## Workflow, step by step

1. **Search.** On the home page you enter a topic. `search.js` sends you to `/news?q=<topic>`.
2. **Results.** `news.js` calls `/api/search`. The server asks SerpApi for Google News results, normalizes them to one shape, cleans them (strips HTML, validates URLs, removes duplicates) and remembers each article's URL under its id.
3. **Newspaper view.** Each result is one page. Previous/Next moves one story at a time. (A flag, `SINGLE_PAGE_VIEW`, in `news.js` restores the two-page desktop spread.)
4. **Story details.** For the visible story and the next one, `news.js` calls `/api/article/<id>`. The server downloads the publisher's page and returns a sharp `og:image` plus up to about 1,500 characters of text. Paywalled or bot-blocking sites simply keep the short summary and thumbnail.
5. **Select.** Tick up to five stories. The sidebar lists them; click one to jump to it, or press × to remove it. Choose a language (languages the current voice provider can't speak are shown disabled).
6. **Create.** `CREATE AI PODCAST` posts the selected articles, the language and the topic to `/api/episode/create`. The server re-validates everything, adds article excerpts, then generates the script and the audio. This takes from several seconds to a couple of minutes depending on the number of stories and the voice provider.
7. **Play.** You land on the conversation page. Lines play one after another, the current line is highlighted and scrolled into view, and the progress bar spans the whole episode.
8. **Change voices (optional).** Pick a different voice per host, preview it, then press **Apply to episode** to re-render the audio. Transcript labels show the voice name in use.

## Folder structure

```text
project-root/
├── app.py                          Flask entry point
├── README.md
├── requirements.txt
├── LICENSE                         MIT
├── .env                            your API keys (not committed)
├── .env.example                    template for .env
├── placeholder.txt                 <!-- CONFIRM: purpose -->
├── root-structure.txt              <!-- CONFIRM: purpose -->
│
├── config/
│   ├── __init__.py
│   └── config.py                   all settings and environment variables
│
├── database/
│   ├── __init__.py
│   ├── db.py                       SQLite connection / setup     <!-- CONFIRM -->
│   └── models.py                   episode storage definitions   <!-- CONFIRM -->
│
├── data/                           SQLite database file lives here (created at runtime)
├── audio/                          generated audio, one folder per episode (created at runtime)
│
├── routes/                         HTTP layer: validate input, call a service, return JSON/HTML
│   ├── __init__.py
│   ├── search.py                   GET  /api/search
│   ├── news.py                     GET  /news
│   ├── article.py                  GET  /api/article/<id>
│   ├── episode.py                  /conversation, episode create/fetch/voices, voice samples
│   └── audio.py                    GET  /audio/<episode_id>/<file>
│
├── services/                       business logic and vendor integrations
│   ├── __init__.py
│   ├── serp_service.py             SerpApi (the only file that knows SERP's format)
│   ├── news_service.py             cleaning and de-duplicating articles
│   ├── article_service.py          full-size image + text excerpt from the publisher's page
│   ├── conversation_service.py     Groq script generation
│   ├── tts_service.py              text-to-speech providers and voices
│   └── episode_service.py          orchestrates script + audio + storage
│
├── static/
│   ├── css/
│   │   ├── style.css               global theme, news layout, conversation page, player
│   │   ├── language-additions.css  language selector
│   │   └── player-additions.css    <!-- CONFIRM: player / voice picker styles -->
│   └── js/
│       ├── search.js               home page
│       ├── news.js                 newspaper view, selection, episode creation
│       └── player.js               conversation page and audio player
│
├── templates/
│   ├── index.html                  home page
│   ├── news.html                   news results shell + sidebar (selection, language, create)
│   └── conversation.html           transcript, voice picker, player
│
└── tests/
    └── test_episode_persistence.py episode persistence tests
```

## How each file works

### Entry point and configuration

| File | What it does |
|------|--------------|
| `app.py` | `create_app()` sets up logging and the secret key, registers the five blueprints (`search`, `news`, `episode`, `audio`, `article`), and defines `GET /` (home page) and `GET /api/health`. Running it starts the dev server with the host, port and debug flag from `Config`. |
| `config/config.py` | The only place that reads environment variables. Loads `.env`, then exposes a `Config` class: API keys, paths (`DATABASE_PATH`, `AUDIO_DIR`), `SUPPORTED_LANGUAGES`, the Groq model and timeout, `MAX_ARTICLES_PER_EPISODE` (5), `TTS_PROVIDER`, `TTS_MAX_WORKERS`, host/port/debug, and the request timeout. |
| `config/__init__.py` | Package marker. |

### Routes (HTTP layer)

Routes only validate input, call one service and shape the response. They contain no vendor logic.

| File | Endpoint(s) | What it does |
|------|-------------|--------------|
| `routes/search.py` | `GET /api/search?q=` | Validates the query (required, max 200 chars), calls `serp_service.search_news`, cleans results with `news_service.clean_articles`, and records each article's URL via `article_service.remember_articles`. Errors become `{"error": ...}` with a user-safe message. |
| `routes/news.py` | `GET /news` | Serves the news page shell. Builds the language dropdown: every configured language is listed, and languages the current voice provider can't speak are disabled ("coming soon"). |
| `routes/article.py` | `GET /api/article/<id>` | Returns `{id, image_url, paragraphs, truncated}` for an article from a recent search, via `article_service.get_details`. |
| `routes/episode.py` | `GET /conversation`, `POST /api/episode/create`, `GET /api/episode/<id>`, `POST /api/episode/<id>/voices`, `GET /api/tts/sample` | Page shell (with voice options), episode creation (validates articles, language, optional voices and topic; adds excerpts; calls `create_episode`), episode lookup, re-voicing an episode, and short voice previews. |
| `routes/audio.py` | `GET /audio/<episode_id>/<filename>` | Serves one audio segment. Both path parts are matched against strict patterns (32 hex characters, `NNN_host_a|b.<ext>`), so only real segments can be requested. Supports Range/conditional requests so browsers can seek. |

### Services (logic and vendors)

| File | What it does |
|------|--------------|
| `services/serp_service.py` | Calls SerpApi (Google News) and normalizes each result to `{id, title, source, url, snippet, published_at, image_url}`. The id is a short SHA-1 of the URL. Raises `SerpError` with a safe message; raw errors and keys never leave this file. |
| `services/news_service.py` | `clean_articles()`: strips HTML, validates required fields, accepts only http(s) URLs, truncates long text, and removes duplicates by URL and by title. Has no SERP-specific code. |
| `services/article_service.py` | `remember_articles()` keeps an id-to-URL table in memory. `get_details(id)` downloads the publisher page and extracts a full-size image and about 1,500 characters of text (trafilatura), with a small cache. `add_article_text()` adds that excerpt to articles for the podcast script, in parallel, failing softly. Every request and redirect must resolve to a public IP address (SSRF protection). |
| `services/conversation_service.py` | Builds the prompts and calls Groq. The script is two unnamed hosts: `host_a` (curious) and `host_b` (knowledgeable), grounded only in the supplied summaries and excerpts, written in the chosen language. Output is validated JSON (`speaker` and `text` per turn); markdown, stage directions and speaker labels are stripped; one retry on invalid output. Target length grows with the number of stories. |
| `services/tts_service.py` | Turns text into audio behind a small `TTSProvider` interface. Providers: `offline` (pyttsx3/SAPI), `edge` (Microsoft Edge neural voices) and `mock` (placeholder tones). Exposes `generate_speech()`, `supported_languages()`, `ensure_language_supported()` and the per-language voice lists used by the voice picker. Failures become `TTSError`. |
| `services/episode_service.py` | Coordinates everything: check the language can be spoken, generate the script, render every line to its own audio file in parallel (`TTS_MAX_WORKERS`), retry once on transient TTS failures, write files atomically, and store the episode. On failure the half-built audio folder is deleted. Also re-renders an episode with new voices. Contains no Groq or TTS vendor details. |

### Database

<!-- CONFIRM this whole subsection against your database/ files -->

| File | What it does |
|------|--------------|
| `database/db.py` | SQLite connection and setup. The database file is `data/podcast.db`. |
| `database/models.py` | Episode storage: saving and loading episodes and their segments. |
| `tests/test_episode_persistence.py` | Tests that episodes survive a restart. |

### Frontend

| File | What it does |
|------|--------------|
| `static/js/search.js` | Home page: checks `/api/health` and sends the topic to `/news?q=`. |
| `static/js/news.js` | The newspaper view. Fetches results, renders one story per page with Previous/Next, keeps the selection (max 5) and the sidebar preview list, loads story details (image and text) for the visible and next page, remembers the chosen language in `localStorage`, and creates the episode (up to 5 minutes allowed) before opening the conversation page. All external text is inserted with `textContent`, never `innerHTML`. |
| `static/js/player.js` | The conversation page. Loads the episode, builds transcript bubbles (labelled with the voice name in use), plays segments in order, highlights and scrolls to the current line, computes progress across all segments, animates the waveform, and handles the voice picker (preview, apply, remembered in `localStorage`). |
| `static/css/style.css` | Global theme (warm newsprint palette), home page, newspaper layout, sidebar, transcript bubbles, player bar and voice picker. |
| `static/css/language-additions.css` | Styling for the language selector. |
| `static/css/player-additions.css` | <!-- CONFIRM: what this contains --> |
| `templates/index.html` | Home page: masthead, search form, server status. |
| `templates/news.html` | News shell: search box, results area, and the left sidebar with the selected count, selected-story list, language selector and Create button. |
| `templates/conversation.html` | Episode title, voice picker, transcript, and the fixed player bar. Passes languages and voice options to `player.js` as JSON. |

## Module boundaries

Each module has one job, and the boundaries are deliberate:

- `serp_service.py` is the **only** place that knows SerpApi's response format.
- `news_service.py` knows nothing about SERP; it only cleans normalized articles.
- `article_service.py` is the only place that downloads publisher pages, and it never takes a URL from the browser.
- `conversation_service.py` is the only place that talks to Groq.
- `tts_service.py` is the only place that talks to a voice vendor. Adding a vendor means subclassing `TTSProvider` and registering it in `PROVIDERS`; nothing else changes.
- `episode_service.py` coordinates but contains no vendor details.
- Routes validate and delegate; they do not contain business logic.
- `config/config.py` is the only file that reads environment variables. API keys are never sent to the frontend.

## API reference

| Method and path | Purpose |
|-----------------|---------|
| `GET /` | Home page |
| `GET /news?q=<topic>` | News results page (fetches `/api/search` from the browser) |
| `GET /conversation?id=<episode_id>` | Conversation page |
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/search?q=<topic>` | `{query, count, results: [{id, title, source, url, snippet, published_at, image_url}]}` |
| `GET /api/article/<id>` | `{id, image_url, paragraphs, truncated}` for a story from a recent search; 404 if unknown or unreadable |
| `POST /api/episode/create` | Body `{articles: [...], language, topic, voices?}` where `voices` is `{host_a, host_b}`. Returns `{episode_id, title, topic, language, voices, conversation: [{id, speaker, text, audio_url}]}` |
| `GET /api/episode/<episode_id>` | A created episode, or 404 |
| `POST /api/episode/<episode_id>/voices` | Body `{voices: {host_a, host_b}}`; re-renders the audio and returns the updated episode |
| `GET /api/tts/sample?language=&speaker=&voice_id=` | A short audio preview of one voice |
| `GET /audio/<episode_id>/<filename>` | One audio segment, e.g. `001_host_a.mp3`, with Range support |

All errors are returned as `{"error": "<user-safe message>"}` with an appropriate status code.

## Configuration

Settings come from `.env` (see `.env.example`) and `config/config.py`.

| Variable | Purpose | Default |
|----------|---------|---------|
| `SERP_API_KEY` | SerpApi key (required for search) | none |
| `GROQ_API_KEY` | Groq key (required for scripts) | none |
| `GROQ_MODEL` | Groq model to use | `openai/gpt-oss-120b` |
| `TTS_PROVIDER` | `offline`, `edge` or `mock` | `offline` on Windows |
| `EDGE_TTS_PROXY` | Proxy for the Edge voice service, if your network needs one | none |
| `FLASK_SECRET_KEY` | Flask secret key | insecure dev key; set your own |
| `FLASK_DEBUG` | `1` enables debug mode | `1` |

Values set directly in `config/config.py`: `SUPPORTED_LANGUAGES`, `MAX_ARTICLES_PER_EPISODE` (5), `TTS_MAX_WORKERS` (parallel audio lines), `GROQ_TIMEOUT_SECONDS` (60), `REQUEST_TIMEOUT_SECONDS` (15), `HOST` (127.0.0.1) and `PORT` (5000).

## Text-to-speech and voices

Voices sit behind the `TTSProvider` interface in `services/tts_service.py`.

- **`offline`**: `pyttsx3` with the SAPI voices installed on Windows. No network needed. Only languages with an installed local voice are available.
- **`edge`**: Microsoft Edge's online neural voices for English, Hindi, Bengali, Telugu and Tamil. No API key. Odia is not in the voice catalog.
- **`mock`**: placeholder tones, for testing playback without any voice service.

Each language has a list of voices and a default voice per host. The voice picker on the conversation page previews a voice, and **Apply to episode** re-renders the audio; your choice is remembered per language in the browser.

Audio is stored one file per spoken line, never as one big file:

```text
audio/<episode_id>/001_host_a.<ext>
audio/<episode_id>/002_host_b.<ext>
...
```

The extension comes from the provider (`.mp3` for Edge, `.wav` for the mock provider).

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
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your `SERP_API_KEY` and `GROQ_API_KEY`. Then run:

```bash
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Security notes

- API keys stay on the server and are never sent to the browser.
- The article-details endpoint accepts only an article id. The URL comes from a server-side table, so the browser can't make the server fetch arbitrary addresses. Every request and redirect must resolve to a public IP address, downloads are size- and time-limited, and only HTML is accepted.
- Audio requests are matched against strict filename patterns (no path traversal, no directory listing).
- All news and episode text is inserted into pages with `textContent`, never `innerHTML`. Article text given to the AI is treated as untrusted data.
- Raw provider errors, prompts and keys are never returned to the user.

## Troubleshooting

| Symptom | Likely cause and fix |
|---------|----------------------|
| "Unable to create the podcast right now" but the terminal shows the episode was created | Creation took longer than the browser's wait time. Raise `CREATE_TIMEOUT_MS` in `news.js`, and check `TTS_MAX_WORKERS`: a value of 1 makes long episodes slow. |
| "Could not connect to the voice service" | With `TTS_PROVIDER=edge`: check the internet connection, VPN or firewall, run `python -m pip install -U edge-tts`, or set `EDGE_TTS_PROXY`. Use `TTS_PROVIDER=mock` to test the rest of the app. |
| Conversation page stuck on "Loading episode..." | Open the browser console (F12). A missing-element error means `templates/conversation.html` is out of date with `static/js/player.js`. |
| A story shows only 2 lines and a small image | The publisher blocks server requests or is behind a paywall. The terminal shows `Article fetch returned HTTP 401/403/406`, and the browser console shows a red 502. This is expected; the story falls back to its summary. |
| Both hosts sound the same | Both dropdowns are set to the same voice. Check the saved choice with `localStorage.getItem('podcast.voices')` in the browser console. |
| A language is greyed out | The current `TTS_PROVIDER` has no voice for it. |

## Development status

| Step | Feature | Status |
|------|---------|--------|
| 1 | Project structure, config files | Done |
| 2 | Flask foundation, `/api/health` | Done |
| 3 | Basic frontend (search page) | Done |
| 4 | SERP integration, `GET /api/search` | Done |
| 5 | Newspaper-style news results | Done (one story per page, page-turn animation) |
| 6 | Article selection (up to 5), selected count, sidebar preview | Done |
| 7 | Groq conversation generation, `POST /api/episode/create` | Done |
| 8 | Conversation screen with transcript bubbles | Done |
| 9 | TTS abstraction (offline, Edge and mock providers) | Done |
| 10 | One audio file per line, served with Range support | Done |
| 11-12 | Synchronized player and waveform | Done |
| 13 | Language selection | Done |
| 14 | SQLite persistence | See `database/` and `tests/` <!-- CONFIRM: Done? --> |
| Extra | Full-size images and article excerpts (`/api/article`), excerpts fed to the AI | Done |
| Extra | Voice picker, previews and re-voicing an episode | Done |
| Extra | Unified warm newsprint theme across all pages | Done |

## License

MIT. See [LICENSE](LICENSE).

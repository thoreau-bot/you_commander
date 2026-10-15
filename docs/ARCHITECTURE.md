# Architecture

Single-process FastAPI app serving static HTML pages (vanilla JS, no build step) over a SQLite database. Every page links one shared stylesheet, `static/app.css`; page-specific rules stay inline in the page.

| File | Role |
|---|---|
| `app.py` | Core API: videos, tags, search (FTS5), triage, batch endpoints, import endpoints |
| `importer.py` | Schema creation and Takeout playlist CSV import |
| `watch.py` | Watch state/log, marks (notes), queue, history, `/watch` and `/history` |
| `transcripts.py` | Caption fetch (`yt-dlp`, json3), Whisper path, background worker, transcript search |
| `voice.py` | Local `faster-whisper` transcription, optional Ollama tag extraction |
| `ui.html` `triage.html` `watch.html` `history.html` `import.html` | Pages |
| `static/app.css` `static/app.js` | Shared visual system (tokens, controls, light/dark) and the `?` help overlay; served at `/static/` |
| `tools/make_demo.py` | Builds an invented demo library |
| `tests/` | pytest smoke tests and a JS syntax check of every page |

## Data
SQLite in WAL mode. Key tables: `videos`, `playlists`, `playlist_items`, `tags`/`video_tags`, `notes`, `watch_state`, `watch_log`, `video_marks`, `transcripts(video_id, kind, status, text, cues, …)`, `bulk_log`. Full-text: `video_fts` (contentless) and `transcript_fts`. `importer.ensure_schema` and each module's `setup()` create/migrate tables idempotently.

## Player
Uses the YouTube IFrame API. Because focus inside a cross-origin iframe cannot be controlled, "player mode" drives the player through the API and captures keys on the parent page.

## Test hooks
Set these to avoid the network: `ORG_OEMBED_FAKE`, `ORG_TRANSCRIPT_FAKE`, `ORG_VOICE_FAKE_TRANSCRIPT`.

## Design choices
- Local only; no write-back to YouTube.
- One SQLite file for easy backup.
- No front-end framework, so the pages stay readable and dependency-free.

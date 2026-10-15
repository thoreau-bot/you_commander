# Changelog

## 1.1.0
- New visual design across all five pages: one shared stylesheet (`static/app.css`) with light and dark themes, a quieter layout, a video "stage", tag pills and key-cap badges on every button
- Keyboard help overlay on every page: press `?` (the long shortcut cheat-sheets are gone from the pages themselves)
- Commander: the bulk bar only appears while videos are ticked; "Select all" and "Undo last bulk" moved to the search bar; tags in the list render as pills; an empty view says so
- Watch and Triage: controls grouped by purpose (transport, speed, loop), actions carry their key, status text reads as sentences
- History and Import restyled on the same system
- No new dependencies and no network access added: fonts are the system's, static files are served from the app itself

## 1.0.0
- Takeout playlist import (playlists only)
- Commander with FTS search, nested tags, bulk actions
- Single and batch triage with undo log
- Watch page: resume, speed, A–B loop, reorderable queue, copy-as-YouTube-queue
- History and Continue Watching
- Notes (text/voice) at time, line or selection
- Transcripts: captions and Whisper, both stored, searchable
- Demo data generator, tests, CI

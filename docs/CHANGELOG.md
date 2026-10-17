# Changelog

## 1.2.0
Review round 1 of the adversarial panel (49 confirmed findings). Highlights:
- Keyboard model: when a button or link has focus, Enter and Space act on it, never on the page (shared `yc.onControl`); Shift+arrow range ticking works whether Shift is tapped or held; typing `/` inside the bulk tag box no longer jumps to Search; ↓ or Enter in Search moves into the results
- Commander: one owner for the view (rail highlight, title line "All videos · 281", search scope shown in the title with a "search all videos" escape); state restored after a trip to Watch; bulk results, undo and transcript jobs report in a status toast; "Load 200 more" only when there is more; playlists view in real columns; tag editor sheet in two rows
- Browser prompt/confirm/alert replaced by in-page popovers (new tag, rename, merge, bulk apply, undo, drop all, delete transcript)
- Triage: Drop can be undone with ← Back (reopen); a finished queue shows a single card with one action; tag box keeps focus after Enter; Esc closes the dropdown, then clears, then leaves; batch Confirm all asks first for 2+; Space previews in batch, V records
- Watch: title and channel sit under the video; queue focus mode ends when a video is chosen; one Previous/Next pair; empty and unknown-video states; Space toggles the Autoplay box when it has focus
- Import: Enter cannot run the import twice; Esc goes back one step; `?` help and the top bar when a library exists
- Search: punctuation-only queries return nothing instead of everything; the search index refreshes after tag changes (previously only on import)
- Light theme retuned to pass WCAG AA (muted text 5.4:1, key-caps 6.9:1, chips ≥5:1); visible focus rings on checkboxes and row links; one control height scale (32 / 28); type scale 12 / 13.5 / 15 / 20; topbar no longer ghosts content through
- Accessibility: chip × are real buttons with labels, rail items are role=button, status text is aria-live, the help overlay is a dialog with a close button and focus trap
- Docs: KEYBOARD.md corrected (C = copy timestamp link; batch Enter; Import keys), USER_GUIDE no longer promises undo for Triage Drop

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

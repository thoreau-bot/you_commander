# Changelog

## 1.4.0
Review round 3 (29 confirmed findings). Also adds a regression suite of every confirmed finding so far (review/tools/regress.py in the review workspace).
- Tab no longer loops inside an open video on Commander: the sentinels around the player pass focus through, and never scroll or blur
- Enter in an empty tag box does nothing (it used to add the first tag); one shared tag picker now serves Commander's bulk bar, Triage, Watch and batch, with prefix match and "Create tag"
- Shift+arrow from a ticked row extends the ticked range (unticks only when the whole range was already ticked)
- A mouse click on any button or checkbox hands focus straight back, so arrows and Enter keep acting on what is highlighted
- Player mode and the Triage context menu are modal: the menu takes ↑↓ Enter and closes on any other key; player mode swallows unhandled keys and says so
- Esc hands focus back from a focused select; Enter on a focused checkbox ticks it
- Undo: deleting a timestamped note and Drop on the Watch page show an undo toast (click Undo or press Z)
- Search covers notes (video note and timestamped notes); duplicate tag names under one parent are refused; audit rows show their tags
- Watch: Find in transcript with Enter/↑/↓; the transcript header is Find + Follow along + ⋯; one bordered transport row with ghost actions aligned beneath; Confirm tags is the primary
- Triage: Back works from the finished card; the voice-setup note is a dismissible line under the panel; the Inbox marker looks like a marker
- History: header row, four columns, position folded into the title line; Import: alert and progressbar roles, focus lands on Open when done
- Visual: five type sizes by token, two control heights, monospace key-caps and timecodes, visible focus ring inside button groups, legible transcript highlights, raised dark surfaces for popovers and hover
- Narrow (≤700px): rail capped at 30vh, tag editor behind an "Edit tag" disclosure, Triage decisions stick to the bottom

## 1.3.0
Review round 2 (39 confirmed findings, none above severity 3).
- Esc now has a "control focused" level on every page: the first Esc hands focus back, then transients close, and only from rest does Esc leave; a mouse click on a Triage decision button hands focus back so Enter keeps meaning Confirm
- Commander: the ← rail walks every view (All videos, audits, playlists, tags), Shift+Tab only enters the rail from rest so reverse tabbing works; Enter/↓ in the search box no longer also tick row 1; leaving the rail keeps the current row; ticks survive a trip to another page; rename lives in the tag sheet; a Watch page action in the open video; narrow layout keeps the header in place
- Triage: ← Back works from the finished card; an unknown `?v=` says so instead of "Done"; Confirm is the filled primary; the Inbox marker no longer looks like a tag; batch warnings persist across re-renders
- Watch: the first Tab starts at the top (queue scrolling no longer moves the focus start point); Find in transcript seeks with Enter/↓/↑; Autoplay remembered; no key errors on the empty page; note delete is a real button
- History: a no-match filter says so and disables "Watch these in order"; Import: returning users get their account name prefilled
- Visual: one control height (32 / 28), opaque top bar, dark-mode hover on Confirm/Drop legible, help dialog without a stray ring, key-caps slightly stronger in light, popovers trap Tab

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

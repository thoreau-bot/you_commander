# Changelog

## 1.8.0
Requested changes. Regression suite: 150 checks (14 new), all green.
- The "F Video Controls" flash is magenta (new `--mag` tokens, both themes)
- Play state travels with the moment: a playing preview hands a playing Watch page (from the same second); a paused one arrives paused. Coming back with `Esc` restores the preview at the Watch page's time and play state
- The same hand-off for Triage: `E` (or Triage This Video) opens Triage in this tab at the preview's moment and play state; `Esc` there comes back to the preview likewise
- Preview actions are four matching buttons: Watch in Theater `W`, Open on YouTube `Y` (new shortcut), Sound On `M`, Triage This Video `E`
- The "Video Controls ON" card lists Space alone for play / pause (K still works)
- Import from Takeout is a button in the rail, icon inside

## 1.7.0
Requested changes. Regression suite: 136 checks (24 new), all green.
- Commander rail: "Owner & Visibility" (singular). Every column of that view sorts: click a header, again to reverse; Videos starts descending. The sort is remembered on this computer
- History: `W` (or `Enter`, or a click) opens the highlighted video in Watch in Theater with the rest of the list, in the same order, as the queue; `T` triages the highlighted video; `Esc` goes back to Commander (from the filter box, the first `Esc` only leaves the box); `Home`/`End`
- Commander preview: the label under the video reads "F Video Controls" and flashes three times when a video opens; while video controls are on it reads "Tab Exit YouTube Video Controls" and goes back to F when you press Tab, Esc, or leave
- The video-controls card is titled "Video Controls ON" and its Tab line reads "Exit YouTube Video Controls"
- `W` from a playing preview (or Triage video) pauses it before the Watch page opens
- Watch page: the stage carries the same accent ring as video controls elsewhere, and a "Video Controls ON" card lists the page's keys (no Tab line; the video always has the keyboard there)
- Round trip: from a Commander preview, `W` → Watch page → `Esc` comes back with the same video open in the accordion, paused where the Watch page left it

## 1.6.0
Requested changes. Regression suite: 112 checks (40 new), all green.
- Commander rail: **Watch in Theater** (`W`) sits between Start Triage and History. It opens the open, highlighted or first video on the Watch page with the current view as its queue; with two or more ticked, it plays those in list order
- `W` works while video controls (`F`) are on, in a Commander preview and in Triage, and carries on from the same moment on the Watch page (`&t=` hand-over). Triage gains `W` everywhere (button, context menu, help); `Esc` on the Watch page comes back to the same Triage video. In batch triage, `W` watches the highlighted video with the batch as its queue
- Video controls: `F` no longer turns them off. `Esc` is the only way out; with them on, `F` (or `Enter`) is fullscreen, as inside YouTube. A mouse click into the video while they are on hands the keyboard straight back to the page, so `W`, `F` and `Esc` keep working; `Tab` still hands it to YouTube's own controls on purpose
- The video-controls card (bottom right) now lists its keys as key-caps. Any message that covers it goes away within 10–15 s at most (by length) and the card comes back; volume/speed/mute readouts no longer replace it for good, and switching windows no longer hides it. When YouTube's own controls have the keyboard, the card says so instead of a separate one-minute message
- Commander list: a click on a row's empty space ticks or unticks it, a large target for anyone who finds the checkbox hard to hit. The title still opens the video; a double-click counts once
- Title Case for every button, menu item and left-rail item ("Start Triage", "All Videos", "Watch Later, Not Yet Sorted", "Note at This Time"…). Tag names are left as you typed them
- Video controls live once, in app.js (`yc.playerMode`), instead of a copy in Commander and in Triage; toasts and the standing card share one bubble manager (`yc.toast` / `yc.hint`)

## 1.5.0
Review round 4 fixes (regression suite now 72 checks, all green).
- Tag picker: picking a tag keeps its name in the box; Enter creates a tag only after ↓ onto the "Create tag" row (or when the query is a path); Enter with a chosen tag in Commander's bulk bar applies it; a re-opened list no longer closes on a stale blur
- Double-fire guards: Triage's Confirm/Skip/Drop/Back and the batch actions ignore a second press while the first is in flight; Watch ignores a second queue step while a video is loading
- Esc levels: the selection popup and the transcript ⋯ menu are "transients" that Esc closes before the page acts on Esc; Esc inside a text field never opens the context menu
- Commander: the bulk bar keeps its height and shows a hint when nothing is ticked; "N selected · k in view" when ticks are off-screen; bulk results are undo toasts (Z); ↓ on the last loaded row loads more; End says how many are loaded; PgDn measures a real row; ← from a ticked checkbox enters the rail; W with nothing highlighted explains itself; listbox/option roles with aria-activedescendant on the list and the rail
- Triage: the context menu shows key-caps and marks Drop as destructive; the counter reads "N to sort · N done"; chips share one class/tooltip source; the finished card is a full-height state with a glyph; aria-pressed on Sound
- Watch: Sound and Fullscreen sit in one transport group with aria-pressed; timestamped notes get an Edit button and the delete ✕ stays faintly visible; transcript Find highlights are underline-style and distinct from the followed line; the transcript stops redrawing while Find is focused or when nothing changed; Find shows "k / n"; the empty state is full-height with a glyph; narrow screens reorder to player → notes → queue; one toast implementation (shared undo toasts)
- History: a real page title with the summary beside it; "Plays" column; chips painted once. Import: file input labelled, plurals, "new to YouCommander" copy, returning users see "Add or refresh playlists from a Takeout"
- Visual: primary buttons darken on hover instead of brightening; key-caps on green primaries darken to stay legible; selects show hover; popovers get a caret and flip with an .up class; checkbox focus ring is rounded; search bar 32px; empty states capped at 48ch
- Shared layer: yc.busy (in-flight guard), yc.transient/closeTransient; the mouse-click hand-back rule covers row links and ignores non-element targets

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

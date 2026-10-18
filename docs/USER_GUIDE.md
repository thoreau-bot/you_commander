# User Guide

## 1. Get your data
1. Go to <https://takeout.google.com>, click **Deselect all**, then tick only **YouTube and YouTube Music** → *All YouTube data included* → select **playlists** only.
2. Export once, download the `.zip`.

YouCommander reads only the playlist CSV files inside. History, comments and subscriptions are never opened (this is covered by a test).

## 2. Import
Start the app, open **Import**, and choose the zip (or a folder). Re-importing is safe: videos are matched by ID and your tags and statuses are kept. Titles and channels are filled in from YouTube's public oEmbed endpoint on request.

## 3. Commander (main page)
- `/` focuses search. Search covers titles, channels, tags, notes and transcripts.
- Arrow keys move through results; `Enter` ticks a row; `Space` previews it. Clicking the empty part of a row also ticks or unticks it, a larger target than the checkbox.
- In a preview, `F` turns on video controls (the keys are listed in a card at the bottom right); `Esc` turns them off.
- Tags are hierarchical: `cooking/baking/bread`. Pick from the autocomplete or type a new path.
- Select several rows and press `T` to start a **batch triage**.

## 4. Triage
Step through videos with Confirm (`Enter`), Skip (`S`/→) or Drop (`X`). `T` focuses the tag box, `N` the note box, `M` / `G` jump to related actions. Bulk changes on the Commander page can be undone with **Undo Last Bulk**; a Drop in Triage is reversed by pressing `←` Back on it.

Batch triage shows the selected videos as accordions with per-video tags, a bulk tag box and *Confirm* / *Drop All*. Use ↑/↓ to highlight a video, `Space` to preview, `R` to remove it from the batch, `Enter` to fold it, `Esc` or ← to return, and `F` to focus the player.

## 5. Watch page
Open a video with **Watch in Theater** (`W`) from the Commander rail, a preview, or Triage. From a playing preview it carries on from the same moment, and `Esc` takes you back. Features:
- Resume where you left off; speed (`<` / `>`); A–B loop (`[`, `]`, `\`).
- **Queue** built from a tag, a list of IDs or your history. Drag items, or focus the queue with `Q` and use `Alt+↑/↓`. `PgDn`/`PgUp` go to next/previous.
- **Copy as YouTube Queue** copies a `watch_videos` link so the same list can be opened on YouTube itself.
- Videos that cannot be embedded show a fallback.

## 6. Notes
- `B` adds a text note at the current time; `V` records a voice note.
- With `Shift`, the note attaches to the highlighted transcript line instead.
- Select any text in the transcript and use the pop-up buttons to attach a note to that quote.

## 7. Transcripts
- **Captions**: reads the video's caption track as text; no audio is downloaded.
- **Whisper**: downloads the audio temporarily and transcribes locally (needs `install_voice.bat`/`pip install faster-whisper`).
- Both versions are stored; switch between them in the transcript header. **Follow Along** scrolls inside the transcript box. The search box filters within a transcript; the main search finds text across all.
- `install_transcripts.bat` (or `pip install -U yt-dlp`) keeps the caption fetcher current.

## 8. History
`H` opens History: everything opened or watched in the app, with filters, *Continue Watching*, and *Watch These in Order*.

## 9. Backup
Everything is in one SQLite file (`organizer.db`) plus the `audio_notes` folder. Run `BACKUP.bat` or just copy those while the app is stopped.

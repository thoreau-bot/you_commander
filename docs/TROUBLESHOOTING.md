# Troubleshooting

**Port 8765 already in use** – another copy is running. Close it, or start with `python -m uvicorn app:app --port 8770`.

**A video shows "unavailable" in the player** – the owner disabled embedding, or it was removed/private. Use the fallback link.

**Captions fetch fails** – update the fetcher: `install_transcripts.bat` or `pip install -U yt-dlp`. Some videos have no captions; use Whisper.

**Whisper is slow** – set `ORG_WHISPER_MODEL=base` (or `tiny`) or use a GPU (`ORG_WHISPER_DEVICE=cuda`).

**`av` import error on Windows** – `pip install "av>=14,<19"`.

**Voice notes empty** – check microphone permission in the browser for `127.0.0.1`.

**Import found 0 videos** – the Takeout must include *playlists*; the CSVs are under `YouTube and YouTube Music/playlists/`.

**Titles are blank** – run the title lookup from Import; it needs internet access.

**Reset** – stop the app and delete `organizer.db`.

## "YouTube asked us to slow down" / HTTP 429
YouTube throttles by address, across everything the app asks it for. Caption fetches are the heaviest (several requests per video), so they are the first to see a 429. When one arrives the app pauses all its YouTube traffic for a few minutes (longer if it keeps happening) and resumes on its own; the Watch and Feed pages show the resume time. Queue captions in smaller batches if it recurs, and leave the background feed check ticked: it waits while captions are queued.

## "database is locked", or the Watch page stays black
Before 1.9's fix, a running Feed background check could hold the database for long stretches. If you still see this: the Feed page's "Check for new videos in the background" box can be unticked (Check Now still works on demand), and `BACKUP.bat` is always safe to run. Report it with the console log if it persists.

# Privacy

YouCommander is built to stay on your computer.

**Stored locally:** the database (`organizer.db`), voice-note audio, and any transcripts you fetch.

**Read from Takeout:** only playlist CSV files. Other files in the archive are skipped and never opened.

**Network use** (all initiated by you, none automatic beyond the embed):
| What | Where | When |
|---|---|---|
| Embedded player | youtube.com / youtube-nocookie.com iframe | When you preview or watch a video. YouTube sees this like any embed. |
| Title/channel lookup | YouTube oEmbed | When you ask to fill in missing titles |
| Captions / audio | YouTube via `yt-dlp` | Only when you click a transcript button for one video |
| Model download | Hugging Face | First use of Whisper |
| LLM tagging | Your own Ollama on localhost | Only if configured |

**Never:** analytics, telemetry, accounts, cloud sync, or writing to your YouTube account.

The server listens on `127.0.0.1` only and has no login; do not port-forward it.

Your database contains your viewing interests. Treat `organizer.db` and exports as personal data, and never commit them (`.gitignore` excludes them).

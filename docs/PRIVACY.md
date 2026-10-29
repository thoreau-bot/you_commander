# Privacy

YouCommander is built to stay on your computer.

**Stored locally:** the database (`organizer.db`), voice-note audio, any transcripts you fetch, and — only if you tick **Keep Audio** on the Watch page — the audio of videos you transcribe with Whisper, under `audio/whisper/` or a folder you choose on the Watch page (a few MB each; Drop Audio on a video, or the setting, removes them).

**Read from Takeout:** only playlist CSV files. Other files in the archive are skipped and never opened.

**Network use** (all initiated by you, none automatic beyond the embed):
| What | Where | When |
|---|---|---|
| Embedded player | youtube.com / youtube-nocookie.com iframe | When you preview or watch a video. YouTube sees this like any embed. |
| Title/channel lookup | YouTube oEmbed | When you ask to fill in missing titles |
| Channel identity | YouTube oEmbed, then one visit to each channel's page (`youtube.com/@handle`) | Only when you press Resolve Channels on the Feed page. Reads the channel's public id; no sign-in, no API key |
| Channel feeds | `youtube.com/feeds/videos.xml` (public Atom, one request per channel) | When you press Fetch New Videos / Check Now, and afterwards in the background **only while the app is running and only if "Check for new videos in the background" is ticked** (it is ticked after your first fetch; untick it on the Feed page). Hourly for channels you watch, daily for the rest. Unchanged feeds answer with a 304 and carry no content |
| Shorts check | `youtube.com/shorts/<id>` (one HEAD request, no body) | Once per new feed item, to tell Shorts from regular videos |
| Captions / audio | YouTube via `yt-dlp` | Only when you ask for captions or a Whisper transcript (one video, or a ticked batch). Whisper audio is deleted after the run unless Keep Audio is on; a Re-transcribe on kept audio makes no request |
| Model download | Hugging Face | First use of Whisper |
| LLM tagging | Your own Ollama on localhost | Only if configured |

**Never:** analytics, telemetry, accounts, cloud sync, or writing to your YouTube account. The feed requests carry no cookies and no account; YouTube sees them the way it sees any feed reader.

The server listens on `127.0.0.1` only and has no login; do not port-forward it.

Your database contains your viewing interests. Treat `organizer.db` and exports as personal data, and never commit them (`.gitignore` excludes them).

# Privacy

YouCommander is built to stay on your computer.

**Stored locally:** the database (`organizer.db`), voice-note audio, and any transcripts you fetch.

**Read from Takeout:** only playlist CSV files. Other files in the archive are skipped and never opened.

**Network use** (all initiated by you, none automatic beyond the embed):
| What | Where | When |
|---|---|---|
| Embedded player | youtube.com / youtube-nocookie.com iframe | When you preview or watch a video. YouTube sees this like any embed. |
| Title/channel lookup | YouTube oEmbed | When you ask to fill in missing titles |
| Channel identity | YouTube oEmbed, then one visit to each channel's page (`youtube.com/@handle`) | Only when you press Resolve Channels on the Feed page. Reads the channel's public id; no sign-in, no API key |
| Channel feeds | `youtube.com/feeds/videos.xml` (public Atom, one request per channel) | When you press Fetch New Videos / Check Now, and afterwards in the background **only while the app is running and only if "Check for new videos in the background" is ticked** (it is ticked after your first fetch; untick it on the Feed page). Hourly for channels you watch, daily for the rest. Unchanged feeds answer with a 304 and carry no content |
| Shorts check | `youtube.com/shorts/<id>` (one HEAD request, no body) | Once per new feed item, to tell Shorts from regular videos |
| Captions / audio | YouTube via `yt-dlp` | Only when you click a transcript button for one video |
| Model download | Hugging Face | First use of Whisper |
| LLM tagging | Your own Ollama on localhost | Only if configured |

**Never:** analytics, telemetry, accounts, cloud sync, or writing to your YouTube account. The feed requests carry no cookies and no account; YouTube sees them the way it sees any feed reader.

The server listens on `127.0.0.1` only and has no login; do not port-forward it.

Your database contains your viewing interests. Treat `organizer.db` and exports as personal data, and never commit them (`.gitignore` excludes them).

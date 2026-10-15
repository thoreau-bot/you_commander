# Contributing

```sh
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
```

Run the app against invented data: `python tools/make_demo.py && ORG_DB=demo_data/organizer.db uvicorn app:app --port 8766`.

Guidelines
- Keep it local-first: no telemetry, no cloud calls that aren't user-initiated.
- Never add code that reads Takeout files other than playlists.
- Pages are plain HTML/JS; run `pytest tests/test_html_scripts.py` after editing them.
- Button labels use Title Case with the shortcut at the end, e.g. `Remove From Batch (R)`.
- Never commit databases, audio, or personal exports.

"""Ten-second check that the YouTube-facing pieces still work on this computer, against real YouTube.
Run after an update or a yt-dlp upgrade:   python tools/selfcheck.py   (from the you_commander folder, venv active)

Checks, each with a pass/fail line and the reason on failure:
  1. yt-dlp is importable and its version
  2. captions: fetch the caption track of one public video with captions, parse it, count the lines
  3. channel RSS: fetch one channel's Atom feed and parse it
  4. Shorts probe: one HEAD request answers 200 or a redirect
Nothing is written to the database. One video, one channel: four requests in all."""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
VIDEO = os.environ.get('YC_CHECK_VIDEO', 'jNQXAC9IVRw')            # "Me at the zoo": public, has captions, never going away
CHANNEL = os.environ.get('YC_CHECK_CHANNEL', 'UC4QobU6STFB0P71PMvOGN5A')   # jawed's channel (that video's)
ok = True
def line(name, good, detail=''):
    global ok; ok = ok and good
    print(('PASS' if good else 'FAIL').ljust(6), name.ljust(16), detail)

try:
    import yt_dlp; line('yt-dlp', True, 'version ' + yt_dlp.version.__version__)
except Exception as e:
    line('yt-dlp', False, f'not importable: {e}'); print('\nInstall it with install_transcripts.bat / pip install yt-dlp'); sys.exit(1)

t = time.time()
try:
    import transcripts
    r = transcripts.fetch_captions(VIDEO)
    if r and r.get('cues'): line('captions', True, f"{len(r['cues'])} lines ({r['kind']}, {r['language']}) in {time.time()-t:.1f}s; first: {r['cues'][0][1][:60]!r}")
    else: line('captions', False, 'fetch returned no captions for a video that has them (yt-dlp options or a YouTube change)')
except Exception as e:
    line('captions', False, f'{type(e).__name__}: {str(e)[:200]}')

t = time.time()
try:
    import feed_fetch
    st, res, et, lm = feed_fetch.fetch_feed(CHANNEL)
    if st == 'ok' and res: line('channel rss', True, f'{len(res)} entries in {time.time()-t:.1f}s; newest: {res[0]["title"][:60]!r}' + (' (ETag present)' if et else ''))
    else: line('channel rss', False, f'{st}: {res}')
except Exception as e:
    line('channel rss', False, f'{type(e).__name__}: {str(e)[:200]}')

try:
    r = feed_fetch.probe_short(VIDEO)
    line('shorts probe', r in (0, 1), {1: 'answered: a Short', 0: 'answered: a regular video', None: 'no answer (blocked, or YouTube changed the redirect)'}[r])
except Exception as e:
    line('shorts probe', False, f'{type(e).__name__}: {str(e)[:200]}')

print('\nAll good.' if ok else '\nSomething failed. Paste this output into the chat and it can be fixed from the reason.')
sys.exit(0 if ok else 2)

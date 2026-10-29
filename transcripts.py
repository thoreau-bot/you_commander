"""On-demand video transcripts, kept local.
Captions first (yt-dlp reads the caption track as text, no audio download). Whisper second, only when you ask for it per video:
that path downloads the audio to a temporary file, transcribes it on this machine, and deletes the file.
Never an automatic pass over the library. YouTube's terms do not provide a download for other people's videos; this is a personal,
private reference tool and using it is your call (see the design doc)."""
import os, re, json, sqlite3, threading, time, random, tempfile, shutil
from fastapi.responses import JSONResponse
from pydantic import BaseModel

FAKE = os.environ.get('ORG_TRANSCRIPT_FAKE')   # tests only
SCHEMA = """
create table if not exists transcripts(video_id TEXT, kind TEXT, status TEXT, model TEXT, language TEXT,
  text TEXT, cues TEXT, error TEXT, fetched_at TEXT, PRIMARY KEY(video_id, kind));
create virtual table if not exists transcript_fts using fts5(text, video_id UNINDEXED);
"""

def migrate(c):
    """First version kept one transcript per video (video_transcripts). Carry those over as kind=captions/whisper."""
    if c.execute("select 1 from sqlite_master where name='video_transcripts'").fetchone():
        c.execute("insert or ignore into transcripts(video_id,kind,status,model,language,text,cues,error,fetched_at) "
                  "select video_id,coalesce(source,'captions'),status,model,language,text,cues,error,fetched_at from video_transcripts")
        c.execute("drop table video_transcripts")

def have_ytdlp():
    try:
        import yt_dlp  # noqa
        return True
    except Exception:
        return False

def merge_cues(raw, max_chars=200, max_secs=14.0):
    """raw: [(start, text)] short caption lines -> readable chunks of roughly a sentence or two."""
    out, cs, buf = [], None, ''
    for st, tx in raw:
        tx = re.sub(r'\s+', ' ', tx).strip()
        if not tx: continue
        if cs is None: cs, buf = st, tx
        else: buf += ' ' + tx
        if len(buf) >= max_chars or st - cs >= max_secs or re.search(r'[.?!]["”]?$', buf) and len(buf) > 90:
            out.append((cs, buf)); cs, buf = None, ''
    if buf: out.append((cs, buf))
    return out

def parse_json3(raw):
    d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    lines = []
    for ev in d.get('events', []):
        if 'segs' not in ev: continue
        t = ''.join(s.get('utf8', '') for s in ev['segs']).replace('\n', ' ').strip()
        if t: lines.append((ev.get('tStartMs', 0) / 1000.0, t))
    return merge_cues(lines)

def _pick_track(info):
    pref = [x for x in [info.get('language'), 'en', 'en-US', 'en-GB', 'en-orig'] if x]
    for kind, bag in (('manual', info.get('subtitles') or {}), ('auto', info.get('automatic_captions') or {})):
        keys = [k for k in pref if k in bag] + [k for k in bag if k.startswith('en') and k not in pref]
        for k in keys:
            for f in bag[k]:
                if f.get('ext') == 'json3': return kind, k, f['url']
    return None

def fetch_captions(vid):
    """-> dict(language, kind, cues) or None when the video has no usable English captions."""
    if FAKE:
        if vid[0] in '-_': return None
        return {'language': 'en', 'kind': 'auto', 'cues': merge_cues([(i * 4.0, f'Test caption line {i} for {vid}.') for i in range(400)])}
    import yt_dlp
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True, 'socket_timeout': 25}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info('https://www.youtube.com/watch?v=' + vid, download=False)
        tr = _pick_track(info)
        if not tr: return None
        kind, lang, url = tr
        raw = ydl.urlopen(url).read()
    cues = parse_json3(raw)
    return {'language': lang, 'kind': kind, 'cues': cues} if cues else None

def whisper_audio(vid):
    """Download the audio to a temp folder, transcribe locally, delete the file. -> list[(start,text)]"""
    import voice
    if FAKE: return merge_cues([(i * 5.0, f'Whisper test line {i}.') for i in range(20)])
    import yt_dlp
    d = tempfile.mkdtemp(prefix='org_audio_')
    try:
        opts = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'format': 'bestaudio/best', 'outtmpl': os.path.join(d, '%(id)s.%(ext)s'), 'socket_timeout': 25}
        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download(['https://www.youtube.com/watch?v=' + vid])
        files = [os.path.join(d, f) for f in os.listdir(d)]
        if not files: raise RuntimeError('audio download produced no file')
        return merge_cues(voice.transcribe_segments(files[0]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

class One(BaseModel): method: str = 'captions'; force: bool = False
class Many(BaseModel): tag: int | None = None; ids: list[str] | None = None; force: bool = False

def setup(app, DB):
    c = sqlite3.connect(DB); c.executescript(SCHEMA); migrate(c); c.commit(); c.close()
    JOB = {'running': False, 'total': 0, 'done': 0, 'ok': 0, 'none': 0, 'err': 0, 'current': None, 'method': None, 'note': '', 'cancel': False}
    QUEUE = []   # [(vid, method)]
    LOCK = threading.Lock()

    def con():
        x = sqlite3.connect(DB, timeout=30); x.row_factory = sqlite3.Row; return x

    def reindex(c, vid):
        c.execute("delete from transcript_fts where video_id=?", (vid,))
        txt = ' '.join(r[0] for r in c.execute("select text from transcripts where video_id=? and status='ok' and text is not null", (vid,)))
        if txt: c.execute("insert into transcript_fts(text,video_id) values(?,?)", (txt, vid))

    def save(vid, kind, status, model=None, language=None, cues=None, error=None):
        text = ' '.join(t for _, t in cues) if cues else None
        c = con()
        c.execute("insert into transcripts(video_id,kind,status,model,language,text,cues,error,fetched_at) values(?,?,?,?,?,?,?,?,datetime('now')) "
                  "on conflict(video_id,kind) do update set status=excluded.status,model=excluded.model,language=excluded.language,"
                  "text=excluded.text,cues=excluded.cues,error=excluded.error,fetched_at=excluded.fetched_at",
                  (vid, kind, status, model, language, text, json.dumps(cues) if cues else None, error))
        reindex(c, vid)
        c.commit(); c.close()

    def run_one(vid, method):
        try:
            if method == 'whisper':
                import voice
                cues = whisper_audio(vid)
                save(vid, 'whisper', 'ok', voice.CFG['whisper_model'], voice.CFG['whisper_lang'] or None, cues)
                return 'ok'
            r = fetch_captions(vid)
            if not r:
                save(vid, 'captions', 'none', error='No English captions on this video'); return 'none'
            save(vid, 'captions', 'ok', r['kind'], r['language'], r['cues']); return 'ok'
        except Exception as e:
            msg = str(e)[:300]
            save(vid, method, 'error', error=msg)
            JOB['note'] = msg
            if re.search(r'429|Too Many|Sign in to confirm|bot', msg, re.I): return 'blocked'
            return 'err'

    def worker():
        blocked = 0
        while True:
            with LOCK:
                if not QUEUE or JOB['cancel']:
                    QUEUE.clear(); JOB['running'] = False; JOB['current'] = None; JOB['method'] = None; JOB['cancel'] = False; return
                vid, method = QUEUE.pop(0)
            JOB['current'] = vid; JOB['method'] = method
            r = run_one(vid, method)
            JOB['done'] += 1
            if r == 'blocked':
                JOB['err'] += 1; blocked += 1
                if blocked >= 3:
                    JOB['note'] = 'YouTube is throttling requests. Stopped; wait a while and try again. ' + JOB['note']
                    with LOCK: QUEUE.clear()
                continue
            blocked = 0
            JOB['ok' if r == 'ok' else 'none' if r == 'none' else 'err'] += 1
            if QUEUE and not FAKE: time.sleep(random.uniform(1.5, 3.5))   # be polite

    def enqueue(items, front=False):
        with LOCK:
            have = set(QUEUE)
            new = [(v, m) for v, m in items if (v, m) not in have and (v, m) != (JOB['current'], JOB['method'])]
            if not new: return 0
            if not JOB['running']:
                JOB.update(running=True, total=0, done=0, ok=0, none=0, err=0, note='', cancel=False)
            QUEUE[0:0] = new if front else []
            if not front: QUEUE.extend(new)
            JOB['total'] += len(new)
            if not any(t.name == 'tx-worker' and t.is_alive() for t in threading.enumerate()):
                threading.Thread(target=worker, name='tx-worker', daemon=True).start()
            return len(new)

    @app.get('/api/transcripts/status')
    def t_status():
        try:
            import voice; w = voice.whisper_installed()
        except Exception: w = False
        return {'yt_dlp': have_ytdlp() or bool(FAKE), 'whisper': w, 'job': dict(JOB, queued=len(QUEUE))}

    def is_active(vid, kind): return (JOB['current'], JOB['method']) == (vid, kind) or (vid, kind) in QUEUE

    @app.get('/api/transcript/{vid}')
    def t_get(vid: str):
        c = con(); rows = c.execute("select * from transcripts where video_id=?", (vid,)).fetchall(); c.close()
        out = {}
        for k in ('captions', 'whisper'):
            out[k] = {'status': 'missing', 'active': is_active(vid, k)}
        for r in rows:
            d = dict(r); d['cues'] = json.loads(d['cues']) if d['cues'] else []; d.pop('text', None); d['active'] = is_active(vid, d['kind'])
            d['edited'] = sum(1 for x in d['cues'] if len(x) > 2 and x[2])
            out[d['kind']] = d
        return out

    @app.post('/api/transcript/{vid}')
    def t_start(vid: str, b: One):
        if b.method not in ('captions', 'whisper'): return JSONResponse({'error': 'bad method'}, 400)
        if not b.force:
            c = con(); r = c.execute("select cues from transcripts where video_id=? and kind=? and status='ok'", (vid, b.method)).fetchone(); c.close()
            if r and r['cues'] and any(len(x) > 2 and x[2] for x in json.loads(r['cues'])):
                return {'error': 'This transcript has lines you edited. Delete it first if you want a fresh copy.', 'edited': True}
        if not (have_ytdlp() or FAKE): return {'error': 'yt-dlp is not installed. Run install_transcripts.bat, then restart.'}
        if b.method == 'whisper':
            import voice
            if not (voice.whisper_installed() or FAKE): return {'error': 'Whisper is not installed. Run install_voice.bat.'}
        return {'queued': enqueue([(vid, b.method)], front=True)}

    class CueEdit(BaseModel): kind: str; k: int; text: str
    @app.patch('/api/transcript/{vid}/cue')
    def t_cue(vid: str, b: CueEdit):
        """Correct one transcript line in place. The cue keeps its time; the joined text and the search index follow.
        Edited lines are remembered (cue[2] = 1) so a re-fetch can warn before overwriting them."""
        if b.kind not in ('captions', 'whisper'): return JSONResponse({'error': 'bad kind'}, 400)
        text = re.sub(r'\s+', ' ', b.text).strip()
        if not text: return {'error': 'The line cannot be empty. Delete the transcript instead if it is wrong throughout.'}
        c = con(); r = c.execute("select cues from transcripts where video_id=? and kind=? and status='ok'", (vid, b.kind)).fetchone()
        if not r or not r['cues']: c.close(); return {'error': 'No such transcript'}
        cues = json.loads(r['cues'])
        if not 0 <= b.k < len(cues): c.close(); return {'error': 'No such line'}
        cues[b.k] = [cues[b.k][0], text, 1]
        c.execute("update transcripts set cues=?,text=? where video_id=? and kind=?", (json.dumps(cues), ' '.join(x[1] for x in cues), vid, b.kind))
        reindex(c, vid); c.commit(); c.close()
        return {'ok': 1, 'edited': sum(1 for x in cues if len(x) > 2 and x[2])}

    @app.delete('/api/transcript/{vid}')
    def t_del(vid: str, kind: str = 'captions'):
        c = con(); c.execute("delete from transcripts where video_id=? and kind=?", (vid, kind)); reindex(c, vid); c.commit(); c.close(); return {'ok': 1}

    @app.post('/api/transcripts/queue')
    def t_queue(b: Many):
        if not (have_ytdlp() or FAKE): return {'error': 'yt-dlp is not installed. Run install_transcripts.bat, then restart.'}
        c = con()
        if b.ids: ids = list(dict.fromkeys(b.ids))
        elif b.tag: ids = [r[0] for r in c.execute("select video_id from video_tags where tag_id=?", (b.tag,))]
        else: ids = []
        done = {r[0] for r in c.execute("select video_id from transcripts where kind='captions' and status in ('ok','none')")} if not b.force else set()
        c.close()
        todo = [(v, 'captions') for v in ids if v not in done][:2000]
        return {'queued': enqueue(todo), 'skipped': len(ids) - len(todo)}

    @app.post('/api/transcripts/cancel')
    def t_cancel():
        with LOCK: QUEUE.clear(); JOB['cancel'] = True
        return {'ok': 1}

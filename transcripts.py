"""On-demand video transcripts, kept local.
Captions first (yt-dlp reads the caption track as text, no audio download). Whisper second, only when you ask for it per video:
that path downloads the audio to a temporary file, transcribes it on this machine, and deletes the file.
Never an automatic pass over the library. YouTube's terms do not provide a download for other people's videos; this is a personal,
private reference tool and using it is your call (see the design doc)."""
import os, re, json, sqlite3, threading, time, random, tempfile, shutil
import ytpace
from fastapi.responses import JSONResponse
from pydantic import BaseModel

FAKE = os.environ.get('ORG_TRANSCRIPT_FAKE')   # tests only
QUEUE_LEN = lambda: 0   # set by setup(): how many transcript jobs are queued or running (the feed poller waits for them)
LANES_PUBLIC = lambda: {}; AUDIO_STATS = lambda: {}; KEEP_AUDIO = lambda: False   # set by setup(); read by the Jobs page
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
    # Subtitles only: skip the player JS and the stream-format resolution yt-dlp does by default, which is most of the
    # requests (and most of what trips YouTube's rate limit) for a fetch that never downloads anything.
    # With the player JS skipped there are no stream formats, and yt-dlp's format selector would raise
    # "Requested format is not available" before we read the captions; ignore_no_formats_error lets it carry on.
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True, 'socket_timeout': 25, 'no_color': True,
            'ignore_no_formats_error': True,
            'extractor_args': {'youtube': {'player_skip': ['js', 'configs'], 'player_client': ['web']}}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info('https://www.youtube.com/watch?v=' + vid, download=False)
        tr = _pick_track(info)
        if not tr: return None
        kind, lang, url = tr
        raw = ydl.urlopen(url).read()
    cues = parse_json3(raw)
    return {'language': lang, 'kind': kind, 'cues': cues} if cues else None

def kept_file(store, vid):
    """The kept audio file for a video, if any."""
    if not store or not os.path.isdir(store): return None
    for f in os.listdir(store):
        if f.startswith(vid + '.'): return os.path.join(store, f)
    return None

def whisper_audio(vid, keep=False, store=None):
    """Transcribe locally. The audio comes from the kept copy when there is one (no YouTube request), else it is
    downloaded; with keep on, the download is moved into the store so a later model can re-run without YouTube.
    -> list[(start,text)]"""
    import voice
    if FAKE:
        if os.environ.get('ORG_TRANSCRIPT_FAKE_SLOW'): time.sleep(float(os.environ['ORG_TRANSCRIPT_FAKE_SLOW']))
        if keep and store:
            os.makedirs(store, exist_ok=True)
            if not kept_file(store, vid): open(os.path.join(store, vid + '.m4a'), 'wb').write(b'fake audio')
        return merge_cues([(i * 5.0, f'Whisper test line {i}.') for i in range(20)])
    have = kept_file(store, vid)
    if have: return merge_cues(voice.transcribe_segments(have))
    import yt_dlp
    d = tempfile.mkdtemp(prefix='org_audio_')
    try:
        opts = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'format': 'bestaudio[ext=m4a]/bestaudio/best', 'outtmpl': os.path.join(d, '%(id)s.%(ext)s'), 'socket_timeout': 25,
                'extractor_args': {'youtube': {'player_skip': ['configs']}}}
        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download(['https://www.youtube.com/watch?v=' + vid])
        files = [os.path.join(d, f) for f in os.listdir(d)]
        if not files: raise RuntimeError('audio download produced no file')
        src = files[0]
        if keep and store:
            os.makedirs(store, exist_ok=True)
            dst = os.path.join(store, os.path.basename(src)); shutil.move(src, dst); src = dst
        return merge_cues(voice.transcribe_segments(src))
    finally:
        shutil.rmtree(d, ignore_errors=True)

class One(BaseModel): method: str = 'captions'; force: bool = False
class Many(BaseModel): tag: int | None = None; ids: list[str] | None = None; force: bool = False; method: str = 'captions'

def setup(app, DB):
    c = sqlite3.connect(DB); c.executescript(SCHEMA); migrate(c); c.commit(); c.close()
    # Two lanes. Captions are a few web requests per video; Whisper downloads audio then runs for minutes on this machine.
    # Each lane has its own queue and worker so a long Whisper queue never holds up a caption fetch.
    def _lane(): return {'running': False, 'total': 0, 'done': 0, 'ok': 0, 'none': 0, 'err': 0, 'current': None, 'method': None, 'note': '', 'cancel': False, 'queue': []}
    LANES = {'captions': _lane(), 'whisper': _lane()}
    LOCK = threading.Lock()

    def con():
        x = sqlite3.connect(DB, timeout=30); x.row_factory = sqlite3.Row; return x

    c0 = sqlite3.connect(DB); c0.execute("create table if not exists app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)"); c0.commit(); c0.close()
    def setting(key, default=None):
        c = con(); r = c.execute("select value from app_settings where key=?", (key,)).fetchone(); c.close(); return r[0] if r else default
    def set_setting(key, value):
        c = con(); c.execute("insert into app_settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value", (key, str(value))); c.commit(); c.close()
    def keep_audio(): return setting('keep_audio', '0') == '1'
    def default_store(): return os.path.join(os.environ.get('ORG_AUDIO_DIR') or os.path.join(os.path.dirname(os.path.abspath(DB)), 'audio'), 'whisper')
    def audio_store():
        """Where kept Whisper audio lives: the audio_dir setting (an absolute folder the user chose), else audio/whisper next to the database."""
        return setting('audio_dir') or default_store()
    def free_bytes(path):
        try:
            p = path
            while p and not os.path.isdir(p): p = os.path.dirname(p)
            return shutil.disk_usage(p or '/').free
        except Exception: return None
    def kept_audio_stats():
        st = audio_store(); d = {'files': 0, 'bytes': 0, 'dir': st, 'is_default': not setting('audio_dir'), 'free': free_bytes(st), 'move': dict(MOVE)}
        if os.path.isdir(st):
            fs = [os.path.join(st, f) for f in os.listdir(st)]
            d['files'] = len(fs); d['bytes'] = sum(os.path.getsize(f) for f in fs if os.path.isfile(f))
        return d
    MOVE = {'running': False, 'total': 0, 'done': 0, 'bytes': 0, 'error': None, 'to': None}
    def check_dir(path):
        """-> (abs path, None) or (None, reason). Creates the folder if it does not exist."""
        path = os.path.abspath(os.path.expanduser(path.strip()))
        if not path or path == os.path.abspath(os.sep): return None, 'Pick a folder, not the root of a drive.'
        try: os.makedirs(path, exist_ok=True)
        except Exception as e: return None, f'Cannot create that folder: {e}'
        if not os.path.isdir(path): return None, 'That is not a folder.'
        try:
            t = os.path.join(path, '.yc_write_test'); open(t, 'w').close(); os.remove(t)
        except Exception as e: return None, f'That folder is not writable: {e}'
        return path, None
    def _mover(src, dst):
        try:
            files = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))] if os.path.isdir(src) else []
            MOVE.update(running=True, total=len(files), done=0, bytes=0, error=None, to=dst)
            for f in files:
                a, b = os.path.join(src, f), os.path.join(dst, f)
                if os.path.exists(b) and os.path.getsize(b) == os.path.getsize(a): os.remove(a)
                else: shutil.move(a, b)          # same drive: rename; other drive: copy then delete
                MOVE['done'] += 1; MOVE['bytes'] += os.path.getsize(b) if os.path.exists(b) else 0
            set_setting('audio_dir', '' if dst == default_store() else dst)
        except Exception as e:
            MOVE['error'] = str(e)[:200]
        finally:
            MOVE['running'] = False

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
        JOB = LANES[method]
        try:
            if method == 'whisper':
                import voice
                cues = whisper_audio(vid, keep=keep_audio(), store=audio_store())
                save(vid, 'whisper', 'ok', voice.CFG['whisper_model'], voice.CFG['whisper_lang'] or None, cues)
                return 'ok'
            r = fetch_captions(vid)
            if not r:
                save(vid, 'captions', 'none', error='No English captions on this video'); return 'none'
            save(vid, 'captions', 'ok', r['kind'], r['language'], r['cues']); return 'ok'
        except Exception as e:
            msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e)); msg = re.sub(r'^ERROR:\s*', '', msg).strip()[:300]
            save(vid, method, 'error', error=msg)
            JOB['note'] = msg
            if re.search(r'429|Too Many|Sign in to confirm|bot', msg, re.I):
                ytpace.hit(); return 'blocked'
            return 'err'

    def worker(lane):
        JOB = LANES[lane]; QUEUE = JOB['queue']; blocked = 0
        while True:
            with LOCK:
                if not QUEUE or JOB['cancel']:
                    QUEUE.clear(); JOB['running'] = False; JOB['current'] = None; JOB['method'] = None; JOB['cancel'] = False; return
                vid, method = QUEUE.pop(0)
            JOB['current'] = vid; JOB['method'] = method
            if ytpace.paused() and not FAKE:
                JOB['note'] = 'YouTube asked us to slow down; resuming at ' + (ytpace.resume_at() or '')
                if not ytpace.sleep_if_paused(lambda: JOB['cancel']): continue
                JOB['note'] = ''
            r = run_one(vid, method)
            if r in ('ok', 'none'): ytpace.ok()
            JOB['done'] += 1
            if r == 'blocked':
                JOB['err'] += 1; blocked += 1
                if blocked >= 3:
                    JOB['note'] = 'YouTube is throttling requests. Stopped; wait a while and try again.'
                    with LOCK: QUEUE.clear()
                elif QUEUE and not FAKE:
                    JOB['note'] = 'YouTube asked us to slow down; resuming at ' + (ytpace.resume_at() or '')
                continue
            blocked = 0
            JOB['ok' if r == 'ok' else 'none' if r == 'none' else 'err'] += 1
            if QUEUE and not FAKE: time.sleep(random.uniform(1.5, 3.5))   # be polite

    global QUEUE_LEN
    # the feed poller waits only for the captions lane (YouTube traffic); a Whisper job is local once its audio is in
    QUEUE_LEN = lambda: len(LANES['captions']['queue']) + (1 if LANES['captions']['running'] else 0)

    def enqueue(items, front=False):
        n = 0
        for lane in ('captions', 'whisper'):
            JOB = LANES[lane]; QUEUE = JOB['queue']
            mine = [(v, m) for v, m in items if m == lane]
            if not mine: continue
            with LOCK:
                have = set(QUEUE)
                new = [(v, m) for v, m in mine if (v, m) not in have and (v, m) != (JOB['current'], JOB['method'])]
                if not new: continue
                if not JOB['running']:
                    JOB.update(running=True, total=0, done=0, ok=0, none=0, err=0, note='', cancel=False)
                QUEUE[0:0] = new if front else []
                if not front: QUEUE.extend(new)
                JOB['total'] += len(new)
                if not any(t.name == 'tx-' + lane and t.is_alive() for t in threading.enumerate()):
                    threading.Thread(target=worker, args=(lane,), name='tx-' + lane, daemon=True).start()
                n += len(new)
        return n

    @app.get('/api/transcripts/status')
    def t_status():
        try:
            import voice; w = voice.whisper_installed()
        except Exception: w = False
        def pub(l): d = {k: v for k, v in l.items() if k != 'queue'}; d['queued'] = len(l['queue']); return d
        cj, wj = pub(LANES['captions']), pub(LANES['whisper'])
        # 'job' keeps the old shape (both lanes folded together) for the pages that read it; 'lanes' has each one
        job = {k: (cj[k] + wj[k] if isinstance(cj[k], int) and not isinstance(cj[k], bool) else cj[k] or wj[k]) for k in cj}
        job['running'] = cj['running'] or wj['running']; job['note'] = ' '.join(x for x in (cj['note'], wj['note']) if x)
        return {'yt_dlp': have_ytdlp() or bool(FAKE), 'whisper': w, 'job': job, 'lanes': {'captions': cj, 'whisper': wj}, 'pace': ytpace.status(), 'keep_audio': keep_audio(), 'audio_kept': kept_audio_stats()}

    def is_active(vid, kind):
        l = LANES.get(kind)
        return bool(l) and ((l['current'], l['method']) == (vid, kind) or (vid, kind) in l['queue'])

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
        out['audio_kept'] = bool(kept_file(audio_store(), vid)); out['keep_audio'] = keep_audio(); out['store'] = kept_audio_stats()
        out['pace'] = ytpace.status(); out['note'] = ' '.join(x for x in (LANES['captions']['note'], LANES['whisper']['note']) if x)
        return out

    @app.post('/api/transcript/{vid}')
    def t_start(vid: str, b: One):
        if b.method not in ('captions', 'whisper'): return JSONResponse({'error': 'bad method'}, 400)
        if not b.force:
            c = con(); r = c.execute("select cues from transcripts where video_id=? and kind=? and status='ok'", (vid, b.method)).fetchone(); c.close()
            if r and r['cues'] and any(len(x) > 2 and x[2] for x in json.loads(r['cues'])):
                return {'error': 'This transcript has lines you edited. Delete it first if you want a fresh copy.', 'edited': True}
        if b.method == 'whisper' and b.force:
            c = con(); c.execute("delete from transcripts where video_id=? and kind='whisper'", (vid,)); reindex(c, vid); c.commit(); c.close()
        if not (have_ytdlp() or FAKE): return {'error': 'yt-dlp is not installed. Run install_transcripts.bat, then restart.'}
        if b.method == 'whisper':
            import voice
            if not (voice.whisper_installed() or FAKE): return {'error': 'Whisper is not installed. Run install_voice.bat.'}
        return {'queued': enqueue([(vid, b.method)], front=True)}

    class CueEdit(BaseModel): kind: str; k: int; text: str | None = None; t: float | None = None
    @app.patch('/api/transcript/{vid}/cue')
    def t_cue(vid: str, b: CueEdit):
        """Correct one transcript line in place: its words, its time, or both. The joined text and the search index follow.
        A changed time re-sorts the lines, and the reply carries the line's new index. Edited lines are remembered
        (cue[2] = 1) so a re-fetch can warn before overwriting them."""
        if b.kind not in ('captions', 'whisper'): return JSONResponse({'error': 'bad kind'}, 400)
        if b.text is None and b.t is None: return {'error': 'Nothing to change'}
        c = con(); r = c.execute("select cues from transcripts where video_id=? and kind=? and status='ok'", (vid, b.kind)).fetchone()
        if not r or not r['cues']: c.close(); return {'error': 'No such transcript'}
        cues = json.loads(r['cues'])
        if not 0 <= b.k < len(cues): c.close(); return {'error': 'No such line'}
        t0, text = cues[b.k][0], cues[b.k][1]
        if b.text is not None:
            text = re.sub(r'\s+', ' ', b.text).strip()
            if not text: c.close(); return {'error': 'The line cannot be empty. Delete the transcript instead if it is wrong throughout.'}
        if b.t is not None:
            if b.t < 0 or b.t > 86400: c.close(); return {'error': 'That time is out of range'}
            t0 = round(float(b.t), 2)
        cues[b.k] = [t0, text, 1]
        order = sorted(range(len(cues)), key=lambda i: (cues[i][0], i))
        cues = [cues[i] for i in order]; k2 = order.index(b.k)
        c.execute("update transcripts set cues=?,text=? where video_id=? and kind=?", (json.dumps(cues), ' '.join(x[1] for x in cues), vid, b.kind))
        reindex(c, vid); c.commit(); c.close()
        return {'ok': 1, 'k': k2, 't': t0, 'text': text, 'edited': sum(1 for x in cues if len(x) > 2 and x[2])}

    @app.delete('/api/transcript/{vid}')
    def t_del(vid: str, kind: str = 'captions'):
        c = con(); c.execute("delete from transcripts where video_id=? and kind=?", (vid, kind)); reindex(c, vid); c.commit(); c.close(); return {'ok': 1}

    @app.post('/api/transcripts/queue')
    def t_queue(b: Many):
        if b.method not in ('captions', 'whisper'): return JSONResponse({'error': 'bad method'}, 400)
        if not (have_ytdlp() or FAKE): return {'error': 'yt-dlp is not installed. Run install_transcripts.bat, then restart.'}
        if b.method == 'whisper':
            import voice
            if not (voice.whisper_installed() or FAKE): return {'error': 'Whisper is not installed. Run install_voice.bat, then restart.'}
        c = con()
        if b.ids: ids = list(dict.fromkeys(b.ids))
        elif b.tag: ids = [r[0] for r in c.execute("select video_id from video_tags where tag_id=?", (b.tag,))]
        else: ids = []
        done = {r[0] for r in c.execute("select video_id from transcripts where kind=? and status in ('ok','none')", (b.method,))} if not b.force else set()
        c.close()
        # Three honest numbers: already done (skipped), queued now, and left over if the queue cap was hit.
        # The cap keeps one request from building a multi-day queue by accident; queue the rest with another press.
        CAP = 10000
        want = [(v, b.method) for v in ids if v not in done]
        todo = want[:CAP]
        q = enqueue(todo)
        return {'queued': q, 'skipped': len(ids) - len(want), 'already_queued': len(todo) - q, 'left': len(want) - len(todo)}

    class KeepIn(BaseModel): keep_audio: bool | None = None; audio_dir: str | None = None; move: bool = False
    @app.post('/api/transcripts/settings')
    def t_settings(b: KeepIn):
        """keep_audio toggles keeping. audio_dir sets the folder (empty string = back to the default); with move=True the
        files already kept are moved there in the background (copy + delete when it is another drive)."""
        if b.keep_audio is not None: set_setting('keep_audio', '1' if b.keep_audio else '0')
        if b.audio_dir is not None:
            if MOVE['running']: return {'error': 'A move is still running; wait for it to finish.'}
            cur = audio_store()
            if b.audio_dir.strip() == '': new = default_store(); os.makedirs(new, exist_ok=True)
            else:
                new, why = check_dir(b.audio_dir)
                if why: return {'error': why}
            if os.path.abspath(new) != os.path.abspath(cur):
                if b.move and os.path.isdir(cur) and any(os.path.isfile(os.path.join(cur, f)) for f in os.listdir(cur)):
                    threading.Thread(target=_mover, args=(cur, new), name='audio-move', daemon=True).start()
                else:
                    set_setting('audio_dir', '' if new == default_store() else new)
        return {'ok': 1, 'keep_audio': keep_audio(), 'audio_kept': kept_audio_stats()}

    @app.get('/api/transcripts/audio')
    def t_audio_info(): return kept_audio_stats()

    @app.delete('/api/transcript/{vid}/audio')
    def t_audio_del(vid: str):
        f = kept_file(audio_store(), vid)
        if f: os.remove(f)
        return {'ok': 1, 'removed': bool(f)}

    @app.post('/api/transcripts/audio/clear')
    def t_audio_clear():
        st = audio_store(); n = 0
        if os.path.isdir(st):
            for f in os.listdir(st):
                p = os.path.join(st, f)
                if os.path.isfile(p): os.remove(p); n += 1
        return {'ok': 1, 'removed': n}

    @app.post('/api/transcripts/cancel')
    def t_cancel(lane: str | None = None):
        with LOCK:
            for k, l in LANES.items():
                if lane and k != lane: continue
                l['queue'].clear(); l['cancel'] = True
        return {'ok': 1}

    def lanes_public():
        out = {}
        c = con()
        for k, l in LANES.items():
            d = {x: v for x, v in l.items() if x != 'queue'}; d['queued'] = len(l['queue'])
            if l['current']:
                r = c.execute("select title from videos where video_id=?", (l['current'],)).fetchone(); d['current_title'] = r[0] if r else None
            d['next'] = [v for v, _ in l['queue'][:5]]
            out[k] = d
        c.close(); return out
    global LANES_PUBLIC, AUDIO_STATS, KEEP_AUDIO
    LANES_PUBLIC, AUDIO_STATS, KEEP_AUDIO = lanes_public, kept_audio_stats, keep_audio

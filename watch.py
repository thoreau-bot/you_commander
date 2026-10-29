"""Watch page + our own watch history (local only). Tables: watch_state (one row per video), watch_log (one row per open), video_marks (timestamped notes)."""
import os, sqlite3, threading, time
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

SCHEMA = """
create table if not exists watch_state(video_id TEXT PRIMARY KEY, last_pos REAL DEFAULT 0, duration REAL DEFAULT 0, seconds REAL DEFAULT 0,
  plays INTEGER DEFAULT 0, speed REAL DEFAULT 1, loop_a REAL, loop_b REAL, last_watched TEXT, first_watched TEXT);
create table if not exists watch_log(id INTEGER PRIMARY KEY, video_id TEXT, source TEXT, opened_at TEXT DEFAULT (datetime('now')), seconds REAL DEFAULT 0, end_pos REAL DEFAULT 0);
create table if not exists video_marks(id INTEGER PRIMARY KEY, video_id TEXT, t REAL, body TEXT, source TEXT DEFAULT 'typed', created_at TEXT DEFAULT (datetime('now')));
create index if not exists ix_marks_v on video_marks(video_id);
create index if not exists ix_log_v on watch_log(video_id);
"""

class Open(BaseModel): source: str = 'watch'
class Ping(BaseModel):
    pos: float = 0; dur: float = 0; delta: float = 0; speed: float | None = None
    loop_a: float | None = None; loop_b: float | None = None; log_id: int | None = None; clear_loop: bool = False
class Mark(BaseModel): t: float; body: str; quote: str | None = None
class MarkEdit(BaseModel): body: str
class QueueIn(BaseModel):
    tag: int | None = None; ids: list[str] | None = None

on_change=lambda:None
def setup(app, DB, video_fn, audio_dir=None):
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    have = [r[1] for r in c.execute("pragma table_info(video_marks)")]
    for col, ddl in (('quote', 'TEXT'), ('status', "TEXT DEFAULT 'ok'"), ('audio_path', 'TEXT')):
        if col not in have: c.execute(f"alter table video_marks add column {col} {ddl}")
    c.commit(); c.close()
    audio_dir = audio_dir or os.path.join(os.path.dirname(os.path.abspath(DB)), 'audio')
    def con():
        x = sqlite3.connect(DB, timeout=30); x.row_factory = sqlite3.Row
        try:
            import feed_fetch; feed_fetch.touch()   # someone is using the app: the feed poller stays out of the way
        except Exception: pass
        return x
    def page(name):
        return HTMLResponse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), encoding='utf-8').read())

    @app.get('/watch', response_class=HTMLResponse)
    def watch_page(): return page('watch.html')
    @app.get('/history', response_class=HTMLResponse)
    def history_page(): return page('history.html')

    @app.post('/api/watch/{vid}/open')
    def w_open(vid: str, b: Open):
        c = con()
        c.execute("insert into watch_state(video_id,plays,last_watched,first_watched) values(?,1,datetime('now'),datetime('now')) "
                  "on conflict(video_id) do update set plays=plays+1,last_watched=datetime('now')", (vid,))
        lid = c.execute("insert into watch_log(video_id,source) values(?,?)", (vid, b.source[:20])).lastrowid
        c.commit()
        st = dict(c.execute("select * from watch_state where video_id=?", (vid,)).fetchone()); c.close()
        return {'log_id': lid, 'state': st}

    @app.post('/api/watch/{vid}/ping')
    def w_ping(vid: str, p: Ping):
        d = max(0.0, min(p.delta, 120.0))  # a ping never adds more than 2 minutes
        c = con()
        c.execute("insert or ignore into watch_state(video_id,first_watched) values(?,datetime('now'))", (vid,))
        c.execute("update watch_state set last_pos=?, duration=case when ?>0 then ? else duration end, seconds=seconds+?, last_watched=datetime('now') where video_id=?",
                  (max(0, p.pos), p.dur, p.dur, d, vid))
        if p.speed: c.execute("update watch_state set speed=? where video_id=?", (p.speed, vid))
        if p.clear_loop: c.execute("update watch_state set loop_a=null,loop_b=null where video_id=?", (vid,))
        elif p.loop_a is not None or p.loop_b is not None:
            c.execute("update watch_state set loop_a=?,loop_b=? where video_id=?", (p.loop_a, p.loop_b, vid))
        if p.log_id: c.execute("update watch_log set seconds=seconds+?, end_pos=? where id=? and video_id=?", (d, p.pos, p.log_id, vid))
        c.commit(); c.close(); return {'ok': 1}

    @app.get('/api/watch/{vid}')
    def w_get(vid: str):
        v = video_fn(vid)
        if not v: return JSONResponse({'error': 'unknown video'}, 404)
        c = con()
        st = c.execute("select * from watch_state where video_id=?", (vid,)).fetchone()
        v['state'] = dict(st) if st else None
        v['marks'] = [dict(r) for r in c.execute("select id,t,body,source,quote,status from video_marks where video_id=? order by t,id", (vid,))]
        c.close(); return v

    @app.post('/api/watch/{vid}/marks')
    def w_mark(vid: str, m: Mark):
        if not m.body.strip(): return {'error': 'empty'}
        c = con(); i = c.execute("insert into video_marks(video_id,t,body,quote) values(?,?,?,?)", (vid, max(0, m.t), m.body.strip(), (m.quote or '').strip()[:600] or None)).lastrowid; on_change()
        c.commit(); c.close(); return {'id': i}

    @app.post('/api/watch/{vid}/marks/voice')
    async def w_mark_voice(vid: str, request: Request, t: float = 0, quote: str = ''):
        """A spoken note pinned to a moment (and optionally a quoted line). Audio is kept; the transcript fills in the note text."""
        data = await request.body()
        if len(data) < 500: return {'error': 'recording too short'}
        ct = request.headers.get('content-type') or ''
        ext = 'webm' if 'webm' in ct else 'ogg' if 'ogg' in ct else 'bin'
        os.makedirs(audio_dir, exist_ok=True)
        path = os.path.join(audio_dir, f"{vid}_mark_{int(time.time() * 1000)}.{ext}")
        with open(path, 'wb') as f: f.write(data)
        c = con()
        mid = c.execute("insert into video_marks(video_id,t,body,source,quote,status,audio_path) values(?,?,?,?,?,?,?)",
                        (vid, max(0, t), '', 'voice', quote.strip()[:600] or None, 'transcribing', path)).lastrowid
        c.commit(); c.close()
        def work():
            body, st = '', 'ok'
            try:
                import voice
                body = voice.transcribe(path) or ''
                if not body: body, st = '(nothing was heard)', 'ok'
            except Exception as e:
                body, st = 'Voice note saved, but it could not be transcribed: ' + str(e)[:160], 'error'
            x = con(); x.execute("update video_marks set body=?,status=? where id=?", (body, st, mid)); x.commit(); x.close()
        threading.Thread(target=work, daemon=True).start()
        return {'id': mid}

    @app.get('/api/watch/marks/{mid}')
    def w_markget(mid: int):
        c = con(); r = c.execute("select id,t,body,source,quote,status from video_marks where id=?", (mid,)).fetchone(); c.close()
        return dict(r) if r else JSONResponse({'error': 'gone'}, 404)

    @app.patch('/api/watch/marks/{mid}')
    def w_markedit(mid: int, b: MarkEdit):
        c = con(); c.execute("update video_marks set body=? where id=?", (b.body.strip(), mid)); c.commit(); c.close(); on_change(); return {'ok': 1}

    @app.delete('/api/watch/marks/{mid}')
    def w_markdel(mid: int):
        c = con(); c.execute("delete from video_marks where id=?", (mid,)); c.commit(); c.close(); on_change(); return {'ok': 1}

    @app.post('/api/watch/queue')
    def w_queue(b: QueueIn):
        c = con()
        base = "select v.video_id,v.title,v.channel,s.last_pos,s.duration,s.plays from videos v left join watch_state s using(video_id)"
        if b.ids:
            ids = list(dict.fromkeys(b.ids))[:500]
            rows = {r['video_id']: dict(r) for r in c.execute(base + " where v.video_id in (%s)" % ','.join('?' * len(ids)), ids)}
            out = [rows[i] for i in ids if i in rows]
        elif b.tag:
            out = [dict(r) for r in c.execute(base + " where v.video_id in (select video_id from video_tags where tag_id=?) order by (v.title is null), v.title collate nocase limit 1000", (b.tag,))]
        else: out = []
        c.close(); return out

    @app.get('/api/history')
    def w_history(limit: int = 300, offset: int = 0):
        c = con()
        rows = [dict(r) for r in c.execute(
            "select s.video_id,v.title,v.channel,s.last_pos,s.duration,s.seconds,s.plays,s.last_watched,s.first_watched,"
            "(select count(*) from video_marks m where m.video_id=s.video_id) marks, "
            "(select source from watch_log l where l.video_id=s.video_id order by l.id desc limit 1) src "
            "from watch_state s left join videos v using(video_id) order by s.last_watched desc limit ? offset ?", (limit, offset))]
        tot = c.execute("select count(*),coalesce(sum(seconds),0) from watch_state").fetchone()
        c.close(); return {'items': rows, 'videos': tot[0], 'seconds': tot[1]}

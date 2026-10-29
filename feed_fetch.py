"""Feed, step 2: new videos from the channels in the library.

Candidates come from each channel's public Atom feed (youtube.com/feeds/videos.xml?channel_id=UC…): the latest ~15 uploads
with title, published time, description, thumbnail and a view count. No key, no quota, no sign-in. Conditional GETs
(ETag / If-Modified-Since) make an unchanged feed a 304 and nearly free.

Shorts are told apart with one HEAD request per new item (youtube.com/shorts/<id> is 200 for a Short, a redirect for a
regular video). Nothing is fetched for an item beyond that.

Network use is off until the user presses Fetch New Videos once. After that first full pass, polling runs on its own
on a tiered schedule (hourly for channels the user watches, daily for the long tail) and can be switched off on the
Feed page. See docs/PRIVACY.md.
"""
import os, re, json, sqlite3, threading, time, random, gzip, urllib.request, urllib.error, datetime as dt
import xml.etree.ElementTree as ET
import ytpace

FAKE = os.environ.get('ORG_FEED_FAKE')   # tests only: Atom from tests/fixtures/feed/<channel_id>.xml, no network
FIX = os.environ.get('ORG_FEED_FIXTURES') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tests', 'fixtures', 'feed')
SCHEMA = """
create table if not exists feed_items(
  video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, published_at TEXT NOT NULL,
  updated_at TEXT, thumb_url TEXT, duration_s INTEGER, views INTEGER, views_at TEXT, likes INTEGER, rating_n INTEGER,
  is_short INTEGER, is_short_src TEXT, first_seen TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'new', state_at TEXT,
  base_score REAL, score_json TEXT, scored_at TEXT);
create index if not exists ix_feed_state on feed_items(state, is_short, published_at desc);
create index if not exists ix_feed_chan on feed_items(channel_id, published_at desc);
create table if not exists feed_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
create table if not exists feed_log(id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, channels INTEGER, new_items INTEGER,
  unchanged INTEGER, failed INTEGER, seconds REAL, note TEXT);
"""
# polling tiers, in hours between polls. 'auto' picks from library signals; a channel row can pin one.
TIERS = {'hourly': 1, 'sixhourly': 6, 'daily': 24, 'off': None}
JOB = dict(running=False, kind='', total=0, done=0, new=0, unchanged=0, failed=0, started=None, finished=None, note='', cancel=False)
LOCK = threading.Lock()
POLLER = dict(thread=None, stop=False)
UA = 'Mozilla/5.0 (YouCommander/1.9; local-first; contact: none)'

def now(): return dt.datetime.utcnow().isoformat(timespec='seconds')

def ensure_schema(path):
    c = sqlite3.connect(path); c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute('pragma table_info(channels)')}
    for col, ddl in (('tier', "TEXT NOT NULL DEFAULT 'auto'"), ('last_modified', 'TEXT'), ('fail_n', 'INTEGER NOT NULL DEFAULT 0')):
        if col not in cols: c.execute(f'alter table channels add column {col} {ddl}')
    c.commit(); c.close()

def setting(c, key, default=None):
    r = c.execute("select value from feed_settings where key=?", (key,)).fetchone()
    return r[0] if r else default

def set_setting(c, key, value):
    c.execute("insert into feed_settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value", (key, str(value)))

# ---------------------------------------------------------------- Atom
def _local(tag): return tag.rsplit('}', 1)[-1]

def parse_atom(raw):
    """Atom bytes -> list of dicts. Namespace-agnostic so a prefix change on YouTube's side does not break it."""
    root = ET.fromstring(raw)
    out = []
    for e in root.iter():
        if _local(e.tag) != 'entry': continue
        d = dict(video_id=None, title=None, published=None, updated=None, description=None, thumb=None, views=None, rating_n=None, link=None)
        for ch in e.iter():
            t = _local(ch.tag)
            if t == 'videoId': d['video_id'] = (ch.text or '').strip()
            elif t == 'title' and d['title'] is None: d['title'] = (ch.text or '').strip()
            elif t == 'published': d['published'] = (ch.text or '').strip()
            elif t == 'updated': d['updated'] = (ch.text or '').strip()
            elif t == 'description': d['description'] = (ch.text or '').strip()
            elif t == 'thumbnail': d['thumb'] = ch.get('url')
            elif t == 'statistics':
                try: d['views'] = int(ch.get('views') or 0)
                except ValueError: pass
            elif t == 'starRating':
                try: d['rating_n'] = int(ch.get('count') or 0)
                except ValueError: pass
            elif t == 'link' and ch.get('rel') == 'alternate': d['link'] = ch.get('href')
        if d['video_id'] and d['title'] and d['published']:
            if not d['video_id'] and d['link']:
                m = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', d['link']); d['video_id'] = m.group(1) if m else None
            out.append(d)
    return out

def iso_utc(s):
    """Atom times carry an offset (2026-10-27T18:00:00+00:00). Store as naive UTC ISO so SQLite string order is time order."""
    try:
        t = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        if t.tzinfo: t = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return t.isoformat(timespec='seconds')
    except Exception:
        return s

# ---------------------------------------------------------------- one channel
def fetch_feed(channel_id, etag=None, last_modified=None):
    """-> ('ok', entries, etag, last_modified) | ('unchanged', None, etag, lm) | ('fail', reason, None, None)"""
    if FAKE:
        if os.environ.get('ORG_FEED_FAKE_SLOW'): time.sleep(float(os.environ['ORG_FEED_FAKE_SLOW']))   # tests: hold each fetch so a pass stays running
        p = os.path.join(FIX, f'{channel_id}.xml')
        if not os.path.exists(p): return 'fail', 'fake: no feed', None, None
        tag = str(int(os.path.getmtime(p)))
        if etag == tag: return 'unchanged', None, tag, None
        try: return 'ok', parse_atom(open(p, 'rb').read()), tag, None
        except ET.ParseError as e: return 'fail', f'parse: {e}', None, None
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    h = {'User-Agent': UA, 'Accept': 'application/atom+xml, application/xml;q=0.9, */*;q=0.5', 'Accept-Encoding': 'gzip'}
    if etag: h['If-None-Match'] = etag
    if last_modified: h['If-Modified-Since'] = last_modified
    for attempt in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
                raw = r.read(4_000_000)
                if r.headers.get('Content-Encoding') == 'gzip': raw = gzip.decompress(raw)
                return 'ok', parse_atom(raw), r.headers.get('ETag'), r.headers.get('Last-Modified')
        except urllib.error.HTTPError as e:
            if e.code == 304: return 'unchanged', None, etag, last_modified
            if e.code in (404, 410): return 'fail', f'http {e.code}', None, None
            if e.code == 429: ytpace.hit(); return 'fail', 'http 429', None, None
            if attempt: return 'fail', f'http {e.code}', None, None
            time.sleep(2)
        except ET.ParseError as e:
            return 'fail', f'parse: {str(e)[:80]}', None, None
        except Exception as e:
            if attempt: return 'fail', f'{type(e).__name__}', None, None
            time.sleep(2)
    return 'fail', 'unreachable', None, None

def probe_short(video_id):
    """-> 1 (Short), 0 (regular), None (could not tell). One HEAD request, no cookies, no redirect following."""
    if FAKE:
        return 1 if video_id.startswith('S') else None if video_id.startswith('U') else 0
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    op = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(f'https://www.youtube.com/shorts/{video_id}', method='HEAD', headers={'User-Agent': UA})
    try:
        with op.open(req, timeout=15) as r: return 1 if r.status == 200 else None
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308): return 0
        if e.code == 429: ytpace.hit()
        return None
    except Exception:
        return None

def upsert_entries(c, channel_id, entries):
    """Insert new items, refresh views/title on known ones. Returns the count of new rows."""
    new = 0; t = now()
    for d in entries:
        pub = iso_utc(d['published'])
        r = c.execute("select 1 from feed_items where video_id=?", (d['video_id'],)).fetchone()
        if r:
            c.execute("update feed_items set title=?,description=coalesce(?,description),views=coalesce(?,views),views_at=case when ? is null then views_at else ? end,rating_n=coalesce(?,rating_n),updated_at=? where video_id=?",
                      (d['title'], d['description'], d['views'], d['views'], t, d['rating_n'], iso_utc(d['updated'] or ''), d['video_id']))
        else:
            c.execute("""insert into feed_items(video_id,channel_id,title,description,published_at,updated_at,thumb_url,views,views_at,rating_n,first_seen,state)
                         values(?,?,?,?,?,?,?,?,?,?,?,'new')""",
                      (d['video_id'], channel_id, d['title'], d['description'], pub, iso_utc(d['updated'] or ''), d['thumb'], d['views'], t if d['views'] is not None else None, d['rating_n'], t))
            new += 1
    # already in the library? then it is not "new to you"; keep the row (stats, dedupe) but out of the feed
    new -= c.execute("update feed_items set state='seen',state_at=? where channel_id=? and state='new' and first_seen=? and video_id in (select video_id from videos)", (t, channel_id, t)).rowcount
    return new

# ---------------------------------------------------------------- tiers
def compute_tiers(c):
    """auto tier from library signals: watched / noted / 3+ saved -> hourly; 2 saved -> sixhourly; else daily."""
    rows = c.execute("""select ch.channel_id,
         (select count(*) from video_channel x where x.channel_id=ch.channel_id) n,
         (select count(*) from video_channel x join watch_log w on w.video_id=x.video_id where x.channel_id=ch.channel_id) watched,
         (select count(*) from video_channel x where x.channel_id=ch.channel_id and (exists(select 1 from notes nt where nt.video_id=x.video_id) or exists(select 1 from video_marks m where m.video_id=x.video_id))) noted
         from channels ch""").fetchall()
    out = {}
    for cid, n, watched, noted in rows:
        out[cid] = 'hourly' if (watched or noted or n >= 3) else 'sixhourly' if n == 2 else 'daily'
    return out

def effective_tier(row_tier, auto_tier): return auto_tier if row_tier == 'auto' else row_tier

def due_channels(c, all_channels=False):
    auto = compute_tiers(c)
    rows = c.execute("select channel_id,tier,last_polled,muted,poll_enabled,fail_n from channels").fetchall()
    due = []; t = dt.datetime.utcnow()
    for cid, tier, lp, muted, pe, fail_n in rows:
        if not pe: continue
        eff = effective_tier(tier, auto.get(cid, 'daily'))
        hrs = TIERS.get(eff)
        if hrs is None: continue
        if all_channels or not lp: due.append(cid); continue
        try: age = (t - dt.datetime.fromisoformat(lp)).total_seconds() / 3600
        except Exception: age = 1e9
        if fail_n >= 3: hrs = max(hrs, 24)      # a channel that keeps failing is checked daily at most
        if age >= hrs * 0.95: due.append(cid)
    return due

# ---------------------------------------------------------------- the pass
def run_pass(path, kind, channel_ids=None, workers=4):
    """One pass over the due channels (or the given ones). kind: 'first' | 'poll' | 'manual'."""
    c = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level='DEFERRED')
    c.execute('pragma busy_timeout=30000')
    try:
        ids = channel_ids if channel_ids is not None else due_channels(c, all_channels=(kind in ('first', 'manual')))   # the button checks everything; only the poller goes by tier
        JOB.update(kind=kind, total=len(ids), done=0, new=0, unchanged=0, failed=0, note='', started=time.time(), finished=None)
        meta = {r[0]: (r[1], r[2]) for r in c.execute("select channel_id,etag,last_modified from channels")}
        idx, lk, t0 = [0], threading.Lock(), time.time()
        new_ids = []
        def work():
            while not JOB['cancel'] and not POLLER['stop']:
                if ytpace.paused() and not FAKE:
                    JOB['note'] = 'YouTube asked us to slow down; resuming at ' + (ytpace.resume_at() or '')
                    if not ytpace.sleep_if_paused(lambda: JOB['cancel'] or POLLER['stop']): return
                    JOB['note'] = ''
                with lk:
                    if idx[0] >= len(ids): return
                    cid = ids[idx[0]]; idx[0] += 1
                et, lm = meta.get(cid, (None, None))
                st, res, et2, lm2 = fetch_feed(cid, et, lm)
                if st in ('ok', 'unchanged'): ytpace.ok()
                with lk:
                    # one short write transaction per channel, committed at once, so the pages never wait on this worker
                    if st == 'ok':
                        n = upsert_entries(c, cid, res)
                        new_ids.extend(d['video_id'] for d in res)
                        last = max((iso_utc(d['published']) for d in res), default=None)
                        c.execute("update channels set etag=?,last_modified=?,last_polled=?,poll_error=NULL,fail_n=0,last_video_at=coalesce(?,last_video_at) where channel_id=?", (et2, lm2, now(), last, cid))
                        JOB['new'] += n
                    elif st == 'unchanged':
                        c.execute("update channels set last_polled=?,poll_error=NULL,fail_n=0 where channel_id=?", (now(), cid)); JOB['unchanged'] += 1
                    else:
                        c.execute("update channels set last_polled=?,poll_error=?,fail_n=fail_n+1 where channel_id=?", (now(), res, cid)); JOB['failed'] += 1
                        if res == 'http 429':
                            JOB['note'] = 'YouTube asked us to slow down; resuming at ' + (ytpace.resume_at() or '')
                    JOB['done'] += 1
                    c.commit()
                if not FAKE: time.sleep(random.uniform(0.25, 0.6))   # ~4 workers -> ~8 requests/s at most
        ths = [threading.Thread(target=work, daemon=True) for _ in range(1 if FAKE else workers)]
        [t.start() for t in ths]; [t.join() for t in ths]
        c.commit()
        # Shorts probe for anything still unknown (new this pass, or left over)
        # Shorts probe: newest first, at most 500 per pass and about one a second, so a backlog drains over several
        # wake-ups instead of as one burst that eats the address's rate budget (captions share it)
        todo = [r[0] for r in c.execute("select video_id from feed_items where is_short is null and state in ('new','seen') order by published_at desc limit 500")]
        JOB.update(kind=kind + ':shorts', total=len(todo), done=0)
        for vid in todo:
            if JOB['cancel'] or POLLER['stop']: break
            if ytpace.paused() and not FAKE:
                JOB['note'] = 'YouTube asked us to slow down; resuming at ' + (ytpace.resume_at() or '')
                if not ytpace.sleep_if_paused(lambda: JOB['cancel'] or POLLER['stop']): break
                JOB['note'] = ''
            r = probe_short(vid)   # network first, outside any transaction
            if r is not None: ytpace.ok()
            if r is not None: c.execute("update feed_items set is_short=?,is_short_src='probe' where video_id=?", (r, vid)); c.commit()
            JOB['done'] += 1
            if not FAKE: time.sleep(random.uniform(0.8, 1.3))
        c.commit()
        c.execute("insert into feed_log(at,kind,channels,new_items,unchanged,failed,seconds,note) values(?,?,?,?,?,?,?,?)",
                  (now(), kind, len(ids), JOB['new'], JOB['unchanged'], JOB['failed'], round(time.time() - t0, 1), JOB['note'] or None))
        if kind == 'first' and not JOB['cancel']:
            set_setting(c, 'first_pass_at', now()); set_setting(c, 'polling', setting(c, 'polling', '1'))
        c.commit()
    except Exception as e:
        JOB['note'] = str(e)[:300]
    finally:
        c.close(); JOB.update(running=False, finished=time.time())

def start_pass(path, kind, channel_ids=None):
    with LOCK:
        if JOB['running']: return False
        JOB.update(running=True, cancel=False, kind=kind, total=0, done=0, new=0, unchanged=0, failed=0, note='')
    threading.Thread(target=run_pass, args=(path, kind, channel_ids), name='feed-fetch', daemon=True).start(); return True

LAST_USER_ACTION = [0.0]
def touch():
    """Called by the app on every foreground write, so the poller stays out of the way while someone is using it."""
    LAST_USER_ACTION[0] = time.time()

def _poll_loop(path):
    """Every ~10 min, see what is due; run a pass for it. Off until first_pass_at is set and polling = 1.
    Waits 90 s after startup (the pages come up first), and holds off while the app was used in the last 2 minutes."""
    grace = int(os.environ.get('ORG_FEED_POLL_GRACE', '90'))
    for _ in range(grace):
        if POLLER['stop']: return
        time.sleep(1)
    while not POLLER['stop']:
        try:
            tx_busy = False
            try:
                import transcripts; tx_busy = bool(transcripts.QUEUE_LEN())
            except Exception: pass
            if time.time() - LAST_USER_ACTION[0] > 120 and not JOB['running'] and not tx_busy and not ytpace.paused():
                c = sqlite3.connect(path, timeout=30); c.execute('pragma busy_timeout=30000')
                on = setting(c, 'polling', '0') == '1' and setting(c, 'first_pass_at')
                due = due_channels(c) if on else []
                c.close()
                if due:
                    start_pass(path, 'poll', due[:400])   # at most 400 channels per wake-up, so a backlog never becomes a long lock-out
                    while JOB['running'] and not POLLER['stop']: time.sleep(1)
        except Exception:
            pass
        for _ in range(int(os.environ.get('ORG_FEED_POLL_SECS', '600'))):
            if POLLER['stop']: return
            time.sleep(1)

def start_poller(path):
    if os.environ.get('ORG_FEED_NO_POLLER'): return
    if POLLER['thread'] and POLLER['thread'].is_alive(): return
    POLLER['stop'] = False
    POLLER['thread'] = threading.Thread(target=_poll_loop, args=(path,), name='feed-poller', daemon=True); POLLER['thread'].start()

# ---------------------------------------------------------------- queries
def items(c, view='newest', limit=200, offset=0, shorts=None, channel=None, q=None):
    where = ["i.state='new'", "ch.muted=0"]; a = []
    if shorts == 'only': where.append("i.is_short=1")
    elif shorts == 'hide': where.append("coalesce(i.is_short,0)=0")
    if channel: where.append("i.channel_id=?"); a.append(channel)
    if q:
        where.append("(i.title like ? or ch.title like ?)"); a += [f'%{q}%', f'%{q}%']
    order = "i.published_at desc" if view == 'newest' else "i.published_at desc"
    sql = f"""select i.video_id,i.title,i.published_at,i.thumb_url,i.views,i.views_at,i.is_short,i.duration_s,i.first_seen,
                     ch.channel_id,ch.title channel,ch.handle
              from feed_items i join channels ch on ch.channel_id=i.channel_id where {' and '.join(where)} order by {order} limit ? offset ?"""
    return [dict(r) for r in c.execute(sql, a + [limit, offset])]

def summary(c):
    s = dict(first_pass_at=setting(c, 'first_pass_at'), polling=setting(c, 'polling', '0') == '1')
    s['new'] = c.execute("select count(*) from feed_items i join channels ch using(channel_id) where i.state='new' and ch.muted=0").fetchone()[0]
    s['new_shorts'] = c.execute("select count(*) from feed_items i join channels ch using(channel_id) where i.state='new' and ch.muted=0 and i.is_short=1").fetchone()[0]
    s['unknown_len'] = c.execute("select count(*) from feed_items where state='new' and is_short is null").fetchone()[0]
    s['channels'] = c.execute("select count(*) from channels where poll_enabled=1 and muted=0").fetchone()[0]
    s['last_polled'] = c.execute("select max(last_polled) from channels").fetchone()[0]
    s['failing'] = c.execute("select count(*) from channels where fail_n>=3").fetchone()[0]
    last = c.execute("select * from feed_log order by id desc limit 1").fetchone()
    s['last_run'] = dict(last) if last else None
    auto = compute_tiers(c)
    rows = c.execute("select channel_id,tier from channels where poll_enabled=1 and muted=0").fetchall()
    tc = {}
    for cid, tier in rows:
        e = effective_tier(tier, auto.get(cid, 'daily')); tc[e] = tc.get(e, 0) + 1
    s['tiers'] = tc
    return s

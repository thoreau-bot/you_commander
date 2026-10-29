"""Feed, step 1: channel identity.

The library knows each video's channel by *title* (oEmbed `author_name`) and, from 1.9 on, by the channel's page URL
(`author_url`, e.g. https://www.youtube.com/@handle). The feed needs the channel's stable `UC…` id, which is what the
per-channel RSS feed is keyed on. Resolving goes in two phases, both started by the user from the Feed page:

  A. videos with a title but no `channel_url` get one more oEmbed lookup (no key, no quota), stored in videos.channel_url
  B. every distinct `channel_url` is turned into a `UC…` id: read straight off a /channel/UC… URL, otherwise by fetching
     the channel page once and reading its canonical id (yt-dlp as a fallback when installed)

Every video is then linked to its channel in `video_channel`. Channels are keyed on the id, never on the title, so two
channels that share a name stay two channels. Network use: one oEmbed call per video in phase A, one page fetch per
distinct channel in phase B, nothing automatic. See docs/PRIVACY.md.
"""
import os, re, json, sqlite3, threading, time, random, urllib.request, urllib.error, urllib.parse, datetime as dt
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

FAKE = os.environ.get('ORG_FEED_FAKE')   # tests only: no network, channel pages are invented
SCHEMA = """
create table if not exists channels(
  channel_id TEXT PRIMARY KEY, title TEXT NOT NULL, handle TEXT, channel_url TEXT, resolved_from TEXT,
  poll_enabled INTEGER NOT NULL DEFAULT 1, muted INTEGER NOT NULL DEFAULT 0, shorts_mode TEXT NOT NULL DEFAULT 'show',
  etag TEXT, last_polled TEXT, last_video_at TEXT, poll_error TEXT, created_at TEXT NOT NULL);
create table if not exists video_channel(video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL);
create index if not exists ix_video_channel_ch on video_channel(channel_id);
create table if not exists channel_unresolved(channel_url TEXT PRIMARY KEY, title TEXT, error TEXT, tried_at TEXT, n INTEGER DEFAULT 0);
"""
UC = re.compile(r'(UC[A-Za-z0-9_-]{22})')
JOB = dict(running=False, phase='', total=0, done=0, ok=0, failed=0, started=None, finished=None, note='', cancel=False)
LOCK = threading.Lock()

def now(): return dt.datetime.utcnow().isoformat(timespec='seconds')

def ensure_schema(path):
    c = sqlite3.connect(path); c.executescript(SCHEMA); c.commit(); c.close()

# ---------------------------------------------------------------- URL shapes
def id_from_url(url):
    """/channel/UC… URLs carry the id in the clear."""
    m = re.search(r'/channel/(UC[A-Za-z0-9_-]{22})', url or '')
    return m.group(1) if m else None

def handle_from_url(url):
    m = re.search(r'youtube\.com/(@[^/?#]+)', url or '')
    return urllib.parse.unquote(m.group(1)) if m else None

# ---------------------------------------------------------------- phase B: channel page -> UC id
def _page_id(url):
    """Fetch the channel page once and read its canonical UC id. Returns (id, how) or (None, error)."""
    if FAKE:
        if 'nochannel' in url: return None, 'fake: no such channel'
        import hashlib
        return 'UC' + hashlib.sha1(url.encode()).hexdigest()[:22].replace('a', '_'), 'page'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (YouCommander/1.9)', 'Accept-Language': 'en'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                final = r.geturl()
                m = id_from_url(final)
                if m: return m, 'redirect'
                html = r.read(1_500_000).decode('utf-8', 'replace')
            for pat in (r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"',
                        r'<meta itemprop="identifier" content="(UC[A-Za-z0-9_-]{22})"',
                        r'"channelId":"(UC[A-Za-z0-9_-]{22})"', r'"externalId":"(UC[A-Za-z0-9_-]{22})"'):
                m = re.search(pat, html)
                if m: return m.group(1), 'page'
            return None, 'page had no channel id'
        except urllib.error.HTTPError as e:
            if e.code in (404, 410): return None, f'http {e.code}'
            if e.code == 429: time.sleep(10 * (attempt + 1)); continue
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None, 'could not fetch the channel page'

def _ytdlp_id(url):
    try:
        import yt_dlp
    except Exception:
        return None, 'yt-dlp not installed'
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True, 'playlist_items': '0', 'skip_download': True}) as y:
            info = y.extract_info(url, download=False) or {}
        cid = info.get('channel_id') or info.get('uploader_id') or ''
        return (cid, 'ytdlp') if UC.fullmatch(cid) else (None, 'yt-dlp gave no channel id')
    except Exception as e:
        return None, f'yt-dlp: {str(e)[:120]}'

def resolve_url(url):
    """channel_url -> (UC id, how) or (None, error). Cheapest path first."""
    cid = id_from_url(url)
    if cid: return cid, 'url'
    cid, how = _page_id(url)
    if cid: return cid, how
    cid2, how2 = _ytdlp_id(url)
    return (cid2, how2) if cid2 else (None, how)

# ---------------------------------------------------------------- the worker
def pending(path):
    c = sqlite3.connect(path)
    # channel_url: NULL = never looked up since 1.9, '' = looked up and YouTube gave no channel link (Retry All clears it), '-' = given up on by the user
    a = c.execute("select count(*) from videos where channel_url is null and title_source='oembed' and unavailable=0").fetchone()[0]
    b = c.execute("""select count(distinct channel_url) from videos v where channel_url is not null and channel_url not in ('','-')
                     and not exists(select 1 from video_channel x where x.video_id=v.video_id)
                     and channel_url not in (select channel_url from channel_unresolved)""").fetchone()[0]
    u = c.execute("select count(*) from channel_unresolved").fetchone()[0]
    c.close(); return dict(need_url=a, need_id=b, unresolved=u)

def _worker(path):
    import importer
    try:
        c = sqlite3.connect(path, timeout=30, check_same_thread=False)
        # ---- phase A: one more oEmbed call per video that has a title but no channel URL (pre-1.9 libraries)
        todo = [r[0] for r in c.execute("select video_id from videos where channel_url is null and title_source='oembed' and unavailable=0")]
        JOB.update(phase='urls', total=len(todo), done=0, ok=0, failed=0, note='')
        idx, lk = [0], threading.Lock()
        def work():
            while not JOB['cancel']:
                with lk:
                    if idx[0] >= len(todo): return
                    vid = todo[idx[0]]; idx[0] += 1
                st, res = importer._fetch_one(vid)
                with lk:
                    if st == 'ok' and res.get('author_url'):
                        c.execute("update videos set channel_url=?,channel=coalesce(?,channel) where video_id=?", (res['author_url'], res.get('author_name'), vid)); JOB['ok'] += 1
                    elif st == 'fail':
                        c.execute("update videos set unavailable=1,title_source=?,last_checked_at=? where video_id=?", (f'oembed_fail_{res}', now(), vid)); JOB['failed'] += 1
                    else:
                        # answered without a channel link, or a retry-class error: note the attempt so this row stops counting as pending
                        c.execute("update videos set channel_url='' where video_id=?", (vid,)); JOB['failed'] += 1   # '' = tried, no link; NULL = never tried
                    JOB['done'] += 1
                    if JOB['done'] % 100 == 0: c.commit()
        ths = [threading.Thread(target=work, daemon=True) for _ in range(int(os.environ.get('ORG_TITLE_THREADS', '5')))]
        [t.start() for t in ths]; [t.join() for t in ths]
        c.commit()
        if JOB['cancel']: return
        # ---- phase B: one page fetch per distinct channel URL that has no id yet
        # URLs already tried and failed are left alone here; Retry All clears channel_unresolved first, which is the only way back in
        rows = c.execute("""select channel_url, min(channel) title, count(*) n from videos v where channel_url is not null and channel_url not in ('','-')
                            and not exists(select 1 from video_channel x where x.video_id=v.video_id)
                            and channel_url not in (select channel_url from channel_unresolved) group by channel_url order by n desc""").fetchall()
        JOB.update(phase='ids', total=len(rows), done=0, ok=0, failed=0)
        known = {r[0]: r[1] for r in c.execute("select channel_url,channel_id from channels where channel_url is not null")}
        for url, title, n in rows:
            if JOB['cancel']: break
            cid = known.get(url)
            how = 'known'
            if not cid:
                cid, how = resolve_url(url)
                if cid and not FAKE: time.sleep(random.uniform(0.8, 1.6))   # be polite to youtube.com
            if cid:
                c.execute("""insert into channels(channel_id,title,handle,channel_url,resolved_from,created_at) values(?,?,?,?,?,?)
                             on conflict(channel_id) do update set title=coalesce(channels.title,excluded.title), channel_url=coalesce(channels.channel_url,excluded.channel_url)""",
                          (cid, title or cid, handle_from_url(url), url, how, now()))
                c.execute("insert or replace into video_channel(video_id,channel_id) select video_id,? from videos where channel_url=?", (cid, url))
                c.execute("delete from channel_unresolved where channel_url=?", (url,))
                known[url] = cid; JOB['ok'] += 1
            else:
                c.execute("insert into channel_unresolved(channel_url,title,error,tried_at,n) values(?,?,?,?,?) on conflict(channel_url) do update set error=excluded.error,tried_at=excluded.tried_at,n=excluded.n",
                          (url, title, how, now(), n)); JOB['failed'] += 1
            JOB['done'] += 1; c.commit()
        c.commit(); c.close()
    except Exception as e:
        JOB['note'] = str(e)[:300]
    finally:
        JOB.update(running=False, finished=time.time())

def start(path):
    with LOCK:
        if JOB['running']: return False
        JOB.update(running=True, phase='', total=0, done=0, ok=0, failed=0, started=time.time(), finished=None, note='', cancel=False)
    threading.Thread(target=_worker, args=(path,), name='feed-resolve', daemon=True).start(); return True

# ---------------------------------------------------------------- app wiring
def setup(app, DB):
    ensure_schema(DB)
    def con():
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

    @app.get('/feed', response_class=HTMLResponse)
    def feed_page(): return open(os.path.join(os.path.dirname(__file__), 'feed.html'), encoding='utf-8').read()

    @app.get('/api/feed/channels')
    def channels():
        c = con()
        import feed_fetch as ff
        auto = ff.compute_tiers(c)
        chans = [dict(r) for r in c.execute("""select ch.*, (select count(*) from video_channel x where x.channel_id=ch.channel_id) n_library,
                                                (select count(*) from feed_items i where i.channel_id=ch.channel_id and i.state='new') n_new
                                                from channels ch order by n_library desc, title collate nocase""")]
        for ch in chans: ch['auto_tier'] = auto.get(ch['channel_id'], 'daily'); ch['eff_tier'] = ff.effective_tier(ch.get('tier', 'auto'), ch['auto_tier'])
        unres = [dict(r) for r in c.execute("select * from channel_unresolved order by n desc, title collate nocase")]
        tot = c.execute("select count(*) from videos where unavailable=0").fetchone()[0]
        linked = c.execute("select count(*) from video_channel").fetchone()[0]
        c.close()
        return dict(channels=chans, unresolved=unres, videos=tot, linked=linked, pending=pending(DB))

    @app.post('/api/feed/resolve')
    def resolve(): return dict(started=start(DB), pending=pending(DB))

    @app.post('/api/feed/resolve/cancel')
    def cancel():
        JOB['cancel'] = True; return {'ok': 1}

    @app.get('/api/feed/resolve/status')
    def status():
        j = dict(JOB)
        if not j['running']: j['pending'] = pending(DB)
        return j

    @app.post('/api/feed/unresolved/retry')
    def retry():
        c = con(); c.execute("delete from channel_unresolved"); c.execute("update videos set channel_url=NULL where channel_url=''"); c.commit(); c.close()
        return dict(started=start(DB))

    class Manual(BaseModel): channel_url: str; link: str
    @app.post('/api/feed/unresolved/link')
    def link_manually(b: Manual):
        """The user pastes the channel's current link (any shape: /channel/UC…, /@handle, a video URL, or a bare UC… id).
        Resolve that, then link every library video that carried the old URL."""
        old = b.channel_url.strip(); given = b.link.strip()
        if not old or not given: return {'error': 'Paste the channel link first.'}
        cid, how = None, ''
        if UC.fullmatch(given): cid, how = given, 'manual'
        elif id_from_url(given): cid, how = id_from_url(given), 'manual'
        elif re.search(r'youtu\.?be', given):
            vm = re.search(r'(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})', given)
            if vm:
                # a video link: ask oEmbed for its channel page, then resolve that
                import importer
                st, res = importer._fetch_one(vm.group(1))
                if st == 'ok' and res.get('author_url'):
                    cid, how = resolve_url(res['author_url'])
                    if cid: how = 'manual'
                else: return {'error': 'That video could not be looked up on YouTube.'}
            else:
                cid, how = resolve_url(given)
                if cid: how = 'manual'
        else:
            return {'error': 'That does not look like a YouTube link or a channel id (UC…).'}
        if not cid: return {'error': f'Could not read a channel id from that link ({how}).'}
        c = con()
        title = (c.execute("select min(channel) from videos where channel_url=?", (old,)).fetchone() or [None])[0]
        c.execute("""insert into channels(channel_id,title,handle,channel_url,resolved_from,created_at) values(?,?,?,?,?,?)
                     on conflict(channel_id) do update set channel_url=excluded.channel_url, handle=coalesce(excluded.handle,channels.handle)""",
                  (cid, title or cid, handle_from_url(given) or handle_from_url(old), given if given.startswith('http') else old, how, now()))
        c.execute("update videos set channel_url=? where channel_url=?", (given if given.startswith('http') else old, old))
        c.execute("insert or replace into video_channel(video_id,channel_id) select video_id,? from videos where channel_url=?", (cid, given if given.startswith('http') else old))
        c.execute("delete from channel_unresolved where channel_url=?", (old,))
        n = c.execute("select count(*) from video_channel where channel_id=?", (cid,)).fetchone()[0]
        c.commit(); c.close()
        return {'ok': 1, 'channel_id': cid, 'linked': n}

    class Drop(BaseModel): channel_url: str
    @app.post('/api/feed/unresolved/remove')
    def remove_unresolved(b: Drop):
        """Give up on this channel: it leaves the Not Yet Resolved list for good and the feed will not follow it.
        Its videos stay in the library untouched. Marked with channel_url='-' so neither Resolve nor Retry All re-tries it."""
        old = b.channel_url.strip(); c = con()
        n = c.execute("update videos set channel_url='-' where channel_url=?", (old,)).rowcount
        c.execute("delete from channel_unresolved where channel_url=?", (old,))
        c.commit(); c.close()
        return {'ok': 1, 'videos': n}

    # ---------------------------------------------------------------- step 2: new videos
    import feed_fetch as ff
    ff.ensure_schema(DB); ff.start_poller(DB)

    @app.get('/api/feed/summary')
    def f_summary():
        c = con(); s = ff.summary(c); c.close(); s['job'] = dict(ff.JOB); s['resolve'] = dict(JOB); return s

    @app.get('/api/feed/items')
    def f_items(view: str = 'newest', limit: int = 200, offset: int = 0, shorts: str | None = None, channel: str | None = None, q: str | None = None):
        c = con(); r = ff.items(c, view, min(limit, 500), offset, shorts, channel, q); c.close(); return r

    @app.post('/api/feed/fetch')
    def f_fetch(kind: str = 'manual'):
        c = con(); first = ff.setting(c, 'first_pass_at') is None; c.close()
        return dict(started=ff.start_pass(DB, 'first' if first else 'manual'))

    @app.post('/api/feed/fetch/cancel')
    def f_cancel(): ff.JOB['cancel'] = True; return {'ok': 1}

    @app.get('/api/feed/fetch/status')
    def f_status(): return dict(ff.JOB)

    class St(BaseModel): video_ids: list[str]; state: str
    @app.post('/api/feed/items/state')
    def f_state(b: St):
        if b.state not in ('new', 'dismissed', 'pulled', 'watched', 'hidden', 'seen'): return {'error': 'bad state'}
        c = con(); t = ff.now(); n = 0
        for v in dict.fromkeys(b.video_ids):
            n += c.execute("update feed_items set state=?,state_at=? where video_id=?", (b.state, t, v)).rowcount
        c.commit(); c.close(); return {'ok': 1, 'changed': n}

    class Sett(BaseModel): polling: bool | None = None
    @app.post('/api/feed/settings')
    def f_settings(b: Sett):
        c = con()
        if b.polling is not None: ff.set_setting(c, 'polling', '1' if b.polling else '0')
        c.commit(); c.close(); return {'ok': 1}

    class ChSet(BaseModel): tier: str | None = None; muted: int | None = None; poll_enabled: int | None = None
    @app.post('/api/feed/channel/{cid}')
    def f_channel(cid: str, b: ChSet):
        if b.tier is not None and b.tier not in ('auto', *ff.TIERS): return {'error': 'bad tier'}
        c = con()
        for f in ('tier', 'muted', 'poll_enabled'):
            v = getattr(b, f)
            if v is not None: c.execute(f"update channels set {f}=? where channel_id=?", (v, cid))
        c.commit(); c.close(); return {'ok': 1}

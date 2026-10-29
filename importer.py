"""YouCommander: first-run schema + Google Takeout import + title fetching.

Privacy rule (same as the original import): only YouTube playlist CSVs are ever read. If a Takeout .zip is dropped, the
only members opened are  .../playlists/*.csv  -- watch history, comments, subscriptions etc. are never read."""
import os, re, csv, io, json, sqlite3, zipfile, threading, time, urllib.request, urllib.error, urllib.parse, datetime as dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, name TEXT, channel_id TEXT, takeout_tag TEXT, cloud_project TEXT, oauth_token_path TEXT);
CREATE TABLE IF NOT EXISTS playlists(pk INTEGER PRIMARY KEY, account_id TEXT, yt_playlist_id TEXT, title TEXT, visibility TEXT,
  created_at TEXT, updated_at TEXT, video_order TEXT, source_file TEXT, item_count INTEGER, etag TEXT, last_synced_at TEXT, managed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS videos(video_id TEXT PRIMARY KEY, title TEXT, channel TEXT, duration TEXT, title_source TEXT, channel_id TEXT,
  duration_s INTEGER, published_at TEXT, privacy TEXT, unavailable INTEGER DEFAULT 0, last_checked_at TEXT);
CREATE TABLE IF NOT EXISTS playlist_items(playlist_pk INTEGER, position INTEGER, video_id TEXT, added_at TEXT, yt_item_id TEXT);
CREATE INDEX IF NOT EXISTS ix_items_video ON playlist_items(video_id);
CREATE INDEX IF NOT EXISTS ix_items_pl ON playlist_items(playlist_pk);
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES tags(id), name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
 sort INTEGER DEFAULT 0, kind TEXT DEFAULT 'topic', publish INTEGER DEFAULT 0, publish_account TEXT, include_descendants INTEGER DEFAULT 1,
 playlist_title_override TEXT, description TEXT);
CREATE TABLE IF NOT EXISTS video_tags(video_id TEXT, tag_id INTEGER, source TEXT, confidence REAL, confirmed INTEGER DEFAULT 0, PRIMARY KEY(video_id,tag_id));
CREATE TABLE IF NOT EXISTS notes(video_id TEXT PRIMARY KEY, body TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS triage(video_id TEXT PRIMARY KEY, status TEXT DEFAULT 'new', triaged_at TEXT);
CREATE TABLE IF NOT EXISTS views(id INTEGER PRIMARY KEY, name TEXT UNIQUE, sql TEXT, description TEXT);
CREATE INDEX IF NOT EXISTS ix_vt_tag ON video_tags(tag_id);
CREATE TABLE IF NOT EXISTS audio_notes(id INTEGER PRIMARY KEY,video_id TEXT,path TEXT,created_at TEXT,transcript TEXT,status TEXT,extracted TEXT,error TEXT);
CREATE VIEW IF NOT EXISTS audit_recent_adds as select v.video_id,v.title,max(pi.added_at) added from playlist_items pi join videos v using(video_id) group by 1 order by added desc limit 200;
CREATE VIEW IF NOT EXISTS audit_duplicates as select v.video_id,v.title,count(distinct t.id) n_tags,group_concat(distinct t.name) tags from video_tags vt join tags t on t.id=vt.tag_id join videos v using(video_id) where t.name!='Inbox' group by 1 having n_tags>1 order by n_tags desc;
CREATE VIEW IF NOT EXISTS audit_unavailable as select video_id,title_source,title from videos where unavailable=1;
CREATE VIEW IF NOT EXISTS audit_untagged_inbox as select v.video_id,v.title from videos v join video_tags vt using(video_id) join tags t on t.id=vt.tag_id where t.name='Inbox' and v.video_id not in (select video_id from video_tags vt2 join tags t2 on t2.id=vt2.tag_id where t2.name!='Inbox');
CREATE VIEW IF NOT EXISTS audit_untriaged as select count(*) from triage where status='new';
CREATE VIEW IF NOT EXISTS audit_note_missing as select count(*) from videos v where v.video_id not in (select video_id from notes);
"""

def ensure_schema(path):
    """Create everything a brand-new install needs. Safe to run on an existing database (everything is IF NOT EXISTS)."""
    c = sqlite3.connect(path)
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript(SCHEMA)
    # 1.9: the channel's page URL from oEmbed (author_url), so channels can be told apart by more than their title.
    if 'channel_url' not in {r[1] for r in c.execute('pragma table_info(videos)')}:
        c.execute('alter table videos add column channel_url TEXT')
    have_fts = c.execute("select 1 from sqlite_master where name='video_fts'").fetchone()
    if not have_fts:
        c.execute("create virtual table video_fts using fts5(title,channel,tags,notes,content='')")
    if not c.execute("select 1 from tags where name='Inbox'").fetchone():
        c.execute("insert into tags(name,slug,kind,publish,description) values('Inbox','inbox','status',0,"
                  "'Marker for Watch later items still to be sorted. Never published.')")
    c.commit(); c.close()

def rebuild_fts(path):
    c = sqlite3.connect(path)
    c.execute("drop table if exists video_fts")
    c.execute("create table if not exists notes(video_id TEXT PRIMARY KEY, body TEXT, updated_at TEXT)")
    c.execute("create table if not exists video_marks(id INTEGER PRIMARY KEY, video_id TEXT, t REAL, body TEXT, source TEXT DEFAULT 'typed', created_at TEXT DEFAULT (datetime('now')))")
    c.execute("create virtual table video_fts using fts5(title,channel,tags,notes,content='')")
    c.execute("""insert into video_fts(rowid,title,channel,tags,notes) select v.rowid,coalesce(v.title,''),coalesce(v.channel,''),
      coalesce((select group_concat(t.name,' ') from video_tags vt join tags t on t.id=vt.tag_id where vt.video_id=v.video_id),''),coalesce((select n.body from notes n where n.video_id=v.video_id),'')||' '||coalesce((select group_concat(m.body,' ') from video_marks m where m.video_id=v.video_id),'') from videos v""")
    c.commit(); c.close()

# ---------------------------------------------------------------- staging
def staging_dir(db_path):
    d = os.environ.get('ORG_IMPORT_DIR') or os.path.join(os.path.dirname(os.path.abspath(db_path)), 'import_staging')
    os.makedirs(d, exist_ok=True); return d

def reset_staging(db_path):
    d = staging_dir(db_path)
    for f in os.listdir(d):
        try: os.remove(os.path.join(d, f))
        except OSError: pass

PLAYLIST_ZIP_MEMBER = re.compile(r'(^|/)playlists/[^/]+\.csv$', re.I)
MAX_CSV = 60 * 1024 * 1024

def keep_csv(db_path, name, data_iter_or_bytes):
    """Save one CSV into staging under its base name. Returns the saved base name."""
    base = os.path.basename(name.replace('\\', '/'))
    base = re.sub(r'[\x00-\x1f]', '', base)
    if not base.lower().endswith('.csv'): return None
    dest = os.path.join(staging_dir(db_path), base)
    with open(dest, 'wb') as f:
        if isinstance(data_iter_or_bytes, (bytes, bytearray)): f.write(data_iter_or_bytes)
        else:
            for ch in data_iter_or_bytes: f.write(ch)
    return base

def stage_zip(db_path, zip_path):
    """Extract ONLY .../playlists/*.csv from a Takeout zip. Everything else in the archive is left unopened."""
    kept, skipped = [], 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir(): continue
            if PLAYLIST_ZIP_MEMBER.search(info.filename) and info.file_size <= MAX_CSV:
                with z.open(info) as fh: kept.append(keep_csv(db_path, info.filename, [fh.read()]))
            else: skipped += 1
    return [k for k in kept if k], skipped

# ---------------------------------------------------------------- parsing
def sanitize(t): return re.sub(r'[\\/:*?"<>|\']', '_', t)

def read_csv_file(p):
    with open(p, encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))

def _col(row_or_header, *needles):
    for h in row_or_header:
        hl = (h or '').lower()
        if all(n in hl for n in needles): return h
    return None

def classify(path):
    """Returns ('index', rows) for playlists.csv-style files, ('videos', rows) for a single playlist, or (None, None)."""
    try: rows = read_csv_file(path)
    except Exception: return None, None
    hdr = list(rows[0].keys()) if rows else []
    if not hdr:
        with open(path, encoding='utf-8-sig', newline='') as f:
            hdr = next(csv.reader(f), [])
    if _col(hdr, 'playlist', 'id') and _col(hdr, 'title') and not _col(hdr, 'video id'): return 'index', rows
    if _col(hdr, 'video id'): return 'videos', rows
    return None, None

def title_from_filename(fn):
    t = re.sub(r'\.csv$', '', fn, flags=re.I)
    t = re.sub(r'\(\d+\)$', '', t)
    t = re.sub(r'-videos$', '', t, flags=re.I)
    return t.strip() or 'Untitled playlist'

def parse_staged(db_path):
    """Look at everything staged and work out the playlists. No database writes."""
    d = staging_dir(db_path)
    index_rows, vid_files, ignored = [], {}, []
    for fn in sorted(os.listdir(d)):
        kind, rows = classify(os.path.join(d, fn))
        if kind == 'index': index_rows += rows
        elif kind == 'videos': vid_files[fn] = rows
        else: ignored.append(fn)
    playlists, used = [], set()
    if index_rows:
        seen = {}
        for r in index_rows:
            ttl_col = _col(r.keys(), 'title', 'original') or _col(r.keys(), 'title')
            id_col = _col(r.keys(), 'playlist', 'id')
            title = (r.get(ttl_col) or '').strip() if ttl_col else ''
            n = seen.get(title, 0); seen[title] = n + 1
            fname = f'{sanitize(title)}-videos.csv' if n == 0 else f'{sanitize(title)}-videos({n}).csv'
            pl = dict(title=title or 'Untitled playlist', yt_id=(r.get(id_col) or '').strip(),
                      visibility=r.get(_col(r.keys(), 'visibility') or '') or None,
                      created=r.get(_col(r.keys(), 'create') or '') or None, updated=r.get(_col(r.keys(), 'update') or '') or None,
                      order=r.get(_col(r.keys(), 'order') or '') or None, file=None, items=[])
            if fname in vid_files: pl['file'] = fname; used.add(fname)
            playlists.append(pl)
    for fn, rows in vid_files.items():
        if fn in used: continue
        playlists.append(dict(title=title_from_filename(fn), yt_id='', visibility=None, created=None, updated=None, order=None, file=fn, items=[]))
    for pl in playlists:
        rows = vid_files.get(pl['file'], []) if pl['file'] else []
        if rows:
            vc = _col(rows[0].keys(), 'video id'); tc = _col(rows[0].keys(), 'creation') or _col(rows[0].keys(), 'added') or _col(rows[0].keys(), 'timestamp')
            for x in rows:
                v = (x.get(vc) or '').strip()
                if v: pl['items'].append((v, (x.get(tc) or '').strip() if tc else ''))
    return playlists, ignored

def preview(db_path):
    pls, ignored = parse_staged(db_path)
    vids = {v for p in pls for v, _ in p['items']}
    c = sqlite3.connect(db_path)
    known = {r[0] for r in c.execute('select video_id from videos')}
    c.close()
    return dict(playlists=len(pls), non_empty=sum(1 for p in pls if p['items']), items=sum(len(p['items']) for p in pls),
                unique_videos=len(vids), new_videos=len(vids - known), ignored=ignored,
                biggest=[dict(title=p['title'], n=len(p['items'])) for p in sorted(pls, key=lambda p: -len(p['items']))[:8]])

# ---------------------------------------------------------------- import
def _slug(s): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'x'

def run_import(db_path, label):
    ensure_schema(db_path)
    pls, ignored = parse_staged(db_path)
    if not pls: return dict(error='Nothing to import yet. Drop your Takeout playlist files first.')
    label = (label or '').strip() or 'My YouTube'
    aid = _slug(label)
    c = sqlite3.connect(db_path)
    c.execute('insert or ignore into accounts(id,name) values(?,?)', (aid, label))
    used_slugs = {r[0] for r in c.execute('select slug from tags')}
    tagof = {r[1]: r[0] for r in c.execute('select id,name from tags')}
    new_pl = upd_pl = new_vids = added_tags = 0
    before = {r[0] for r in c.execute('select video_id from videos')}
    for p in pls:
        row = None
        if p['yt_id']: row = c.execute('select pk from playlists where account_id=? and yt_playlist_id=?', (aid, p['yt_id'])).fetchone()
        if not row: row = c.execute('select pk from playlists where account_id=? and title=?', (aid, p['title'])).fetchone()
        if row:
            pk = row[0]; upd_pl += 1
            c.execute('update playlists set visibility=coalesce(?,visibility),updated_at=coalesce(?,updated_at),video_order=coalesce(?,video_order),source_file=?,item_count=? where pk=?',
                      (p['visibility'], p['updated'], p['order'], p['file'], len(p['items']), pk))
            c.execute('delete from playlist_items where playlist_pk=?', (pk,))
        else:
            pk = c.execute('insert into playlists(account_id,yt_playlist_id,title,visibility,created_at,updated_at,video_order,source_file,item_count) values(?,?,?,?,?,?,?,?,?)',
                           (aid, p['yt_id'] or None, p['title'], p['visibility'], p['created'], p['updated'], p['order'], p['file'], len(p['items']))).lastrowid
            new_pl += 1
        c.executemany('insert into playlist_items(playlist_pk,position,video_id,added_at) values(?,?,?,?)', [(pk, i, v, t) for i, (v, t) in enumerate(p['items'])])
        c.executemany('insert or ignore into videos(video_id) values(?)', [(v,) for v, _ in p['items']])
        if not p['items']: continue
        if p['title'].strip().lower() == 'watch later': name, conf = 'Inbox', 1
        else: name, conf = p['title'], 0
        if name not in tagof:
            s = _slug(name); b = s; n = 2
            while s in used_slugs: s = f'{b}-{n}'; n += 1
            used_slugs.add(s)
            tagof[name] = c.execute("insert into tags(name,slug,kind,publish) values(?,?,'topic',0)", (name, s)).lastrowid
        cur = c.executemany("insert or ignore into video_tags(video_id,tag_id,source,confidence,confirmed) values(?,?,'import',NULL,?)", [(v, tagof[name], conf) for v, _ in p['items']])
        added_tags += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    inbox = tagof.get('Inbox')
    c.execute("insert or ignore into triage(video_id,status) select video_id,'new' from videos")
    c.execute("update triage set status='imported' where status='new' and video_id in (select vt.video_id from video_tags vt join tags t on t.id=vt.tag_id where t.name!='Inbox')")
    now = {r[0] for r in c.execute('select video_id from videos')}
    c.commit(); c.close()
    rebuild_fts(db_path)
    return dict(ok=True, account=label, playlists_new=new_pl, playlists_updated=upd_pl, videos_total=len(now), videos_new=len(now - before),
                ignored=ignored, need_titles=len(need_titles(db_path)))

# ---------------------------------------------------------------- titles (YouTube oEmbed: no API key, no quota)
def need_titles(db_path):
    c = sqlite3.connect(db_path)
    r = [x[0] for x in c.execute("select video_id from videos where (title is null or title='') and (title_source is null or title_source='')")]
    c.close(); return r

TITLES = dict(running=False, done=0, total=0, failed=0, unavailable=0, started=None, finished=None, error=None)
_lock = threading.Lock()

def _fetch_one(vid):
    if os.environ.get('ORG_OEMBED_FAKE'):
        if vid.startswith('GONE'): return 'fail', 404
        if vid.startswith('NOURL'): return 'ok', dict(title=f'Fake title for {vid}', author_name='Fake Channel')   # answered without a channel link
        # Fake channels: the first character picks the channel, so several videos can share one, and two videos from
        # different channels can share a *title* ('Fake Channel') the way real same-named channels do.
        return 'ok', dict(title=f'Fake title for {vid}', author_name='Fake Channel', author_url=f'https://www.youtube.com/@fake-{vid[0]}')
    url = 'https://www.youtube.com/oembed?format=json&url=' + urllib.parse.quote(f'https://www.youtube.com/watch?v={vid}', safe='')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'YouCommander/1.0'}), timeout=20) as r:
                return 'ok', json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404): return 'fail', e.code
            if e.code == 429: time.sleep(5 * (attempt + 1)); continue
            return 'retry', e.code
        except Exception: time.sleep(1.5 * (attempt + 1))
    return 'retry', 0

def _title_worker(db_path):
    try:
        todo = need_titles(db_path)
        TITLES.update(running=True, done=0, total=len(todo), failed=0, unavailable=0, started=time.time(), finished=None, error=None)
        c = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        idx = [0]; lk = threading.Lock(); pending = [0]

        def work():
            try:
                while True:
                    with lk:
                        if idx[0] >= len(todo): return
                        vid = todo[idx[0]]; idx[0] += 1
                    st, res = _fetch_one(vid)
                    with lk:
                        if st == 'ok':
                            c.execute("update videos set title=?,channel=?,channel_url=?,title_source='oembed',unavailable=0,last_checked_at=? where video_id=?",
                                      (res.get('title'), res.get('author_name'), res.get('author_url'), dt.datetime.utcnow().isoformat(timespec='seconds'), vid))
                        elif st == 'fail':
                            c.execute("update videos set title_source=?,unavailable=1,last_checked_at=? where video_id=?",
                                      (f'oembed_fail_{res}', dt.datetime.utcnow().isoformat(timespec='seconds'), vid)); TITLES['unavailable'] += 1
                        else: TITLES['failed'] += 1
                        TITLES['done'] += 1; pending[0] += 1
                        if pending[0] >= 100: c.commit(); pending[0] = 0
            except Exception as e:
                TITLES['error'] = str(e)
        ths = [threading.Thread(target=work, daemon=True) for _ in range(int(os.environ.get('ORG_TITLE_THREADS', '5')))]
        [t.start() for t in ths]; [t.join() for t in ths]
        c.commit(); c.close()
        rebuild_fts(db_path)
    except Exception as e:
        TITLES['error'] = str(e)
    finally:
        TITLES.update(running=False, finished=time.time())

def start_titles(db_path):
    with _lock:
        if TITLES['running']: return False
        TITLES.update(running=True, done=0, total=0)
    threading.Thread(target=_title_worker, args=(db_path,), daemon=True).start(); return True

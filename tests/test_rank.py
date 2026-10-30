"""Step 3: ranking from library signals. Pure functions on a scratch database, then the API's mode behaviour."""
import os, sqlite3, time, pytest
import feed_rank, importer

def _db(tmp_path):
    p = str(tmp_path / 'r.db'); importer.ensure_schema(p)
    c = sqlite3.connect(p)
    c.executescript("""
    create table if not exists watch_state(video_id TEXT PRIMARY KEY, last_pos REAL DEFAULT 0, duration REAL DEFAULT 0, seconds REAL DEFAULT 0, plays INTEGER DEFAULT 0, speed REAL DEFAULT 1, loop_a REAL, loop_b REAL, last_watched TEXT, first_watched TEXT);
    create table if not exists video_marks(id INTEGER PRIMARY KEY, video_id TEXT, t REAL, body TEXT, source TEXT DEFAULT 'typed', created_at TEXT DEFAULT (datetime('now')));
    create table if not exists channels(channel_id TEXT PRIMARY KEY, title TEXT NOT NULL, handle TEXT, channel_url TEXT, resolved_from TEXT, poll_enabled INTEGER NOT NULL DEFAULT 1, muted INTEGER NOT NULL DEFAULT 0, shorts_mode TEXT NOT NULL DEFAULT 'show', etag TEXT, last_polled TEXT, last_video_at TEXT, poll_error TEXT, created_at TEXT NOT NULL);
    create table if not exists video_channel(video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL);
    create table if not exists feed_items(video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT, published_at TEXT NOT NULL, updated_at TEXT, thumb_url TEXT, duration_s INTEGER, views INTEGER, views_at TEXT, likes INTEGER, rating_n INTEGER, is_short INTEGER, is_short_src TEXT, first_seen TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'new', state_at TEXT, base_score REAL, score_json TEXT, scored_at TEXT);
    create table if not exists feed_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    feed_rank.ensure_schema(p)
    return p, c

def _chan(c, cid, videos):
    """videos: list of dicts {id, completion, note, status}"""
    c.execute("insert into channels(channel_id,title,created_at) values(?,?,'2026-01-01')", (cid, cid))
    for v in videos:
        c.execute("insert into videos(video_id,title) values(?,?)", (v['id'], v.get('title', 'Video ' + v['id'])))
        c.execute("insert into video_channel values(?,?)", (v['id'], cid))
        if v.get('completion') is not None: c.execute("insert into watch_state(video_id,last_pos,duration) values(?,?,100)", (v['id'], 100 * v['completion']))
        if v.get('note'): c.execute("insert into notes(video_id,body,updated_at) values(?,?,datetime('now'))", (v['id'], 'n'))
        if v.get('status'): c.execute("insert into triage(video_id,status) values(?,?)", (v['id'], v['status']))
    c.commit()

def test_drop_ratio_penalty_matches_the_design(tmp_path):
    p, c = _db(tmp_path)
    # 8 keeps / 2 drops: ratio 0.2 -> penalty 0.032 ; 2 keeps / 8 drops: ratio 0.8 -> 0.512 ; 1 keep / 1 drop: too few decisions -> none
    _chan(c, 'liked',  [dict(id=f'L{i:010d}', status='done' if i < 8 else 'dropped', completion=1.0) for i in range(10)])
    _chan(c, 'mostly', [dict(id=f'M{i:010d}', status='done' if i < 2 else 'dropped', completion=1.0) for i in range(10)])
    _chan(c, 'two',    [dict(id='T0000000001', status='done', completion=1.0), dict(id='T0000000002', status='dropped', completion=1.0)])
    _chan(c, 'quiet',  [dict(id='Q0000000001')])
    assert feed_rank.compute_affinity(c) == 4
    a = {r[0]: r[1:] for r in c.execute("select channel_id, drop_ratio, affinity, n_kept, n_dropped from channel_affinity")}
    assert a['liked'][0] == pytest.approx(0.2) and a['mostly'][0] == pytest.approx(0.8) and a['two'][0] == pytest.approx(0.5) and a['quiet'][0] is None
    # the penalty is the only difference between liked and mostly besides their (equal) watch totals shifted by drops? No:
    # w_raw differs too (keeps add 0.20). Check the penalty directly from pos: affinity = pos - 0.8*ratio^2
    import math
    rows = {r[0]: r[1] for r in c.execute("select channel_id, w_raw from channel_affinity")}
    ws = list(rows.values()); mean = sum(ws) / len(ws); sd = math.sqrt(sum((w - mean) ** 2 for w in ws) / len(ws)) or 1
    pos = lambda cid: 1 / (1 + math.exp(-(rows[cid] - mean) / sd))
    assert a['liked'][1] == pytest.approx(max(0, pos('liked') - 0.8 * 0.2 ** 2), abs=1e-6)
    assert a['mostly'][1] == pytest.approx(max(0, pos('mostly') - 0.8 * 0.8 ** 2), abs=1e-6)
    assert a['two'][1] == pytest.approx(pos('two'), abs=1e-6)          # under 3 decisions: no penalty
    assert a['liked'][1] > a['mostly'][1]

def test_engagement_terms_and_item_scores(tmp_path):
    p, c = _db(tmp_path)
    _chan(c, 'hot',  [dict(id='H0000000001', completion=1.0, note=True, status='done'), dict(id='H0000000002', completion=0.9, title='Fixing a dead PSU with a multimeter'), dict(id='H0000000003', completion=0.8)])
    _chan(c, 'cold', [dict(id='C0000000001')])
    feed_rank.compute_affinity(c)
    for vid, cid, title in (('F0000000001', 'hot', 'Fresh from hot'), ('F0000000002', 'cold', 'Fresh from cold'),
                            ('H0000000001', 'hot', 'Already saved'), ('F0000000003', 'hot', 'Fixing a dead PSU with a multimeter (reupload)')):
        c.execute("insert into feed_items(video_id,channel_id,title,published_at,first_seen) values(?,?,?,'2026-10-29T00:00:00','2026-10-29T00:00:00')", (vid, cid, title))
    c.commit()
    assert feed_rank.score_items(c) == 4
    s = {r[0]: (r[1], __import__('json').loads(r[2])) for r in c.execute("select video_id, base_score, score_json from feed_items")}
    assert s['F0000000001'][0] > s['F0000000002'][0]                       # hot channel outranks cold
    assert s['H0000000001'][1]['terms']['seen'] == -1.0                    # already in the library: effectively hidden
    assert s['F0000000003'][1]['terms'].get('dup') == -0.5                 # same channel, near-identical saved title
    why = s['F0000000001'][1]['why']; assert why['n_library'] == 3 and why['n_watched'] == 3 and why['n_noted'] == 1 and why['n_kept'] == 1
    assert 0 < why['affinity'] <= 1

def test_recency_is_query_time_only_and_modes_differ(tmp_path):
    p, c = _db(tmp_path)
    _chan(c, 'a', [dict(id='A0000000001', completion=1.0)])
    _chan(c, 'b', [dict(id='B0000000001')])
    feed_rank.compute_affinity(c)
    import datetime as dt
    now = dt.datetime.utcnow()
    # an old item from the liked channel vs a fresh item from the quiet one
    c.execute("insert into feed_items(video_id,channel_id,title,published_at,first_seen) values('OLDAAAAAAAA','a','Old but loved',?,?)", ((now - dt.timedelta(days=6)).isoformat(timespec='seconds'),) * 2)
    c.execute("insert into feed_items(video_id,channel_id,title,published_at,first_seen) values('NEWBBBBBBBB','b','New but meh',?,?)", ((now - dt.timedelta(hours=2)).isoformat(timespec='seconds'),) * 2)
    c.commit(); feed_rank.score_items(c)
    base = {r[0]: r[1] for r in c.execute("select video_id, base_score from feed_items")}
    import feed_fetch; c.row_factory = sqlite3.Row
    rec = [i['video_id'] for i in feed_fetch.items(c, 'ranked', mode='recent')]
    rev = [i['video_id'] for i in feed_fetch.items(c, 'ranked', mode='review')]
    assert rec[0] == 'NEWBBBBBBBB' and rev[0] == 'OLDAAAAAAAA'              # Recent favours fresh; Review favours the channel
    after = {r[0]: r[1] for r in c.execute("select video_id, base_score from feed_items")}
    assert after == base                                                    # switching modes stored nothing
    assert feed_fetch.items(c, 'newest')[0]['video_id'] == 'NEWBBBBBBBB'
    # the review window (21 d) includes a 15-day-old item; recent (7 d) does not
    c.execute("insert into feed_items(video_id,channel_id,title,published_at,first_seen) values('MIDAAAAAAAA','a','Two weeks ago',?,?)", ((now - dt.timedelta(days=15)).isoformat(timespec='seconds'),) * 2); c.commit(); feed_rank.score_items(c)
    assert 'MIDAAAAAAAA' in [i['video_id'] for i in feed_fetch.items(c, 'ranked', mode='review')]
    assert 'MIDAAAAAAAA' not in [i['video_id'] for i in feed_fetch.items(c, 'ranked', mode='recent')]

def test_retention_hides_stale_untouched_items(tmp_path):
    p, c = _db(tmp_path)
    _chan(c, 'a', [dict(id='A0000000001')])
    c.execute("insert into feed_items(video_id,channel_id,title,published_at,first_seen) values('STALE000001','a','Stale','2026-01-01T00:00:00','2026-01-01T00:00:00')")
    c.execute("insert into feed_items(video_id,channel_id,title,published_at,first_seen,state) values('STALE000002','a','Pulled long ago','2026-01-01T00:00:00','2026-01-01T00:00:00','pulled')")
    c.commit()
    assert feed_rank.retention(c) == 1
    assert c.execute("select state from feed_items where video_id='STALE000001'").fetchone()[0] == 'hidden'
    assert c.execute("select state from feed_items where video_id='STALE000002'").fetchone()[0] == 'pulled'

def test_mode_setting_and_seen_marker(resolved):
    client = resolved
    s = client.get('/api/feed/summary').json(); assert s['mode'] == 'recent'
    assert client.post('/api/feed/settings', json={'mode': 'review'}).json()['ok']
    assert client.get('/api/feed/summary').json()['mode'] == 'review'
    assert 'error' in client.post('/api/feed/settings', json={'mode': 'weekly'}).json()
    assert client.post('/api/feed/seen').json()['ok'] and client.get('/api/feed/summary').json()['last_seen_at']
    client.post('/api/feed/settings', json={'mode': 'recent'})
    r = client.get('/api/feed/items', params={'view': 'ranked'}).json()
    assert all('score' in i and 'base_score' in i for i in r)
    assert client.post('/api/feed/rescore').json()['ok']

"""Feed step 1: channel identity."""
import os, sqlite3, sys, time, pytest
from conftest import takeout_csvs

@pytest.fixture(scope='module')
def lib(client):
    """The imported test library (titles filled by the oEmbed test double), whichever test file runs first."""
    if client.get('/api/summary').json()['videos'] == 0:
        client.post('/api/import/reset')
        for n, d in takeout_csvs().items(): client.post('/api/import/stage', params={'name': n}, content=d)
        client.post('/api/import/run', json={'label': 'Test Account'})
    client.post('/api/import/titles')
    for _ in range(50):
        if not client.get('/api/import/status').json().get('running'): break
        time.sleep(0.1)
    return client

def _feed(): return sys.modules['feed']   # imported by app with ORG_FEED_FAKE set

def _wait(client, secs=5):
    for _ in range(int(secs / 0.05)):
        if not client.get('/api/feed/resolve/status').json().get('running'): return
        time.sleep(0.05)
    raise AssertionError('resolver still running')

def test_url_shapes(lib):
    feed = _feed()
    assert feed.id_from_url('https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv') == 'UCabcdefghijklmnopqrstuv'
    assert feed.id_from_url('https://www.youtube.com/@someone') is None
    assert feed.handle_from_url('https://www.youtube.com/@Some%20One') == '@Some One'
    assert feed.handle_from_url('https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv') is None
    cid, how = feed.resolve_url('https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv')
    assert (cid, how) == ('UCabcdefghijklmnopqrstuv', 'url')
    cid, how = feed.resolve_url('https://www.youtube.com/@someone')
    assert cid and cid.startswith('UC') and len(cid) == 24 and how == 'page'
    assert feed.resolve_url('https://www.youtube.com/@nochannel-here')[0] is None

def test_feed_page_serves(lib):
    client = lib
    r = client.get('/feed')
    assert r.status_code == 200 and '<title>' in r.text and '/static/app.css' in r.text

def test_import_stores_channel_url(lib):
    client = lib
    db = os.environ['ORG_DB']; c = sqlite3.connect(db)
    rows = c.execute("select video_id, channel, channel_url from videos where title_source='oembed'").fetchall(); c.close()
    assert rows and all(u and u.startswith('https://www.youtube.com/@fake-') for _, _, u in rows)

def test_resolver_links_every_video_and_keeps_same_titled_channels_apart(lib):
    client = lib
    before = client.get('/api/feed/channels').json()
    assert before['linked'] == 0 and before['pending']['need_id'] >= 2
    assert client.post('/api/feed/resolve').json()['started']
    _wait(client)
    after = client.get('/api/feed/channels').json()
    assert after['linked'] == after['videos'] and after['pending'] == {'need_url': 0, 'need_id': 0, 'unresolved': 0}
    # 'aaaaaaaaaaa' and 'bbbbbbbbbbb' both say "Fake Channel" but come from @fake-a and @fake-b: two channels, not one
    ids = {ch['channel_id'] for ch in after['channels']}
    assert len(ids) == len(after['channels']) >= 2
    urls = {ch['channel_url'] for ch in after['channels']}
    assert 'https://www.youtube.com/@fake-a' in urls and 'https://www.youtube.com/@fake-b' in urls
    assert all(ch['n_library'] >= 1 and ch['resolved_from'] == 'page' and ch['handle'].startswith('@fake-') for ch in after['channels'])
    assert after['unresolved'] == []

def test_phase_a_backfills_pre_1_9_rows_and_unresolved_is_reported(lib):
    client = lib
    db = os.environ['ORG_DB']; c = sqlite3.connect(db)
    # a pre-1.9 row: title from oEmbed, no channel_url yet -> phase A fills it, phase B links it
    c.execute("insert into videos(video_id,title,channel,title_source) values('eeeeeeeeeee','Old row','Fake Channel','oembed')")
    # a URL the (fake) channel page cannot resolve -> lands in the Not Yet Resolved list
    c.execute("insert into videos(video_id,title,channel,channel_url,title_source) values('fffffffffff','Gone','Vanished','https://www.youtube.com/@nochannel-x','oembed')")
    c.commit(); c.close()
    p = client.get('/api/feed/channels').json()['pending']
    assert p == {'need_url': 1, 'need_id': 1, 'unresolved': 0}
    client.post('/api/feed/resolve'); _wait(client)
    r = client.get('/api/feed/channels').json()
    # the failed URL is no longer "pending": a plain Resolve leaves it alone, only Retry All tries it again
    assert r['pending'] == {'need_url': 0, 'need_id': 0, 'unresolved': 1}
    tried = r['unresolved'][0]['tried_at']
    client.post('/api/feed/resolve'); _wait(client)
    assert client.get('/api/feed/channels').json()['unresolved'][0]['tried_at'] == tried
    assert len(r['unresolved']) == 1 and r['unresolved'][0]['channel_url'].endswith('@nochannel-x') and r['unresolved'][0]['n'] == 1
    c = sqlite3.connect(db)
    assert c.execute("select channel_url from videos where video_id='eeeeeeeeeee'").fetchone()[0] == 'https://www.youtube.com/@fake-e'
    assert c.execute("select channel_id from video_channel where video_id='eeeeeeeeeee'").fetchone()
    c.close()
    # retry clears the list and runs again; still unresolvable, so it comes back with n unchanged
    time.sleep(1.1); client.post('/api/feed/unresolved/retry'); _wait(client)
    u = client.get('/api/feed/channels').json()['unresolved']
    assert len(u) == 1 and u[0]['tried_at'] != tried
    # leave the shared library as the import left it (the smoke test counts its videos)
    c = sqlite3.connect(db)
    c.execute("delete from videos where video_id in ('eeeeeeeeeee','fffffffffff')")
    c.execute("delete from video_channel where video_id in ('eeeeeeeeeee','fffffffffff')")
    c.execute("delete from channel_unresolved"); c.commit(); c.close()


# ---------------------------------------------------------------- step 2: new videos
def _ff(): return sys.modules['feed_fetch']

@pytest.fixture(scope='module')
def resolved(lib):
    """The library with every channel resolved (step 1), whatever order the tests ran in."""
    if lib.get('/api/feed/channels').json()['linked'] < 4:
        lib.post('/api/feed/resolve'); _wait(lib)
    return lib

def _wait_fetch(client, secs=10):
    for _ in range(int(secs / 0.05)):
        if not client.get('/api/feed/fetch/status').json().get('running'): return
        time.sleep(0.05)
    raise AssertionError('fetch still running')

def test_atom_parser_is_namespace_agnostic_and_tolerant(resolved):
    lib = resolved
    ff = _ff()
    raw = open(os.path.join(ff.FIX, 'UC33585ccd6083d99f36099d.xml'), 'rb').read()
    e = ff.parse_atom(raw)
    assert [x['video_id'] for x in e] == ['Snew0000001', 'Unew0000001', 'aaaaaaaaaaa', 'Rnew0000001']
    r = e[3]
    assert r['title'] == 'A regular upload' and r['views'] == 4200 and r['rating_n'] == 12 and r['description'] == 'Long form, with & entity'
    assert r['thumb'].endswith('/Rnew0000001/hqdefault.jpg')
    assert ff.iso_utc('2026-10-27T09:00:00-07:00') == '2026-10-27T16:00:00'   # offsets are normalised to UTC
    assert ff.parse_atom(raw.replace(b'xmlns:yt="http://www.youtube.com/xml/schemas/2015"', b'xmlns:yt="http://example.com/other"'))[0]['video_id'] == 'Snew0000001'

def test_first_pass_fetches_every_channel_and_probes_shorts(resolved):
    client = resolved
    s = client.get('/api/feed/summary').json()
    assert s['first_pass_at'] is None and s['new'] == 0 and s['polling'] is False
    assert client.post('/api/feed/fetch').json()['started']
    _wait_fetch(client)
    j = client.get('/api/feed/fetch/status').json()
    assert j['kind'] == 'first:shorts' and j['failed'] >= 2          # channel c (bad xml) and d (no feed); a fifth channel may linger from the phase-A test
    errs = {c['handle']: c['poll_error'] for c in client.get('/api/feed/channels').json()['channels']}
    assert errs['@fake-c'].startswith('parse:') and errs['@fake-d'] == 'fake: no feed' and errs['@fake-a'] is None
    s = client.get('/api/feed/summary').json()
    assert s['first_pass_at'] and s['polling'] is True                # polling turns itself on after the first pass
    items = client.get('/api/feed/items').json()
    ids = [i['video_id'] for i in items]
    assert ids == ['Rnew0000002', 'Snew0000001', 'Unew0000001', 'Rnew0000001']   # newest first, across channels
    assert 'aaaaaaaaaaa' not in ids                                   # already in the library: not "new to you"
    by = {i['video_id']: i for i in items}
    assert by['Snew0000001']['is_short'] == 1 and by['Rnew0000001']['is_short'] == 0 and by['Unew0000001']['is_short'] is None
    assert by['Rnew0000002']['thumb_url'] is None and by['Rnew0000001']['views'] == 4200
    assert [i['video_id'] for i in client.get('/api/feed/items?shorts=only').json()] == ['Snew0000001']
    assert 'Snew0000001' not in [i['video_id'] for i in client.get('/api/feed/items?shorts=hide').json()]
    assert s['new'] == 4 and s['new_shorts'] == 1 and s['unknown_len'] == 1
    log = s['last_run']; assert log['kind'] == 'first' and log['channels'] >= 4 and log['new_items'] == 4 and log['failed'] >= 2

def test_repoll_is_conditional_and_refreshes_views(resolved):
    client = resolved; ff = _ff()
    db = os.environ['ORG_DB']
    # unchanged fixture -> 304-equivalent, no new rows
    client.post('/api/feed/fetch'); _wait_fetch(client)
    j = client.get('/api/feed/fetch/status').json()
    assert j['new'] == 0 and j['unchanged'] == 2 and j['failed'] >= 2
    # bump the views in channel b's fixture and touch it -> the row's views refresh, nothing duplicates
    p = os.path.join(ff.FIX, 'UC3f4ceb5349be81_dbe418f.xml'); raw = open(p).read()
    open(p, 'w').write(raw.replace('views="10"', 'views="999"')); os.utime(p, (time.time() + 5, time.time() + 5))
    client.post('/api/feed/fetch'); _wait_fetch(client)
    it = {i['video_id']: i for i in client.get('/api/feed/items').json()}
    assert it['Rnew0000002']['views'] == 999 and len(it) == 4
    open(p, 'w').write(raw); os.utime(p, (time.time() + 10, time.time() + 10))

def test_dismiss_and_channel_settings(resolved):
    client = resolved
    assert client.post('/api/feed/items/state', json={'video_ids': ['Unew0000001'], 'state': 'dismissed'}).json()['changed'] == 1
    assert 'Unew0000001' not in [i['video_id'] for i in client.get('/api/feed/items').json()]
    client.post('/api/feed/items/state', json={'video_ids': ['Unew0000001'], 'state': 'new'})
    chans = {c['handle']: c for c in client.get('/api/feed/channels').json()['channels']}
    a = chans['@fake-a']
    assert a['n_new'] == 3 and a['tier'] == 'auto' and a['eff_tier'] in ('hourly', 'sixhourly', 'daily')
    assert client.post(f"/api/feed/channel/{a['channel_id']}", json={'tier': 'off'}).json()['ok']
    chans = {c['handle']: c for c in client.get('/api/feed/channels').json()['channels']}
    assert chans['@fake-a']['eff_tier'] == 'off'
    assert 'error' in client.post(f"/api/feed/channel/{a['channel_id']}", json={'tier': 'weekly'}).json()
    client.post(f"/api/feed/channel/{a['channel_id']}", json={'tier': 'auto'})
    # mute hides the channel's items from the feed without touching them
    client.post(f"/api/feed/channel/{a['channel_id']}", json={'muted': 1})
    assert all(i['channel_id'] != a['channel_id'] for i in client.get('/api/feed/items').json())
    client.post(f"/api/feed/channel/{a['channel_id']}", json={'muted': 0})
    assert client.get('/api/feed/summary').json()['new'] == 4

def test_tiers_follow_library_signals(resolved):
    lib = resolved
    ff = _ff(); db = os.environ['ORG_DB']; c = sqlite3.connect(db)
    t = ff.compute_tiers(c)
    chans = {r[1]: r[0] for r in c.execute("select channel_id,handle from channels")}
    # test library: bbbbbbbbbbb is in two playlists but one video per channel -> daily everywhere unless watched
    assert t[chans['@fake-a']] == 'daily'
    c.execute("insert into watch_log(video_id,at,source) values('aaaaaaaaaaa',datetime('now'),'test')") if 'at' in {r[1] for r in c.execute('pragma table_info(watch_log)')} else None
    c.commit(); t = ff.compute_tiers(c)
    c.execute("delete from watch_log where source='test'"); c.commit(); c.close()

def test_one_stuck_video_does_not_block_the_feed(resolved):
    client = resolved; db = os.environ['ORG_DB']
    c = sqlite3.connect(db)
    c.execute("insert into videos(video_id,title,channel,title_source) values('NOURL000001','No link','Someone','oembed')"); c.commit(); c.close()
    assert client.get('/api/feed/channels').json()['pending']['need_url'] == 1
    client.post('/api/feed/resolve'); _wait(client)
    p = client.get('/api/feed/channels').json()['pending']
    assert p['need_url'] == 0                      # tried once, recorded, no longer pending
    client.post('/api/feed/resolve'); _wait(client)
    assert client.get('/api/feed/resolve/status').json()['total'] == 0   # a second R does not retry it
    # Retry All gives it another go
    client.post('/api/feed/unresolved/retry'); _wait(client)
    c = sqlite3.connect(db); assert c.execute("select channel_url from videos where video_id='NOURL000001'").fetchone()[0] == ''
    c.execute("delete from videos where video_id='NOURL000001'"); c.commit(); c.close()

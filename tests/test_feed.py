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
    assert after['linked'] == after['videos'] and after['pending'] == {'need_url': 0, 'need_id': 0}
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
    assert p == {'need_url': 1, 'need_id': 1}
    client.post('/api/feed/resolve'); _wait(client)
    r = client.get('/api/feed/channels').json()
    assert r['pending'] == {'need_url': 0, 'need_id': 1}
    assert len(r['unresolved']) == 1 and r['unresolved'][0]['channel_url'].endswith('@nochannel-x') and r['unresolved'][0]['n'] == 1
    c = sqlite3.connect(db)
    assert c.execute("select channel_url from videos where video_id='eeeeeeeeeee'").fetchone()[0] == 'https://www.youtube.com/@fake-e'
    assert c.execute("select channel_id from video_channel where video_id='eeeeeeeeeee'").fetchone()
    c.close()
    # retry clears the list and runs again; still unresolvable, so it comes back with n unchanged
    client.post('/api/feed/unresolved/retry'); _wait(client)
    assert len(client.get('/api/feed/channels').json()['unresolved']) == 1
    # leave the shared library as the import left it (the smoke test counts its videos)
    c = sqlite3.connect(db)
    c.execute("delete from videos where video_id in ('eeeeeeeeeee','fffffffffff')")
    c.execute("delete from video_channel where video_id in ('eeeeeeeeeee','fffffffffff')")
    c.execute("delete from channel_unresolved"); c.commit(); c.close()

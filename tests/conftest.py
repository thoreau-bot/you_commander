import os, sys, importlib, io, csv, tempfile, pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

@pytest.fixture(scope='session')
def client():
    """One app instance on a throwaway database, with every network-touching feature switched to its built-in test double."""
    tmp = tempfile.mkdtemp(prefix='yc_test_')
    os.environ.update(ORG_DB=os.path.join(tmp, 'organizer.db'), ORG_AUDIO_DIR=os.path.join(tmp, 'audio'), ORG_IMPORT_DIR=os.path.join(tmp, 'staging'),
                      ORG_OEMBED_FAKE='1', ORG_TRANSCRIPT_FAKE='1', ORG_FEED_FAKE='1', ORG_FEED_NO_POLLER='1', ORG_VOICE_FAKE_TRANSCRIPT='spoken test note')
    for m in ('app', 'importer', 'watch', 'transcripts', 'voice', 'feed', 'feed_fetch'):
        sys.modules.pop(m, None)
    app = importlib.import_module('app')
    from fastapi.testclient import TestClient
    with TestClient(app.app) as c:
        c.tmp = tmp
        yield c

def takeout_csvs():
    idx = io.StringIO(); w = csv.writer(idx)
    w.writerow(['Playlist ID', 'Playlist Title (Original)', 'Visibility', 'Playlist Create Timestamp', 'Playlist Update Timestamp', 'Video Order'])
    w.writerow(['PL1', 'Watch later', 'Private', '2024-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'Manual'])
    w.writerow(['PL2', 'Soldering', 'Private', '2024-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'Manual'])
    def vids(ids):
        b = io.StringIO(); x = csv.writer(b); x.writerow(['Video ID', 'Playlist Video Creation Timestamp'])
        for i, v in enumerate(ids): x.writerow([v, f'2025-01-{i + 1:02d}T00:00:00+00:00'])
        return b.getvalue().encode()
    return {'playlists.csv': idx.getvalue().encode(),
            'Watch later-videos.csv': vids(['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc']),
            'Soldering-videos.csv': vids(['bbbbbbbbbbb', 'ddddddddddd'])}


@pytest.fixture(scope='module')
def lib(client):
    """The imported test library (titles filled by the oEmbed test double), whichever test file runs first."""
    import time
    if client.get('/api/summary').json()['videos'] == 0:
        client.post('/api/import/reset')
        for n, d in takeout_csvs().items(): client.post('/api/import/stage', params={'name': n}, content=d)
        client.post('/api/import/run', json={'label': 'Test Account'})
    client.post('/api/import/titles')
    for _ in range(50):
        if not client.get('/api/import/status').json().get('running'): break
        time.sleep(0.1)
    return client

@pytest.fixture(scope='module')
def resolved(lib):
    """The library with every channel resolved (step 1), whatever order the tests ran in."""
    import time
    if lib.get('/api/feed/channels').json()['linked'] < 4:
        lib.post('/api/feed/resolve')
        for _ in range(100):
            if not lib.get('/api/feed/resolve/status').json().get('running'): break
            time.sleep(0.05)
    return lib

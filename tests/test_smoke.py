import io, json, time, zipfile, os
from conftest import takeout_csvs

def stage(client, name, data):
    return client.post('/api/import/stage', params={'name': name}, content=data).json()

def test_pages_serve(client):
    for path in ('/', '/import', '/triage', '/watch', '/history'):
        r = client.get(path)
        assert r.status_code == 200 and '<title>' in r.text
        assert '/static/app.css' in r.text

def test_static_assets_serve(client):
    assert client.get('/static/app.css').status_code == 200
    assert client.get('/static/app.js').status_code == 200

def test_import_flow(client):
    client.post('/api/import/reset')
    for n, d in takeout_csvs().items(): assert stage(client, n, d)['ok']
    p = client.get('/api/import/preview').json()
    assert p['playlists'] == 2 and p['unique_videos'] == 4 and p['items'] == 5
    r = client.post('/api/import/run', json={'label': 'Test Account'}).json()
    assert r['ok'] and r['videos_total'] == 4
    client.post('/api/import/titles')
    for _ in range(50):
        if not client.get('/api/import/status').json().get('running'): break
        time.sleep(0.1)
    names = {t['name'] for t in client.get('/api/tags').json()}
    assert {'Inbox', 'Soldering'} <= names
    vids = client.get('/api/videos').json()
    assert len(vids) == 4 and all(v['title'] for v in vids)
    assert client.get('/api/playlists').json()[0]['owner'] == 'Test Account'

def test_zip_import_reads_only_playlist_csvs(client):
    client.post('/api/import/reset')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for n, d in takeout_csvs().items(): z.writestr(f'Takeout/YouTube and YouTube Music/playlists/{n}', d)
        z.writestr('Takeout/YouTube and YouTube Music/history/watch-history.json', '{"secret": "SENTINEL-HISTORY"}')
        z.writestr('Takeout/YouTube and YouTube Music/comments/comments.csv', 'SENTINEL-COMMENT')
    r = stage(client, 'takeout.zip', buf.getvalue())
    assert r['ok'] and r['skipped'] == 2 and len(r['kept']) == 3
    staged = os.environ['ORG_IMPORT_DIR']
    blob = b''.join(open(os.path.join(staged, f), 'rb').read() for f in os.listdir(staged))
    assert b'SENTINEL' not in blob
    client.post('/api/import/reset')

def test_tagging_bulk_triage_and_undo(client):
    inbox = next(t for t in client.get('/api/tags').json() if t['name'] == 'Inbox')['id']
    sol = next(t for t in client.get('/api/tags').json() if t['name'] == 'Soldering')['id']
    r = client.post('/api/bulk', json={'video_ids': ['aaaaaaaaaaa', 'ccccccccccc'], 'action': 'add', 'tag_id': sol}).json()
    assert r['changed'] == 2
    v = client.get('/api/video/aaaaaaaaaaa').json()
    assert any(t['id'] == sol and t['confirmed'] for t in v['tags']) and not any(t['id'] == inbox for t in v['tags'])
    client.post('/api/video/aaaaaaaaaaa/triage', json={'action': 'confirm', 'note': 'keep this one'})
    v = client.get('/api/video/aaaaaaaaaaa').json()
    assert v['status'] == 'done' and v['note'] == 'keep this one'
    assert client.post('/api/bulk/undo').json()['restored'] == 2
    v = client.get('/api/video/ccccccccccc').json()
    assert any(t['id'] == inbox for t in v['tags'])
    batch = client.post('/api/videos/batch', json={'ids': ['aaaaaaaaaaa', 'bbbbbbbbbbb']}).json()
    assert [b['video_id'] for b in batch] == ['aaaaaaaaaaa', 'bbbbbbbbbbb']

def test_nested_tag_paths(client):
    r = client.post('/api/tags/path', json={'path': 'Projects / Shop / Lighting'}).json()
    assert r['id'] and len(r['created']) == 3
    assert client.post('/api/tags/path', json={'path': 'Projects / Shop / Lighting'}).json()['created'] == []

def test_watch_history_marks_and_queue(client):
    o = client.post('/api/watch/ddddddddddd/open', json={'source': 'watch'}).json()
    client.post('/api/watch/ddddddddddd/ping', json={'pos': 42, 'dur': 300, 'delta': 10, 'speed': 1.5, 'log_id': o['log_id'], 'loop_a': 10, 'loop_b': 20})
    st = client.get('/api/watch/ddddddddddd').json()['state']
    assert st['last_pos'] == 42 and st['speed'] == 1.5 and st['loop_a'] == 10 and st['plays'] == 1
    m = client.post('/api/watch/ddddddddddd/marks', json={'t': 65, 'body': 'check this', 'quote': 'a quoted line'}).json()
    marks = client.get('/api/watch/ddddddddddd').json()['marks']
    assert marks[0]['quote'] == 'a quoted line'
    client.request('PATCH', f"/api/watch/marks/{m['id']}", json={'body': 'edited'})
    assert client.get(f"/api/watch/marks/{m['id']}").json()['body'] == 'edited'
    v = client.post('/api/watch/ddddddddddd/marks/voice', params={'t': 5}, content=b'x' * 600, headers={'content-type': 'audio/webm'}).json()
    for _ in range(50):
        r = client.get(f"/api/watch/marks/{v['id']}").json()
        if r['status'] != 'transcribing': break
        time.sleep(0.1)
    assert r['body'] == 'spoken test note'
    q = client.post('/api/watch/queue', json={'ids': ['ddddddddddd', 'aaaaaaaaaaa']}).json()
    assert [x['video_id'] for x in q] == ['ddddddddddd', 'aaaaaaaaaaa']
    h = client.get('/api/history').json()
    assert h['items'][0]['video_id'] == 'ddddddddddd' and h['items'][0]['marks'] == 2

def test_transcripts_both_versions_and_search(client):
    assert client.post('/api/transcript/bbbbbbbbbbb', json={'method': 'captions'}).json()['queued'] == 1
    assert client.post('/api/transcript/bbbbbbbbbbb', json={'method': 'whisper'}).json()['queued'] in (0, 1)
    for _ in range(100):
        t = client.get('/api/transcript/bbbbbbbbbbb').json()
        if t['captions']['status'] == 'ok' and t['whisper']['status'] == 'ok': break
        time.sleep(0.1)
    assert t['captions']['cues'] and t['whisper']['cues']
    hits = [v['video_id'] for v in client.get('/api/videos', params={'search': 'Test caption line 7'}).json()]
    assert hits == ['bbbbbbbbbbb']
    client.delete('/api/transcript/bbbbbbbbbbb', params={'kind': 'captions'})
    assert client.get('/api/transcript/bbbbbbbbbbb').json()['captions']['status'] == 'missing'
    assert client.get('/api/transcript/bbbbbbbbbbb').json()['whisper']['status'] == 'ok'

def test_transcript_line_can_be_corrected_in_place(client):
    if client.get('/api/summary').json()['videos'] == 0: test_import_flow(client)
    assert client.post('/api/transcript/ccccccccccc', json={'method': 'captions'}).json()['queued'] == 1
    for _ in range(100):
        t = client.get('/api/transcript/ccccccccccc').json()
        if t['captions']['status'] == 'ok': break
        time.sleep(0.05)
    cues = t['captions']['cues']; assert len(cues) > 3 and t['captions']['edited'] == 0
    r = client.patch('/api/transcript/ccccccccccc/cue', json={'kind': 'captions', 'k': 2, 'text': '  The  FEP film   tears here. '}).json()
    assert r['ok'] and r['edited'] == 1
    t = client.get('/api/transcript/ccccccccccc').json()['captions']
    assert t['cues'][2][0] == cues[2][0] and t['cues'][2][1] == 'The FEP film tears here.' and t['cues'][2][2] == 1 and t['edited'] == 1
    # search sees the correction, and no longer the old words
    assert any(v['video_id'] == 'ccccccccccc' for v in client.get('/api/videos', params={'search': 'FEP film tears'}).json())
    # empty / out of range refused
    assert 'error' in client.patch('/api/transcript/ccccccccccc/cue', json={'kind': 'captions', 'k': 2, 'text': '  '}).json()
    assert 'error' in client.patch('/api/transcript/ccccccccccc/cue', json={'kind': 'captions', 'k': 99999, 'text': 'x'}).json()
    # a re-fetch will not silently overwrite edits; force does
    r = client.post('/api/transcript/ccccccccccc', json={'method': 'captions'}).json()
    assert r.get('edited') and 'error' in r
    client.delete('/api/transcript/ccccccccccc', params={'kind': 'captions'})

def test_transcript_line_time_can_be_changed_and_list_resorts(client):
    if client.get('/api/summary').json()['videos'] == 0: test_import_flow(client)
    client.post('/api/transcript/ddddddddddd', json={'method': 'captions'})
    for _ in range(100):
        t = client.get('/api/transcript/ddddddddddd').json()
        if t['captions']['status'] == 'ok': break
        time.sleep(0.05)
    cues = t['captions']['cues']; text3 = cues[3][1]
    # move line 3 to before line 0
    r = client.patch('/api/transcript/ddddddddddd/cue', json={'kind': 'captions', 'k': 3, 't': 0.5}).json()
    assert r['ok'] and r['k'] == 1 and r['t'] == 0.5 and r['text'] == text3      # line 0 is at 0.0, so it lands second
    t = client.get('/api/transcript/ddddddddddd').json()['captions']
    assert t['cues'][1] == [0.5, text3, 1] and [c[0] for c in t['cues']] == sorted(c[0] for c in t['cues'])
    assert 'error' in client.patch('/api/transcript/ddddddddddd/cue', json={'kind': 'captions', 'k': 1, 't': -3}).json()
    assert 'error' in client.patch('/api/transcript/ddddddddddd/cue', json={'kind': 'captions', 'k': 1}).json()
    client.delete('/api/transcript/ddddddddddd', params={'kind': 'captions'})

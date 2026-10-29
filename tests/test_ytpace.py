import time, ytpace

def test_pace_pauses_everyone_and_backs_off(monkeypatch):
    ytpace._until = 0; ytpace._penalty = 300; ytpace._last_hit = 0
    assert not ytpace.paused() and ytpace.status()['wait_s'] == 0
    t = ytpace.hit()
    assert ytpace.paused() and 290 <= ytpace.wait_s() <= 300 and ytpace.resume_at()
    t2 = ytpace.hit()                       # a second 429 soon after: the penalty doubles
    assert t2 > t and 590 <= ytpace.wait_s() <= 600
    ytpace._until = 0; ytpace._last_hit = time.time() - 4000   # a quiet hour later: back to the base
    ytpace.ok(); ytpace.hit()
    assert 290 <= ytpace.wait_s() <= 300
    ytpace._until = time.time() + 0.3
    assert ytpace.sleep_if_paused(lambda: False) is True and not ytpace.paused()
    ytpace._until = time.time() + 60
    assert ytpace.sleep_if_paused(lambda: True) is False     # a cancel breaks out
    ytpace._until = 0

def test_feed_and_transcript_status_carry_the_pace(client):
    assert 'pace' in client.get('/api/feed/summary').json()
    assert 'pace' in client.get('/api/transcripts/status').json()
    assert 'pace' in client.get('/api/transcript/aaaaaaaaaaa').json()

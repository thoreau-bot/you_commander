"""One pace for every request the app makes to youtube.com.

YouTube throttles per address, across everything (caption fetches, feed polls, Shorts probes). So the workers share
one clock: any 429 anywhere pauses all of them for a while, doubling on repeats, and resets after a quiet spell.
Captions the user asked for come first: the feed poller does not start while a transcript job is queued.
"""
import threading, time

_lock = threading.Lock()
_until = 0.0          # no YouTube requests before this time
_penalty = 300.0      # seconds; doubles on each 429 while a pause is still fresh, up to an hour
_last_hit = 0.0
MAX = 3600.0

def hit():
    """A 429 (or a 'confirm you are not a bot') came back. Pause everyone."""
    global _until, _penalty, _last_hit
    with _lock:
        now = time.time()
        if now - _last_hit < 1800: _penalty = min(MAX, _penalty * 2)   # repeat within half an hour: back off harder
        else: _penalty = 300.0
        _last_hit = now; _until = max(_until, now + _penalty)
        return _until

def ok():
    """A request went through; after a quiet half hour the penalty resets to the base."""
    global _penalty
    with _lock:
        if time.time() - _last_hit > 1800: _penalty = 300.0

def wait_s():
    """Seconds until YouTube requests may resume; 0 when clear."""
    return max(0.0, _until - time.time())

def paused():
    return wait_s() > 0

def resume_at():
    """ISO time (local) when the pause ends, or None."""
    return time.strftime('%H:%M', time.localtime(_until)) if paused() else None

def sleep_if_paused(stop=lambda: False, step=1.0):
    """Block until the pause ends, checking stop() every second. Returns False if stop() fired."""
    while paused():
        if stop(): return False
        time.sleep(step)
    return True

def status():
    return {'paused': paused(), 'resume_at': resume_at(), 'wait_s': int(wait_s())}

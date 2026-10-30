"""Feed, step 3: ranking from the library's own signals.

Nothing here talks to the network. The score of a feed item is built from what the library already knows about its
channel: how much of that channel has been watched, noted, kept or dropped in Triage. Every term is stored per item in
score_json so the page can show "why this?". Time is kept OUT of the stored score: recency is added at query time from
published_at and the current mode (Recent / Review), so flipping the mode never rescored anything.

Per-video engagement (library videos)
    completion = clamp(last_pos / duration, 0, 1)          NULL when never watched
    engagement = 0.55·completion + 0.25·[note or mark] + 0.20·[kept in triage]      (0 … 1)
Channel affinity
    pos        = sigmoid((Σ engagement − mean) / sd)         NULL engagement counts 0.1 (saving it was a weak yes);
                                                             a pull from the feed counts 0.2
    drop_ratio = dropped / (kept + dropped)                  0 when never triaged; no penalty under 3 decisions
    affinity   = clamp(pos − DROP_STRENGTH · drop_ratio², 0, 1)
Item base score
    base = W_CHAN·affinity + seen + dup                      seen: already in the library (hidden); dup: same channel,
                                                             near-identical title already saved
Displayed score
    score = base + W_RECENT(mode) · 2 ** (−age_h / HALF_LIFE_H(mode))
"""
import json, math, re, sqlite3, threading, time, datetime as dt

W = dict(chan=0.40, topic=0.30, topic2=0.10, seen=-1.0, dup=-0.5, drop_strength=0.8, min_decisions=3, pull_weight=0.2, saved_weight=0.1)
MODES = {'recent': dict(half_life_h=72.0, w_recent=0.30, window_days=7), 'review': dict(half_life_h=240.0, w_recent=0.12, window_days=21)}
RETENTION_DAYS = 60

SCHEMA = """
create table if not exists channel_affinity(channel_id TEXT PRIMARY KEY, n_library INTEGER NOT NULL, n_watched INTEGER NOT NULL,
  mean_completion REAL, n_noted INTEGER NOT NULL, n_kept INTEGER NOT NULL, n_dropped INTEGER NOT NULL, n_pulled INTEGER NOT NULL,
  w_raw REAL NOT NULL, drop_ratio REAL, affinity REAL NOT NULL, computed_at TEXT NOT NULL);
"""

def now(): return dt.datetime.utcnow().isoformat(timespec='seconds')

def ensure_schema(path):
    c = sqlite3.connect(path); c.executescript(SCHEMA); c.commit(); c.close()

def _sigmoid(x): return 1.0 / (1.0 + math.exp(-x))

# ---------------------------------------------------------------- channel affinity
def compute_affinity(c):
    """Rebuild channel_affinity for every channel. Pure SQL + a little Python; a few hundred ms for thousands of channels."""
    rows = c.execute("""
        select x.channel_id,
               count(*)                                                                                  n_library,
               sum(case when s.last_pos is not null and s.duration > 0 then 1 else 0 end)                 n_watched,
               avg(case when s.duration > 0 then min(1.0, s.last_pos / s.duration) end)                   mean_completion,
               sum(case when exists(select 1 from notes n where n.video_id=x.video_id)
                          or exists(select 1 from video_marks m where m.video_id=x.video_id) then 1 else 0 end) n_noted,
               sum(case when t.status='done' then 1 else 0 end)                                            n_kept,
               sum(case when t.status='dropped' then 1 else 0 end)                                         n_dropped,
               sum(case when v.pulled_at is not null then 1 else 0 end)                                    n_pulled,
               sum( case when s.duration > 0 or exists(select 1 from notes n where n.video_id=x.video_id)
                              or exists(select 1 from video_marks m where m.video_id=x.video_id) or t.status='done'
                    then 0.55 * coalesce(case when s.duration > 0 then min(1.0, s.last_pos / s.duration) end, 0)
                       + 0.25 * (case when exists(select 1 from notes n where n.video_id=x.video_id)
                                          or exists(select 1 from video_marks m where m.video_id=x.video_id) then 1 else 0 end)
                       + 0.20 * (case when t.status='done' then 1 else 0 end)
                    else ? end
                  + case when v.pulled_at is not null then ? else 0 end )                                  w_raw
        from video_channel x
        join videos v on v.video_id = x.video_id
        left join watch_state s on s.video_id = x.video_id
        left join triage t on t.video_id = x.video_id
        group by x.channel_id""", (W['saved_weight'], W['pull_weight'])).fetchall()
    if not rows: return 0
    ws = [r[8] for r in rows]; mean = sum(ws) / len(ws)
    sd = math.sqrt(sum((w - mean) ** 2 for w in ws) / len(ws)) or 1.0
    t = now(); out = []
    for cid, n_lib, n_w, mc, n_noted, n_kept, n_drop, n_pulled, w_raw in rows:
        pos = _sigmoid((w_raw - mean) / sd)
        dec = (n_kept or 0) + (n_drop or 0)
        dr = (n_drop / dec) if dec else None
        pen = W['drop_strength'] * dr * dr if (dr is not None and dec >= W['min_decisions']) else 0.0
        aff = max(0.0, min(1.0, pos - pen))
        out.append((cid, n_lib, n_w or 0, mc, n_noted or 0, n_kept or 0, n_drop or 0, n_pulled or 0, w_raw, dr, aff, t))
    c.execute("delete from channel_affinity")
    c.executemany("insert into channel_affinity values(?,?,?,?,?,?,?,?,?,?,?,?)", out)
    c.commit(); return len(out)

# ---------------------------------------------------------------- items
_WORD = re.compile(r'[a-z0-9]+')
def _tokens(s): return set(_WORD.findall((s or '').lower()))

def score_items(c, only_unscored=False):
    """base_score + score_json for every feed item that is new/seen (or only those without a score)."""
    aff = {r[0]: r[1:] for r in c.execute("select channel_id, affinity, n_library, n_watched, mean_completion, n_noted, n_kept, n_dropped, drop_ratio from channel_affinity")}
    lib_titles = {}
    for cid, title in c.execute("select x.channel_id, v.title from video_channel x join videos v using(video_id) where v.title is not null"):
        lib_titles.setdefault(cid, []).append(_tokens(title))
    lib_ids = {r[0] for r in c.execute("select video_id from videos")}
    where = "state in ('new','seen')" + (" and base_score is null" if only_unscored else "")
    rows = c.execute(f"select video_id, channel_id, title from feed_items where {where}").fetchall()
    t = now(); n = 0; upd = []
    for vid, cid, title in rows:
        a = aff.get(cid)
        chan = a[0] if a else 0.5
        terms = {'chan': round(W['chan'] * chan, 4)}
        why = {'affinity': round(chan, 3)}
        if a:
            why.update(n_library=a[1], n_watched=a[2], mean_completion=round(a[3], 2) if a[3] is not None else None, n_noted=a[4], n_kept=a[5], n_dropped=a[6], drop_ratio=round(a[7], 2) if a[7] is not None else None)
        seen = W['seen'] if vid in lib_ids else 0.0
        if seen: terms['seen'] = seen
        dup = 0.0
        tk = _tokens(title)
        if len(tk) >= 3:
            for lt in lib_titles.get(cid, ()):
                if lt and len(tk & lt) / len(tk | lt) > 0.8: dup = W['dup']; break
        if dup: terms['dup'] = dup
        base = round(sum(terms.values()), 4)
        upd.append((base, json.dumps({'terms': terms, 'why': why}), t, vid)); n += 1
    c.executemany("update feed_items set base_score=?, score_json=?, scored_at=? where video_id=?", upd)
    c.commit(); return n

def retention(c):
    """Items older than RETENTION_DAYS that nobody acted on go hidden (never deleted)."""
    cut = (dt.datetime.utcnow() - dt.timedelta(days=RETENTION_DAYS)).isoformat(timespec='seconds')
    n = c.execute("update feed_items set state='hidden', state_at=? where state='new' and published_at < ?", (now(), cut)).rowcount
    c.commit(); return n

def rescore(path):
    c = sqlite3.connect(path, timeout=30); c.execute('pragma busy_timeout=30000')
    try:
        compute_affinity(c); n = score_items(c); retention(c); return n
    finally:
        c.close()

# ---------------------------------------------------------------- debounced rescoring
_T = [None]; _LOCK = threading.Lock()
def dirty(path, delay=60.0):
    """Something that feeds the score changed (tags, watch state, triage, a pull). Rescore once, a minute later."""
    with _LOCK:
        if _T[0]: _T[0].cancel()
        t = threading.Timer(delay, lambda: rescore(path)); t.daemon = True; t.start(); _T[0] = t

# ---------------------------------------------------------------- query-time recency
def mode_params(mode): return MODES.get(mode or 'recent', MODES['recent'])

def ranked_sql(mode):
    """ORDER BY expression adding the recency term to base_score, computed in SQL from published_at."""
    p = mode_params(mode)
    # 2 ** (−age_h / H) == exp(−age_h · ln2 / H); age_h from julianday differences (days × 24)
    return f"(coalesce(i.base_score,0) + {p['w_recent']} * exp(-(julianday('now') - julianday(i.published_at)) * 24.0 * {math.log(2) / p['half_life_h']}))"

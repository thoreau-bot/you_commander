"""Builds demo_data/organizer.db: an invented library (made-up video ids and titles) so you can try YouCommander
without importing anything of your own. Run from the project folder:  python tools/make_demo.py"""
import os, sys, random, sqlite3, csv, io, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB = os.environ.get('ORG_DB', os.path.join(ROOT, 'demo_data', 'organizer.db'))
os.makedirs(os.path.dirname(DB), exist_ok=True)
if os.path.exists(DB): os.remove(DB)
import importer
random.seed(7)
ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
def vid(): return 'DEMO' + ''.join(random.choice(ALPHA) for _ in range(7))   # obviously fake, 11 characters
TOPICS = {
 'Watch later': [],
 '3D Printing': ['Calibrating a first layer in five minutes', 'Why your prints warp (and four fixes)', 'Resin vs filament: which should you buy?', 'Tuning retraction without guessing', 'Designing snap-fit enclosures', 'A beginner\'s guide to supports', 'Printing flexible TPU reliably', 'Input shaping explained simply'],
 'Electronics Repair': ['Fixing a dead bench power supply', 'Reflowing a cracked BGA joint', 'Finding a short with a thermal camera', 'Capacitor swap on an old amplifier', 'Hot air station buyer\'s guide', 'Reading schematics for repairs', 'Diagnosing a boot loop'],
 '3D Scanning': ['Scanning shiny parts without spray', 'Photogrammetry vs structured light', 'Turning a scan into a printable model', 'Cleaning up a noisy mesh', 'Scanning a car interior'],
 'Workshop Tips': ['A tidy bench in a small space', 'Lighting your workshop for filming', 'Labeling every drawer, once', 'Cheap tools that earn their place', 'Soldering fume extraction on a budget'],
 'Channel Ideas': ['Ten channel intros that work', 'How to storyboard a repair video', 'Lighting for close-up macro shots', 'Editing a tutorial in half the time', 'Audio mistakes that lose viewers', 'Thumbnails: what to test first'],
}
CHANNELS = ['Example Maker', 'Bench Notes', 'Layer by Layer', 'Probe & Solder', 'Scan Lab', 'The Tidy Shop', 'Frame Rate Films']
items, ids_by_pl = {}, {}
for pl, titles in TOPICS.items():
    n = 28 if pl == 'Watch later' else len(titles)
    ids_by_pl[pl] = [vid() for _ in range(n)]
# Watch later holds some of the same videos plus some untriaged extras
extras = ids_by_pl['Watch later']
pool = [v for k, vs in ids_by_pl.items() if k != 'Watch later' for v in vs]
ids_by_pl['Watch later'] = extras[:20] + random.sample(pool, 8)
titles = {}
for pl, tl in TOPICS.items():
    for v, t in zip(ids_by_pl[pl], tl): titles[v] = t
for v in ids_by_pl['Watch later']:
    titles.setdefault(v, random.choice(['Quick tip: ', 'Review: ', 'Build log: ', 'Q&A: ']) + random.choice(['mystery gadget', 'the cheap one vs the good one', 'my first week with it', 'what I would do differently', 'everything that went wrong']))
# 1. write Takeout-shaped CSVs into the import staging folder and import them the normal way
os.environ['ORG_IMPORT_DIR'] = os.path.join(os.path.dirname(DB), 'import_staging')
importer.ensure_schema(DB); importer.reset_staging(DB)
idx = io.StringIO(); w = csv.writer(idx)
w.writerow(['Playlist ID', 'Playlist Title (Original)', 'Visibility', 'Playlist Create Timestamp', 'Playlist Update Timestamp', 'Video Order'])
for k, pl in enumerate(TOPICS): w.writerow([f'PLDEMO{k:04d}', pl, 'Private', '2024-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'Manual'])
importer.keep_csv(DB, 'playlists.csv', idx.getvalue().encode())
for pl, vs in ids_by_pl.items():
    b = io.StringIO(); w = csv.writer(b); w.writerow(['Video ID', 'Playlist Video Creation Timestamp'])
    for i, v in enumerate(vs): w.writerow([v, f'2025-{1 + i % 12:02d}-{1 + i % 27:02d}T12:00:00+00:00'])
    importer.keep_csv(DB, f'{pl}-videos.csv', b.getvalue().encode())
print(importer.run_import(DB, 'Demo Account'))
# 2. fill in titles and channels directly (the real app fetches them from YouTube's oEmbed endpoint)
c = sqlite3.connect(DB)
for v, t in titles.items(): c.execute("update videos set title=?,channel=?,title_source='demo' where video_id=?", (t, random.choice(CHANNELS), v))
# 3. a little triage history so every page has something to show
c.execute("insert or ignore into tags(name,slug,parent_id,kind,publish) select 'Cameras','3d-printing-cameras',(select id from tags where name='3D Printing'),'topic',0")
done = random.sample(ids_by_pl['Channel Ideas'], 3)
for v in done:
    c.execute("update triage set status='done',triaged_at=datetime('now') where video_id=?", (v,))
    c.execute("update video_tags set confirmed=1 where video_id=?", (v,))
c.execute("insert or replace into notes(video_id,body,updated_at) values(?,?,datetime('now'))", (done[0], 'Good reference for pacing: cuts every 4 seconds in the first minute.'))
c.commit(); c.close()
importer.rebuild_fts(DB)
print('Demo library ready:', DB)

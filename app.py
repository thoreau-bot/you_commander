import os,re,sqlite3
from fastapi import FastAPI,Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
DB=os.environ.get('ORG_DB','organizer.db')
app=FastAPI()
import threading,time,json as _json
from fastapi import Request
import voice, importer
from fastapi.responses import JSONResponse
AUDIO_DIR=os.environ.get('ORG_AUDIO_DIR',os.path.join(os.path.dirname(os.path.abspath(DB)),'audio'))
def _init_voice():
    c=sqlite3.connect(DB,timeout=30)
    c.execute("create table if not exists audio_notes(id INTEGER PRIMARY KEY,video_id TEXT,path TEXT,created_at TEXT,transcript TEXT,status TEXT,extracted TEXT,error TEXT)")
    c.commit();c.close();os.makedirs(AUDIO_DIR,exist_ok=True)

importer.ensure_schema(DB)
def _touch():
    try:
        import feed_fetch;feed_fetch.touch()
    except Exception:pass
def q(sql,a=()):
    _touch();c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row
    r=[dict(x) for x in c.execute(sql,a)];c.close();return r
def w(sql,a=()):
    _touch();c=sqlite3.connect(DB,timeout=30);cur=c.execute(sql,a);c.commit();i=cur.lastrowid;c.close();return i
AUD=['recent_adds','duplicates','unavailable','untagged_inbox']
_FTS_T=None
def _fts_rebuild():
    c=sqlite3.connect(DB,isolation_level=None)
    try:
        c.execute('begin immediate')
        c.execute("drop table if exists video_fts")
        c.execute("create virtual table video_fts using fts5(title,channel,tags,notes,content='')")
        c.execute("""insert into video_fts(rowid,title,channel,tags,notes) select v.rowid,coalesce(v.title,''),coalesce(v.channel,''),
          coalesce((select group_concat(t.name,' ') from video_tags vt join tags t on t.id=vt.tag_id where vt.video_id=v.video_id),''),coalesce((select n.body from notes n where n.video_id=v.video_id),'')||' '||coalesce((select group_concat(m.body,' ') from video_marks m where m.video_id=v.video_id),'') from videos v""")
        c.execute('commit')
    except Exception:
        try: c.execute('rollback')
        except Exception: pass
    finally: c.close()
def _fts_shape_ok():
    try:
        c=sqlite3.connect(DB,timeout=30);r=c.execute("select sql from sqlite_master where name='video_fts'").fetchone();c.close()
        return bool(r and 'notes' in r[0])
    except Exception: return False
if not _fts_shape_ok(): threading.Thread(target=_fts_rebuild,daemon=True).start()
def fts_dirty(delay=1.0):
    """Tags changed: rebuild the search index shortly (coalesces bursts such as triage confirms)."""
    global _FTS_T
    if _FTS_T: _FTS_T.cancel()
    _FTS_T=threading.Timer(delay,_fts_rebuild);_FTS_T.daemon=True;_FTS_T.start()
@app.get('/api/tags')
def tags():
    return q("""select t.*,(select count(*) from video_tags v where v.tag_id=t.id) n,
      (select count(*) from video_tags v where v.tag_id=t.id and v.confirmed=1) confirmed from tags t order by coalesce(parent_id,0),sort,name""")
@app.get('/api/videos')
def videos(tag:int|None=None,search:str|None=None,audit:str|None=None,limit:int=200,offset:int=0):
    if audit:
        if audit not in AUD: return []
        return q(f"select a.*,(select group_concat(t.name,', ') from video_tags vt join tags t on t.id=vt.tag_id where vt.video_id=a.video_id) tags from audit_{audit} a limit ? offset ?",(limit,offset))
    where,a=[],[]
    sel="select v.video_id,v.title,v.channel,v.unavailable,(select group_concat(t.name,', ') from video_tags vt join tags t on t.id=vt.tag_id where vt.video_id=v.video_id) tags from videos v"
    if tag: where.append("v.video_id in (select video_id from video_tags where tag_id=?)");a.append(tag)
    if search:
        s=' '.join(f'"{x}"*' for x in re.findall(r'\w+',search))
        if not s: return []
        if s:
            where.append("(v.rowid in (select rowid from video_fts where video_fts match ?) or v.video_id in (select video_id from transcript_fts where transcript_fts match ?))");a.append(s);a.append(s)
    sql=sel+(' where '+' and '.join(where) if where else '')+' order by (v.title is null), v.title collate nocase limit ? offset ?'
    return q(sql,a+[limit,offset])
@app.get('/api/summary')
def summary():
    r={k:q(f"select count(*) n from audit_{k}")[0]['n'] for k in AUD}
    r['videos']=q("select count(*) n from videos")[0]['n'];r['tags']=q("select count(*) n from tags")[0]['n'];r['playlists']=q("select count(*) n from playlists")[0]['n'];return r
class TagIn(BaseModel):
    name:str|None=None;parent_id:int|None=None;publish:int|None=None;kind:str|None=None;description:str|None=None;set_parent:bool=False
@app.post('/api/tags')
def new(t:TagIn):
    if q("select 1 from tags where lower(name)=lower(?) and coalesce(parent_id,0)=coalesce(?,0)",(t.name.strip(),t.parent_id)): return {'error':'A tag with that name already exists here'}
    s=re.sub(r'[^a-z0-9]+','-',t.name.lower()).strip('-');base=s;n=2
    while q("select 1 from tags where slug=?",(s,)): s=f'{base}-{n}';n+=1
    return {'id':w("insert into tags(name,slug,parent_id,kind) values(?,?,?,?)",(t.name,s,t.parent_id,t.kind or 'topic'))}
@app.patch('/api/tags/{tid}')
def upd(tid:int,t:TagIn):
    for f in ('name','publish','kind','description'):
        v=getattr(t,f)
        if v is not None: w(f"update tags set {f}=? where id=?",(v,tid))
    if t.name is not None: fts_dirty()
    if t.set_parent:
        p=t.parent_id;x=p
        while x:  # no cycles
            if x==tid: return {'error':'cycle'}
            r=q("select parent_id from tags where id=?",(x,));x=r[0]['parent_id'] if r else None
        w("update tags set parent_id=? where id=?",(p,tid))
    return {'ok':1}
@app.get('/api/playlists')
def playlists():
    return q("""select p.pk,p.account_id,p.title,p.visibility,p.item_count,coalesce(a.name,p.account_id) owner
      from playlists p left join accounts a on a.id=p.account_id order by owner,p.title collate nocase""")
class PathIn(BaseModel): path:str
@app.post('/api/tags/path')
def tag_path(b:PathIn):
    segs=[x.strip() for x in b.path.split('/') if x.strip()]
    if not segs: return {'error':'empty'}
    c=sqlite3.connect(DB,timeout=30);parent=None;created=[]
    for name in segs:
        r=c.execute("select id from tags where lower(name)=lower(?) and coalesce(parent_id,0)=coalesce(?,0)",(name,parent)).fetchone()
        if r: parent=r[0];continue
        sl=re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-') or 'x';base=sl;k=2
        while c.execute('select 1 from tags where slug=?',(sl,)).fetchone(): sl=f'{base}-{k}';k+=1
        parent=c.execute("insert into tags(name,slug,parent_id,kind,publish) values(?,?,?,'topic',0)",(name,sl,parent)).lastrowid;created.append(name)
    c.commit();c.close();return {'id':parent,'created':created}
class Bulk(BaseModel): video_ids:list[str]; action:str; tag_id:int|None=None
def _inbox(c):
    r=c.execute("select id from tags where name='Inbox'").fetchone();return r[0] if r else None
@app.post('/api/bulk')
def bulk(b:Bulk):
    c=sqlite3.connect(DB,timeout=30)
    c.execute("create table if not exists bulk_log(op INTEGER,video_id TEXT,tag_id INTEGER,added INTEGER DEFAULT 0,removed_tag INTEGER DEFAULT 0,prev_confirmed INTEGER,had_inbox INTEGER DEFAULT 0,prev_status TEXT)")
    tag=b.tag_id
    if b.action=='trash':
        r=c.execute("select id from tags where lower(name)='trash'").fetchone()
        if r: tag=r[0]
        else:
            tag=c.execute("insert into tags(name,slug,kind,publish,description) values('Trash','trash','status',0,'Never published. Videos tagged Trash are excluded from every published playlist.')").lastrowid
    if not tag: return {'error':'no tag'}
    ib=_inbox(c);op=(c.execute("select coalesce(max(op),0) from bulk_log").fetchone()[0])+1;n=0
    for v in dict.fromkeys(b.video_ids):
        ex=c.execute("select confirmed from video_tags where video_id=? and tag_id=?",(v,tag)).fetchone()
        if b.action in('add','trash'):
            added=0;pc=None
            if ex is None: c.execute("insert into video_tags(video_id,tag_id,source,confirmed) values(?,?, 'bulk',1)",(v,tag));added=1
            elif ex[0]==0: c.execute("update video_tags set confirmed=1 where video_id=? and tag_id=?",(v,tag));pc=0
            hi=0
            if ib and tag!=ib and c.execute("select 1 from video_tags where video_id=? and tag_id=?",(v,ib)).fetchone():
                c.execute("delete from video_tags where video_id=? and tag_id=?",(v,ib));hi=1
            ps=None
            if b.action=='trash':
                ps=(c.execute("select status from triage where video_id=?",(v,)).fetchone() or [None])[0]
                if ps in('new','imported'): c.execute("update triage set status='done',triaged_at=datetime('now') where video_id=?",(v,))
                else: ps=None
            c.execute("insert into bulk_log(op,video_id,tag_id,added,prev_confirmed,had_inbox,prev_status) values(?,?,?,?,?,?,?)",(op,v,tag,added,pc,hi,ps));n+=1
        elif b.action=='remove' and ex is not None:
            c.execute("delete from video_tags where video_id=? and tag_id=?",(v,tag))
            c.execute("insert into bulk_log(op,video_id,tag_id,removed_tag,prev_confirmed) values(?,?,?,1,?)",(op,v,tag,ex[0]));n+=1
    c.commit();c.close();fts_dirty();return {'ok':1,'changed':n,'op':op,'tag_id':tag}
@app.post('/api/bulk/undo')
def bulk_undo():
    c=sqlite3.connect(DB,timeout=30)
    try: op=c.execute("select max(op) from bulk_log").fetchone()[0]
    except Exception: op=None
    if not op: return {'error':'nothing to undo'}
    ib=_inbox(c);n=0
    for v,t,added,rem,pc,hi,ps in c.execute("select video_id,tag_id,added,removed_tag,prev_confirmed,had_inbox,prev_status from bulk_log where op=?",(op,)).fetchall():
        if rem: c.execute("insert or ignore into video_tags(video_id,tag_id,source,confirmed) values(?,?, 'restored',?)",(v,t,pc if pc is not None else 1))
        elif added: c.execute("delete from video_tags where video_id=? and tag_id=?",(v,t))
        elif pc==0: c.execute("update video_tags set confirmed=0 where video_id=? and tag_id=?",(v,t))
        if hi and ib: c.execute("insert or ignore into video_tags(video_id,tag_id,source,confirmed) values(?,?, 'import',1)",(v,ib))
        if ps: c.execute("update triage set status=? where video_id=?",(ps,v))
        n+=1
    c.execute("delete from bulk_log where op=?",(op,));c.commit();c.close();fts_dirty();return {'ok':1,'restored':n}
@app.get('/api/bulk/last')
def bulk_last():
    try: return q("select op,count(*) n from bulk_log where op=(select max(op) from bulk_log) group by op")
    except Exception: return []
class Merge(BaseModel): into:int
@app.post('/api/tags/{tid}/merge')
def merge(tid:int,m:Merge):
    if tid==m.into: return {'error':'same'}
    c=sqlite3.connect(DB,timeout=30)
    c.execute("insert or ignore into video_tags(video_id,tag_id,source,confidence,confirmed) select video_id,?,source,confidence,confirmed from video_tags where tag_id=?",(m.into,tid))
    c.execute("update video_tags set confirmed=1 where tag_id=? and video_id in (select video_id from video_tags where tag_id=? and confirmed=1)",(m.into,tid))
    c.execute("delete from video_tags where tag_id=?",(tid,))
    c.execute("update tags set parent_id=? where parent_id=?",(m.into,tid))
    c.execute("delete from tags where id=?",(tid,));c.commit();c.close();fts_dirty();return {'ok':1}
@app.get('/api/triage/queue')
def tqueue(limit:int=400,offset:int=0,status:str='open',tag:int|None=None,video:str|None=None):
    if video: return q("select video_id from videos where video_id=?",(video,))
    st="('new','imported')" if status=='open' else "('dropped')" if status=='dropped' else "('done')"
    f=" and v.video_id in (select video_id from video_tags where tag_id=%d)"%tag if tag else ""
    return q(f"select v.video_id from videos v join triage t using(video_id) where t.status in {st}{f} order by (t.status='imported'), v.video_id limit ? offset ?",(limit,offset))
@app.get('/api/triage/counts')
def tcounts(): return q("select status,count(*) n from triage group by 1")
@app.get('/api/video/{vid}')
def video(vid:str):
    v=q("select video_id,title,channel,unavailable from videos where video_id=?",(vid,))
    if not v: return {}
    v=v[0]
    v['tags']=q("select t.id,t.name,t.description,vt.confirmed,vt.source from video_tags vt join tags t on t.id=vt.tag_id where vt.video_id=? order by t.name",(vid,))
    n=q("select body from notes where video_id=?",(vid,));v['note']=n[0]['body'] if n else ''
    v['status']=q("select status from triage where video_id=?",(vid,))[0]['status']
    v['playlists']=q("select p.title,p.account_id from playlist_items i join playlists p on p.pk=i.playlist_pk where i.video_id=?",(vid,))
    return v
class Ids(BaseModel): ids:list[str]
@app.post('/api/videos/batch')
def videos_batch(b:Ids):
    out=[]
    for v in list(dict.fromkeys(b.ids))[:300]:
        r=video(v)
        if r: out.append(r)
    return out
class BSug(BaseModel): video_ids:list[str]; tag_ids:list[int]
@app.post('/api/bulk/suggest')
def bulk_suggest(b:BSug):
    c=sqlite3.connect(DB,timeout=30)
    for v in b.video_ids:
        for t in b.tag_ids: c.execute("insert or ignore into video_tags(video_id,tag_id,source,confirmed) values(?,?, 'voice',0)",(v,t))
    c.commit();c.close();fts_dirty();return {'ok':1}
class VT(BaseModel): tag_id:int
@app.post('/api/video/{vid}/tags')
def addtag(vid:str,b:VT):
    w("insert into video_tags(video_id,tag_id,source,confirmed) values(?,?, 'manual',1) on conflict(video_id,tag_id) do update set confirmed=1",(vid,b.tag_id))
    w("delete from video_tags where video_id=? and tag_id in (select id from tags where name='Inbox') and ?!=(select id from tags where name='Inbox')",(vid,b.tag_id));fts_dirty();return {'ok':1}
@app.delete('/api/video/{vid}/tags/{tid}')
def rmtag(vid:str,tid:int):
    w("delete from video_tags where video_id=? and tag_id=?",(vid,tid));fts_dirty();return {'ok':1}
class Act(BaseModel): action:str; note:str|None=None
@app.post('/api/video/{vid}/triage')
def act(vid:str,a:Act):
    c=sqlite3.connect(DB,timeout=30)
    if a.note is not None:
        if a.note.strip(): c.execute("insert into notes(video_id,body,updated_at) values(?,?,datetime('now')) on conflict(video_id) do update set body=excluded.body,updated_at=excluded.updated_at",(vid,a.note))
        else: c.execute("delete from notes where video_id=?",(vid,))
    if a.action=='confirm':  # confirm every non-Inbox tag, drop the Inbox marker, mark done
        c.execute("update video_tags set confirmed=1 where video_id=? and tag_id not in (select id from tags where name='Inbox')",(vid,))
        c.execute("delete from video_tags where video_id=? and tag_id in (select id from tags where name='Inbox')",(vid,))
        c.execute("update triage set status='done',triaged_at=datetime('now') where video_id=?",(vid,))
    elif a.action=='drop': c.execute("update triage set status='dropped',triaged_at=datetime('now') where video_id=?",(vid,))
    elif a.action=='reopen': c.execute("update triage set status='new' where video_id=?",(vid,))
    c.commit();c.close()
    if a.action in('confirm','note') or a.note is not None: fts_dirty()
    return {'ok':1}
_init_voice()
import watch
watch.on_change=lambda:fts_dirty()
watch.setup(app,DB,video,AUDIO_DIR)
import transcripts
transcripts.setup(app,DB)
import feed
feed.setup(app,DB)
@app.get('/api/voice/status')
def voice_status():
    o=voice.ollama_status() if voice.CFG['fake_transcript'] is None or True else {}
    return {'whisper':voice.whisper_installed() or voice.CFG['fake_transcript'] is not None,'ollama':o,'whisper_model':voice.CFG['whisper_model'],'ollama_model':voice.CFG['ollama_model'],'device_setting':voice.CFG['whisper_device']}
@app.post('/api/video/{vid}/audio')
async def audio_upload(vid:str,request:Request):
    data=await request.body()
    if len(data)<500: return {'error':'recording too short'}
    ext='webm' if 'webm' in (request.headers.get('content-type') or '') else 'ogg' if 'ogg' in (request.headers.get('content-type') or '') else 'bin'
    p=os.path.join(AUDIO_DIR,f"{vid}_{int(time.time()*1000)}.{ext}")
    open(p,'wb').write(data)
    aid=w("insert into audio_notes(video_id,path,created_at,status) values(?,?,datetime('now'),'processing')",(vid,p))
    threading.Thread(target=voice.process,args=(DB,aid),daemon=True).start()
    return {'id':aid}
@app.get('/api/audio/{aid}')
def audio_get(aid:int):
    r=q("select id,video_id,status,transcript,extracted,error from audio_notes where id=?",(aid,))
    if not r: return {}
    r=r[0];r['extracted']=_json.loads(r['extracted']) if r['extracted'] else None;return r
from fastapi.staticfiles import StaticFiles
app.mount('/static',StaticFiles(directory=os.path.join(os.path.dirname(__file__),'static')),name='static')
@app.get('/triage',response_class=HTMLResponse)
def triage_page(): return open(os.path.join(os.path.dirname(__file__),'triage.html'),encoding='utf-8').read()
@app.get('/',response_class=HTMLResponse)
def home(): return open(os.path.join(os.path.dirname(__file__),'ui.html'),encoding='utf-8').read()

# ---------------- first-run Google Takeout import ----------------
@app.get('/import',response_class=HTMLResponse)
def import_page(): return open(os.path.join(os.path.dirname(__file__),'import.html'),encoding='utf-8').read()
@app.post('/api/import/reset')
def imp_reset(): importer.reset_staging(DB);return {'ok':True}
@app.post('/api/import/stage')
async def imp_stage(request:Request,name:str):
    d=importer.staging_dir(DB);lower=name.lower()
    tmp=os.path.join(d,'_upload.tmp')
    with open(tmp,'wb') as f:
        async for ch in request.stream(): f.write(ch)
    try:
        if lower.endswith('.zip'):
            kept,skipped=importer.stage_zip(DB,tmp);return {'ok':True,'kept':kept,'skipped':skipped,'zip':True}
        if lower.endswith('.csv'):
            with open(tmp,'rb') as f: data=f.read()
            b=importer.keep_csv(DB,name,data);return {'ok':bool(b),'kept':[b] if b else [],'skipped':0}
        return {'ok':False,'kept':[],'skipped':1}
    except Exception as e: return JSONResponse({'ok':False,'error':str(e)},status_code=400)
    finally:
        try: os.remove(tmp)
        except OSError: pass
@app.get('/api/import/preview')
def imp_preview(): return importer.preview(DB)
class ImpRun(BaseModel): label:str|None=None
@app.post('/api/import/run')
def imp_run(b:ImpRun):
    r=importer.run_import(DB,b.label)
    if r.get('ok') and r.get('need_titles'): importer.start_titles(DB)
    return r
@app.post('/api/import/titles')
def imp_titles(): return {'started':importer.start_titles(DB),'pending':len(importer.need_titles(DB))}
@app.get('/api/import/status')
def imp_status():
    t=dict(importer.TITLES);t['pending']=len(importer.need_titles(DB)) if not t['running'] else max(0,t['total']-t['done']);return t

"""Local voice notes: faster-whisper transcription + Ollama tag extraction.
Everything is optional and degrades gracefully. No NPU/OpenVINO dependency: GPU (CUDA) if present, else CPU."""
import os,sys,json,glob,threading,sqlite3,urllib.request,urllib.error,re
CFG=dict(
 whisper_model=os.environ.get('ORG_WHISPER_MODEL','large-v3-turbo'),
 whisper_device=os.environ.get('ORG_WHISPER_DEVICE','auto'),   # auto | cuda | cpu
 whisper_lang=os.environ.get('ORG_WHISPER_LANG','en'),
 ollama_url=os.environ.get('ORG_OLLAMA_URL','http://127.0.0.1:11434'),
 ollama_model=os.environ.get('ORG_OLLAMA_MODEL','qwen2.5:14b-instruct'),
 fake_transcript=os.environ.get('ORG_VOICE_FAKE_TRANSCRIPT'))   # tests only
_model=None;_model_dev=None;_lock=threading.Lock()
def _add_cuda_dlls():
    # pip-installed nvidia-cublas-cu12 / nvidia-cudnn-cu12 put DLLs under site-packages/nvidia/*/bin (Windows)
    try:
        import site
        for sp in site.getsitepackages()+[site.getusersitepackages()]:
            for d in glob.glob(os.path.join(sp,'nvidia','*','bin')):
                os.environ['PATH']=d+os.pathsep+os.environ.get('PATH','')
                if hasattr(os,'add_dll_directory'): os.add_dll_directory(d)
    except Exception: pass
def whisper_installed():
    try: import faster_whisper; return True
    except Exception: return False
def _load(device):
    global _model,_model_dev
    from faster_whisper import WhisperModel
    _add_cuda_dlls()
    if device=='cuda': _model=WhisperModel(CFG['whisper_model'],device='cuda',compute_type='float16')
    else: _model=WhisperModel(CFG['whisper_model'],device='cpu',compute_type='int8')
    _model_dev=device
def _pick_device():
    d=CFG['whisper_device']
    if d in('cuda','cpu'): return d
    try:
        _add_cuda_dlls();import ctranslate2
        return 'cuda' if ctranslate2.get_cuda_device_count()>0 else 'cpu'
    except Exception: return 'cpu'
def _patch_av():
    # PyAV 19+ dropped the metadata_errors option that faster-whisper still passes; drop it if rejected.
    try:
        import av
        if getattr(av.open,'_org_patched',False): return
        _orig=av.open
        def _open(*a,**k):
            try: return _orig(*a,**k)
            except TypeError as e:
                if 'metadata_errors' in str(e):
                    k.pop('metadata_errors',None); return _orig(*a,**k)
                raise
        _open._org_patched=True
        av.open=_open
    except Exception: pass
def transcribe(path):
    if CFG['fake_transcript'] is not None: return CFG['fake_transcript']
    _patch_av()
    with _lock:
        for attempt in (0,1):
            if _model is None: _load(_pick_device() if attempt==0 else 'cpu')
            try:
                segs,_=_model.transcribe(path,language=CFG['whisper_lang'] or None,vad_filter=True,beam_size=5)
                return ' '.join(s.text.strip() for s in segs).strip()
            except Exception as e:
                if attempt==0 and _model_dev=='cuda' and re.search('cublas|cudnn|cuda|CUDA',str(e)):
                    globals()['_model']=None;continue   # GPU libs unusable: fall back to CPU once
                raise
def transcribe_segments(path):
    """Like transcribe() but returns [(start_seconds, text), ...] for the transcript viewer."""
    if CFG['fake_transcript'] is not None: return [(0.0,CFG['fake_transcript'])]
    _patch_av()
    with _lock:
        for attempt in (0,1):
            if _model is None: _load(_pick_device() if attempt==0 else 'cpu')
            try:
                segs,_=_model.transcribe(path,language=CFG['whisper_lang'] or None,vad_filter=True,beam_size=5)
                return [(float(x.start),x.text.strip()) for x in segs if x.text.strip()]
            except Exception as e:
                if attempt==0 and _model_dev=='cuda' and re.search('cublas|cudnn|cuda|CUDA',str(e)):
                    globals()['_model']=None;continue
                raise
def _http(url,body=None,timeout=240):
    req=urllib.request.Request(url,json.dumps(body).encode() if body is not None else None,{'content-type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r: return json.load(r)
def ollama_status():
    try:
        tags=_http(CFG['ollama_url']+'/api/tags',timeout=3).get('models',[])
        names=[m.get('name','') for m in tags];want=CFG['ollama_model']
        ready=want in names or (':' not in want and any(n.split(':')[0]==want for n in names))
        return {'up':True,'model_ready':ready,'models':names[:20]}
    except Exception as e:
        return {'up':False,'model_ready':False,'error':str(e)[:120]}
SYSTEM=("You help one person sort their saved YouTube videos into their own tag list. They spoke a short note about a video. "
 "Reply with JSON only: {\"tags\":[{\"path\":string,\"confidence\":number}],\"new_tags\":[string],\"note\":string}. "
 "Rules: 'tags' paths must be copied exactly from the VOCABULARY list; choose only tags the speaker named or clearly implied. "
 "'new_tags' lists a tag the speaker clearly asked for that is NOT in the vocabulary, written as 'Parent / Child' if they gave a parent. "
 "'note' is what the speaker said about the video, cleaned up (keep first person, at most two sentences); use \"\" if they only named tags. "
 "If they say trash, junk, or that they don't care about the video, include the tag Trash. Never invent tags that are not in the vocabulary or asked for.")
def extract(title,channel,existing,vocab,transcript):
    vlines='\n'.join(f"- {p}"+(f" — {d}" if d else '') for p,d in vocab)
    user=f"VIDEO: {title or '(unknown)'} | CHANNEL: {channel or ''}\nCURRENT TAGS: {', '.join(existing) or 'none'}\n\nVOCABULARY:\n{vlines}\n\nSPOKEN NOTE: {transcript}"
    r=_http(CFG['ollama_url']+'/api/chat',{'model':CFG['ollama_model'],'stream':False,'format':'json','options':{'temperature':0.1},
       'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':user}]})
    txt=r.get('message',{}).get('content','{}')
    try: return json.loads(txt)
    except Exception:
        m=re.search(r'\{.*\}',txt,re.S);return json.loads(m.group(0)) if m else {}
def process(db,audio_id):
    """Background job: transcribe, extract, store unconfirmed suggestions."""
    c=sqlite3.connect(db);c.row_factory=sqlite3.Row
    def upd(**kw):
        c.execute("update audio_notes set "+','.join(k+'=?' for k in kw)+" where id=?",list(kw.values())+[audio_id]);c.commit()
    try:
        row=c.execute("select * from audio_notes where id=?",(audio_id,)).fetchone();vid=row['video_id']
        if not whisper_installed() and CFG['fake_transcript'] is None:
            upd(status='error',error='Whisper is not installed. Run install_voice.bat.');return
        text=transcribe(row['path']);upd(transcript=text,status='transcribed')
        if not text.strip(): upd(status='done',extracted=json.dumps({'tags':[],'new_tags':[],'note':''}));return
        v=c.execute("select title,channel from videos where video_id=?",(vid,)).fetchone()
        tags=c.execute("select id,name,parent_id,description from tags").fetchall();byid={t['id']:t for t in tags}
        def path(t):
            p=[];x=t;n=0
            while x is not None and n<10: p.insert(0,x['name']);x=byid.get(x['parent_id']);n+=1
            return ' / '.join(p)
        vocab=[(path(t),t['description'] or '') for t in tags if t['name']!='Inbox']
        norm=lambda s:re.sub(r'\s*/\s*',' / ',s.strip()).lower()
        lookup={norm(p):t['id'] for p,t in zip((x[0] for x in vocab),[t for t in tags if t['name']!='Inbox'])}
        existing=[path(byid[r[0]]) for r in c.execute("select tag_id from video_tags where video_id=?",(vid,)) if r[0] in byid]
        try: ex=extract(v['title'] if v else '',v['channel'] if v else '',existing,vocab,text)
        except Exception as e:
            upd(status='done',error='Transcribed, but tag suggestions need Ollama: '+str(e)[:150],extracted=json.dumps({'tags':[],'new_tags':[],'note':text}));return
        out={'tags':[],'new_tags':[str(x) for x in ex.get('new_tags',[]) if str(x).strip()],'note':str(ex.get('note','')).strip()}
        for t in ex.get('tags',[]):
            p=t.get('path') if isinstance(t,dict) else str(t);conf=float(t.get('confidence',0.7)) if isinstance(t,dict) else 0.7
            tid=lookup.get(norm(p or ''))
            if tid is None:
                if p and p.strip() and p.strip() not in out['new_tags']: out['new_tags'].append(p.strip())
                continue
            c.execute("insert or ignore into video_tags(video_id,tag_id,source,confidence,confirmed) values(?,?, 'voice',?,0)",(vid,tid,conf));out['tags'].append({'id':tid,'path':path(byid[tid]),'confidence':conf})
        c.commit();upd(status='done',extracted=json.dumps(out))
    except Exception as e:
        try: upd(status='error',error=str(e)[:300])
        except Exception: pass
    finally: c.close()

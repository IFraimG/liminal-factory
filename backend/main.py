import asyncio,base64,json,os,secrets,socket,sys,time,shutil
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from backend.models.schema import EpisodeInput,Settings,MusicBrief
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.orchestration.workflow import DAG
from backend.integrations.process import contained,run,checksum
from backend.integrations.unity import discover
from backend.integrations.secrets import secret

HOME=Path(os.environ.get('LIMINAL_DATA',str(Path.home()/'Library/Application Support/Liminal Factory')))
TOKEN=os.environ.get('LIMINAL_TOKEN') or secrets.token_urlsafe(32)
HOME.mkdir(parents=True,exist_ok=True)
store=Store(HOME/'factory.sqlite3')

def get_settings():
    row=store.rows('SELECT data FROM settings WHERE id=1')
    s=Settings.model_validate_json(row[0]['data']) if row else Settings(working_directory=str(HOME/'episodes'))
    if not s.working_directory: s.working_directory=str(HOME/'episodes')
    defaults={'ffmpeg':'/opt/homebrew/bin/ffmpeg','ffprobe':'/opt/homebrew/bin/ffprobe','yt-dlp':'/opt/homebrew/bin/yt-dlp','codex':'/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'}
    for name,path in defaults.items():
        if name not in s.tools and Path(path).is_file(): s.tools[name]=path
    unity=discover()
    if unity and not s.tools.get('unity'): s.tools['unity']=str(unity[0])
    return s

engine=Engine(store,Path(get_settings().working_directory),get_settings())

@asynccontextmanager
async def lifespan(app):
    engine.scheduler=asyncio.create_task(engine.serve())
    yield
    await engine.close()
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:1420','http://127.0.0.1:1420','tauri://localhost','http://tauri.localhost'],allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Authorization','Content-Type'])

@app.middleware('http')
async def auth(request:Request,call_next):
    if request.method!='OPTIONS':
        supplied=request.headers.get('authorization','').removeprefix('Bearer ')
        if request.url.path.startswith('/episodes/') and '/file/' in request.url.path:
            supplied=request.query_params.get('token',supplied)
        if not secrets.compare_digest(supplied,TOKEN):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Unauthorized'},401)
        if int(request.headers.get('content-length','0'))>100*1024*1024:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Request too large'},413)
    try: return await call_next(request)
    except (ValueError,KeyError,FileNotFoundError) as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':str(exc)},400)

@app.get('/health')
async def health(): return {'status':'ok','version':'0.1.0'}

@app.get('/settings')
async def settings(): return get_settings().model_dump()

@app.put('/settings')
async def save_settings(s:Settings):
    if engine.running: raise HTTPException(409,'Cancel running tasks before changing settings')
    old=get_settings()
    root=Path(s.working_directory).expanduser().resolve()
    forbidden=[Path('/'),Path.home(),Path('/System'),Path('/Applications'),Path('/Library'),Path('/usr'),Path('/bin'),Path('/etc')]
    if root in forbidden or any(root.is_relative_to(p) for p in forbidden[2:]): raise ValueError('Choose a dedicated project folder')
    if old.working_directory!=str(root) and store.rows('SELECT id FROM episodes LIMIT 1'): raise ValueError('Working directory cannot change while episodes exist. Move the complete data folder with the app closed.')
    root.mkdir(parents=True,exist_ok=True); s.working_directory=str(root)
    store.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(s.model_dump_json(),))
    engine.settings=s; engine.root=root; engine.semaphore=asyncio.Semaphore(s.max_concurrent_agents)
    return s.model_dump()

@app.post('/secrets/{name}')
async def set_secret(name:str,request:Request):
    value=(await request.json()).get('value',''); secret(name,value); return {'saved':True}

@app.post('/diagnostics/{name}')
async def diagnostic(name:str):
    if name not in {'herdr','codex','gemini','ffmpeg','ffprobe','yt-dlp','unity'}: raise ValueError('Unknown executable')
    try:
        path=engine.tool(name)
        if name=='herdr': info=await engine.herdr().check(); return {'ok':True,'message':info['version']}
        if name=='unity':
            if not Path(path).is_file(): raise ValueError('Unity executable not found')
            return {'ok':True,'message':path+' — installed; graphics/license are verified at render time'}
        output=await run([path,'-version' if name in ('ffmpeg','ffprobe') else '--version'],timeout=20)
        return {'ok':True,'message':output[:500]}
    except Exception as exc: return {'ok':False,'message':str(exc)+'\nConfigure the executable path. Herdr: https://herdr.dev/tui/docs/install/'}

@app.get('/episodes')
async def episodes():
    output=[]
    for row in store.rows('SELECT * FROM episodes ORDER BY created DESC'):
        config=json.loads(row['config']); tasks=store.rows('SELECT * FROM tasks WHERE episode=?',(row['id'],))
        for task in tasks: task['data']=json.loads(task['data'])
        statuses=[t['status'] for t in tasks]
        status='Completed' if all(s in ('Completed','Approved') for s in statuses) else next((s for s in ('Failed','Running','Waiting for Approval','Cancelled') if s in statuses),'Pending')
        output.append({'id':row['id'],'config':config,'created':row['created'],'status':status,'progress':sum(s in ('Completed','Approved') for s in statuses)/len(tasks),'tasks':tasks})
    return output

@app.post('/episodes')
async def create(config:EpisodeInput): return {'id':engine.create(config.model_dump())}

@app.get('/episodes/{e}')
async def detail(e:str):
    config=store.config(e); root=engine.directory(e)
    tasks=[store.task(e,n) for n in DAG]
    artifacts=[]
    for t in tasks:
        for file in t['data'].get('artifacts',[]):
            path=contained(root,file)
            if path.is_file(): artifacts.append({'name':file,'size':path.stat().st_size})
    refs=[]
    manifest=root/'references.json'
    names=json.loads(manifest.read_text()) if manifest.exists() else []
    for path in names:
        if contained(root,path).is_file(): refs.append(path)
    return {'id':e,'config':config,'tasks':tasks,'logs':store.rows('SELECT * FROM logs WHERE episode=? ORDER BY id DESC LIMIT 300',(e,)),'artifacts':artifacts,'references':refs,'music':[str(p.relative_to(root)) for p in sorted((root/'music').glob('*'))]}

@app.post('/episodes/{e}/start')
async def start(e:str): await engine.start(e); return {'started':True}

@app.post('/episodes/{e}/tasks/{n}/{action}')
async def task_action(e:str,n:str,action:str,request:Request):
    store.config(e)
    if action=='retry': await engine.retry(e,n)
    elif action=='cancel': await engine.cancel(e,n)
    elif action=='approve': await engine.approve(e,n)
    elif action=='changes': await engine.request_changes(e,n,(await request.json()).get('reason','Please revise the brief'))
    else: raise ValueError('Unknown action')
    return {'ok':True}

@app.post('/episodes/{e}/imports/{kind}')
async def import_file(e:str,kind:str,request:Request):
    store.config(e); root=engine.directory(e); data=await request.json()
    name=Path(data['name']).name; suffix=Path(name).suffix.lower()
    if kind not in {'references','music'}: raise ValueError('Unsupported import kind')
    gate='music_approval' if kind=='music' else 'visual_approval'
    if kind=='references' and any(store.task(e,n)['status']!='Pending' for n in ('visual_reference','unity_preview','visual_approval','visual_render')): raise ValueError('References are locked once visual analysis starts')
    if kind=='music' and store.task(e,gate)['status'] not in ('Pending','Waiting for Approval'): raise ValueError('Request changes before replacing approved music')
    if suffix not in ({'.png','.jpg','.jpeg','.webp'} if kind=='references' else {'.mp3','.wav'}): raise ValueError('Unsupported file type')
    raw=base64.b64decode(data['base64'],validate=True)
    if len(raw)>70*1024*1024: raise ValueError('Maximum imported file size is 70 MB')
    folder=root/kind; folder.mkdir(exist_ok=True); path=folder/(uuid_name()+suffix); path.write_bytes(raw)
    try:
        if kind=='references':
            with Image.open(path) as img:
                if img.width*img.height>40000000: raise ValueError('Image exceeds 40 megapixels')
                img.verify()
            manifest=root/'references.json'; names=json.loads(manifest.read_text()) if manifest.exists() else []; names.append(str(path.relative_to(root))); manifest.write_text(json.dumps(names))
        else:
            from backend.media.ffmpeg import probe
            info=await probe(path,engine.tool('ffprobe'))
            if not any(s['codec_type']=='audio' for s in info['streams']): raise ValueError('File has no audio stream')
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ValueError('Invalid imported media: '+str(exc)) from None
    except BaseException:
        path.unlink(missing_ok=True); raise
    return {'name':str(path.relative_to(root))}

def uuid_name():
    import uuid
    return uuid.uuid4().hex

@app.put('/episodes/{e}/references')
async def references(e:str,request:Request):
    root=engine.directory(e); store.config(e)
    if store.task(e,'visual_reference')['status']!='Pending': raise ValueError('References locked during production')
    manifest=root/'references.json'; old=json.loads(manifest.read_text()) if manifest.exists() else []
    names=(await request.json())['names']
    if len(set(names))!=len(names) or any(n not in old for n in names): raise ValueError('Invalid reference ordering')
    for name in set(old)-set(names): contained(root,name).unlink()
    manifest.write_text(json.dumps(names)); return {'ok':True}

@app.put('/episodes/{e}/prompts')
async def prompts(e:str,brief:MusicBrief):
    root=engine.directory(e)
    if store.task(e,'music_approval')['status']!='Waiting for Approval': raise ValueError('Prompts editable only before approval')
    for name in ('metadata','final_assembly'):
        if (e,name) in engine.running: await engine.cancel(e,name)
        store.update(e,name,'Pending',error='',data={})
    (root/'music_brief.json').write_text(brief.model_dump_json(indent=2))
    t=store.task(e,'music_brief'); store.update(e,'music_brief',data={**t['data'],'result':brief.model_dump(),'artifact_checksums':{'music_brief.json':checksum(root/'music_brief.json')}}); engine.wake.set(); return {'ok':True}

@app.delete('/episodes/{e}/music/{name}')
async def delete_music(e:str,name:str):
    store.config(e)
    if store.task(e,'music_approval')['status'] not in ('Pending','Waiting for Approval'): raise ValueError('Request changes before removing approved music')
    path=contained(engine.directory(e)/'music',name)
    if not path.is_file(): raise ValueError('Music file not found')
    path.unlink(); return {'ok':True}

@app.get('/episodes/{e}/file/{name:path}')
async def file(e:str,name:str):
    store.config(e); path=contained(engine.directory(e),name)
    if not path.is_file(): raise HTTPException(404,'Artifact not found')
    if path.suffix.lower() not in {'.mp4','.wav','.mp3','.png','.jpg','.jpeg','.webp','.json','.log','.cs','.unity'}: raise ValueError('File type not served')
    return FileResponse(path,headers={'Cache-Control':'no-store'})

@app.post('/episodes/{e}/open')
async def open_output(e:str):
    store.config(e); root=engine.directory(e); folder=root/'output' if (root/'output').exists() else root
    await run(['/usr/bin/open',str(folder)]); return {'ok':True}

@app.get('/events')
async def events(request:Request,after:int=0):
    async def stream():
        cursor=after
        while not await request.is_disconnected():
            rows=store.rows('SELECT * FROM logs WHERE id>? ORDER BY id LIMIT 100',(cursor,))
            for row in rows:
                cursor=row['id']; yield 'id: '+str(cursor)+'\ndata: '+json.dumps(row)+'\n\n'
            if not rows: yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream')

def main():
    import uvicorn,fcntl
    lock=(HOME/'.backend.lock').open('a')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This workspace is already open in another Liminal Factory process')
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128)
    print(json.dumps({'url':f'http://127.0.0.1:{sock.getsockname()[1]}'}),flush=True)
    uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False)).run(sockets=[sock])
if __name__=='__main__': main()

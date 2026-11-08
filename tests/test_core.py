import asyncio,json
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.models.schema import EpisodeInput,Metadata,Settings,youtube_url
from backend.integrations.process import contained,checksum
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.orchestration.workflow import DAG
from backend.orchestration.herdr_adapter import HerdrAdapter,MockHerdrAdapter

BASE=dict(name='Test atmosphere',audio_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',channel_url='https://www.youtube.com/@ambient',permission=True)

@pytest.mark.parametrize('url',['http://youtube.com/watch?v=dQw4w9WgXcQ','https://youtube.com.evil.org/watch?v=dQw4w9WgXcQ','https://youtube.com@evil.org/watch?v=dQw4w9WgXcQ','file:///tmp/test','https://youtu.be/../../x','https://youtube.com:444/watch?v=dQw4w9WgXcQ'])
def test_hostile_urls(url):
    with pytest.raises(ValueError): youtube_url(url)

def test_schema_and_hashtags():
    assert EpisodeInput(**BASE).duration_minutes==60
    with pytest.raises(ValidationError): EpisodeInput(**BASE,fps=25)
    good=dict(titles=['one','two','three','four','five'],recommended='one',description='An atmosphere',hashtags='#liminalspace, #ambientmusic')
    assert Metadata(**good).hashtags.startswith('#')
    for invalid in ['#one #two','one, #two','#one,#two','#one, ']:
        with pytest.raises(ValidationError): Metadata(**{**good,'hashtags':invalid})

def test_containment(tmp_path):
    with pytest.raises(ValueError): contained(tmp_path,'../outside')
    (tmp_path/'link').symlink_to('/etc')
    with pytest.raises(ValueError): contained(tmp_path,'link/passwd')

async def until(predicate,timeout=3):
    deadline=asyncio.get_running_loop().time()+timeout
    while not predicate():
        if asyncio.get_running_loop().time()>deadline: raise AssertionError('Timed out')
        await asyncio.sleep(.01)

@pytest.fixture
def setup(tmp_path):
    s=Store(tmp_path/'db.sqlite'); settings=Settings(working_directory=str(tmp_path/'episodes'),max_concurrent_agents=3)
    return s,settings

async def test_parallel_claim_retry_cancel_and_gates(setup):
    store,settings=setup; active=0; peak=0; calls={}
    async def handler(e,n):
        nonlocal active,peak
        calls[n]=calls.get(n,0)+1; active+=1; peak=max(peak,active)
        try: await asyncio.sleep(.08)
        finally: active-=1
        if n=='channel_reference' and calls[n]==1: raise RuntimeError('Quota exhausted')
        return {'artifacts':[]}
    engine=Engine(store,settings.working_directory,settings,handlers={n:handler for n in DAG})
    e=engine.create(EpisodeInput(**BASE).model_dump());store.execute('INSERT INTO cache VALUES(?,?,?)',('started:'+e,'true',0))
    engine.scheduler=asyncio.create_task(engine.serve())
    try:
        await until(lambda:store.task(e,'music_approval')['status']=='Waiting for Approval' and store.task(e,'channel_reference')['status']=='Failed')
        assert peak==3
        assert calls['audio_reference']==1
        assert 'final_assembly' not in calls
        await engine.retry(e,'channel_reference')
        await until(lambda:store.task(e,'channel_reference')['status']=='Completed')
        await engine.cancel(e,'music_approval');assert store.task(e,'music_approval')['status']=='Cancelled'
        await engine.retry(e,'music_approval')
        await until(lambda:store.task(e,'music_approval')['status']=='Waiting for Approval')
        assert 'audio_engineer' not in calls
    finally: await engine.close()

async def test_approval_checksum_and_invalidation(setup):
    store,s=setup; engine=Engine(store,s.working_directory,s)
    e=engine.create(EpisodeInput(**BASE).model_dump());root=engine.directory(e);(root/'music').mkdir();(root/'music/track.wav').write_bytes(b'music');(root/'music_brief.json').write_text('{}')
    store.update(e,'music_approval','Waiting for Approval');await engine.approve(e,'music_approval')
    assert store.task(e,'music_approval')['status']=='Approved'
    engine.verify_approval(e,'music_approval')
    (root/'music/track.wav').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='changed'): engine.verify_approval(e,'music_approval')
    store.update(e,'final_assembly','Completed')
    await engine.request_changes(e,'music_approval','less rhythm')
    assert store.task(e,'music_approval')['status']=='Pending'
    assert store.task(e,'final_assembly')['status']=='Pending'
    assert store.task(e,'metadata')['status']=='Pending'

async def test_restart_never_trusts_pid(setup):
    store,s=setup;engine=Engine(store,s.working_directory,s);e=engine.create(EpisodeInput(**BASE).model_dump())
    store.update(e,'audio_reference','Running',data={'pid':1})
    reloaded=Store(Path(s.working_directory).parent/'db.sqlite')
    other=Engine(reloaded,s.working_directory,s);await other.recover()
    assert reloaded.task(e,'audio_reference')['status']=='Failed'
    assert 'retry' in reloaded.task(e,'audio_reference')['error'].lower()

async def test_herdr_pane_before_agent_and_result(tmp_path):
    class Recording(HerdrAdapter):
        def __init__(self): super().__init__();self.calls=[]
        async def check(self): return {}
        async def cli(self,*args,**kwargs):
            self.calls.append(args)
            if args[:2]==('workspace','create'): return {'result':{'root_pane':{'pane_id':'w7:p3'}}}
            if args[:2]==('agent','prompt'): (tmp_path/'result.json').write_text('{"valid":true}')
            return {}
    adapter=Recording(); identities=[]
    assert await adapter.launch(tmp_path,'test','result.json',identities.append,timeout=.1)=={'valid':True}
    assert adapter.calls[0][:2]==('workspace','create')
    assert adapter.calls[1][adapter.calls[1].index('--pane')+1]=='w7:p3'
    assert identities[0]['pane']=='w7:p3'

async def test_idle_without_artifact_is_not_success(tmp_path):
    class Idle(HerdrAdapter):
        async def cli(self,*args,**kwargs): return {'result':{'state':'idle'}}
    with pytest.raises(TimeoutError): await Idle().wait(tmp_path,{'agent':'test','result':'absent.json'},timeout=.01)

async def test_youtube_public_tabs_and_cache(monkeypatch,tmp_path):
    import backend.integrations.youtube as yt
    calls=[]
    async def extract(args,**kwargs):
        calls.append((args,kwargs))
        return json.dumps({'entries':[{'entries':[{'id':'v1','title':'first?token=literal'}]},
            {'entries':[{'id':'v2','title':'second'},{'id':'v1','title':'duplicate'},
            {'id':'v3','title':'Private video'}]}]})
    monkeypatch.setattr(yt,'run',extract)
    store=Store(tmp_path/'db')
    result=await yt.channel_titles(BASE['channel_url'],'yt-dlp',store,chrome_cookies=True,chrome_profile='Profile 1')
    assert result==['first?token=literal','second']
    args,kw=calls[0]
    assert args[args.index('--cookies-from-browser')+1]=='chrome:Profile 1'
    assert '--flat-playlist' in args and '--dump-single-json' in args
    assert '--playlist-end' not in args and '--abort-on-error' in args
    assert kw['stdout_only'] is True
    assert await yt.channel_titles(BASE['channel_url'],'yt-dlp',store)==result
    assert len(calls)==1
    await yt.channel_titles(BASE['channel_url'],'yt-dlp',store,cache_hours=0)
    assert len(calls)==2

@pytest.mark.parametrize('payload',[None,{'entries':[None]},{'entries':[]},{'entries':[{'id':'x'}]}])
async def test_youtube_incomplete_not_cached(monkeypatch,tmp_path,payload):
    import backend.integrations.youtube as yt
    async def extract(*args,**kwargs): return json.dumps(payload)
    monkeypatch.setattr(yt,'run',extract)
    store=Store(tmp_path/'db')
    with pytest.raises(RuntimeError): await yt.channel_titles(BASE['channel_url'],'yt-dlp',store)
    assert not store.rows('SELECT * FROM cache')

async def test_youtube_bad_url_before_process(monkeypatch,tmp_path):
    import backend.integrations.youtube as yt
    async def forbidden(*args,**kwargs): raise AssertionError('must validate before cookie access')
    monkeypatch.setattr(yt,'run',forbidden)
    with pytest.raises(ValueError): await yt.channel_titles('https://evil.example/@foo','yt-dlp',Store(tmp_path/'db'),chrome_cookies=True)

async def test_json_stdout_separated_from_redacted_diagnostics(tmp_path):
    import sys
    from backend.integrations.process import run
    from backend.integrations.download import redact_download_output
    log=tmp_path/'stderr.log'
    code='import sys; print(\' {"title":"https://example.com/?exact=title"} \'); print("Cookie: secret",file=sys.stderr)'
    result=await run([sys.executable,'-c',code],stdout_only=True,sanitize=redact_download_output,log=log)
    assert json.loads(result)['title']=='https://example.com/?exact=title'
    assert 'secret' not in log.read_text()
    with pytest.raises(RuntimeError,match='redacted') as error:
        await run([sys.executable,'-c',code+';sys.exit(1)'],stdout_only=True,sanitize=redact_download_output)
    assert 'secret' not in str(error.value)

async def test_subprocess_timeout_terminates():
    from backend.integrations.process import run
    import sys
    with pytest.raises(asyncio.TimeoutError): await run([sys.executable,'-c','import time;time.sleep(30)'],timeout=.1)

async def test_process_identity_is_recorded():
    from backend.integrations.process import run,PROCESS_OBSERVER
    import sys
    records=[];token=PROCESS_OBSERVER.set(records.append)
    try: assert (await run([sys.executable,'-c','print("hello")'])).strip()=='hello'
    finally: PROCESS_OBSERVER.reset(token)
    assert records[0]['active'] is True and records[0]['pid']>0
    assert records[-1]['active'] is False and records[-1]['returncode']==0
    assert records[0]['instance']==records[-1]['instance']

async def test_dependency_artifact_tampering_fails(setup):
    store,s=setup;engine=Engine(store,s.working_directory,s)
    e=engine.create(EpisodeInput(**BASE).model_dump());p=engine.directory(e)/'analysis.json';p.write_text('{}')
    store.update(e,'audio_reference','Completed',data={'artifact_checksums':{'analysis.json':checksum(p)}})
    p.write_text('{"edited":true}')
    store.update(e,'music_brief','Running');await engine.execute(e,'music_brief')
    assert store.task(e,'music_brief')['status']=='Failed'
    assert 'changed' in store.task(e,'music_brief')['error']

async def test_production_preflight_needs_no_youtube_key(monkeypatch,setup):
    import backend.integrations.secrets as secrets
    store,settings=setup
    settings.vision_enabled=True
    class Ready:
        async def check(self): return True
    engine=Engine(store,settings.working_directory,settings,adapter=Ready())
    episode=engine.create(EpisodeInput(**BASE).model_dump())
    refs=engine.directory(episode)/'references';refs.mkdir();(refs/'ref.png').write_bytes(b'reference')
    monkeypatch.setattr(engine,'tool',lambda name:'/test/'+name)
    def forbidden(*args): raise AssertionError('production must not request an API key')
    monkeypatch.setattr(secrets,'secret',forbidden)
    await engine.start(episode)
    assert engine.enabled(episode)
    assert DAG['audio_reference']==[] and DAG['channel_reference']==[]

@pytest.mark.parametrize('tamper',[False,True])
async def test_unity_retry_resumes_verified_preview_or_rebuilds_changed_files(setup,monkeypatch,tamper):
    import backend.orchestration.engine as module
    from backend.models.schema import SceneSpec
    store,settings=setup;engine=Engine(store,settings.working_directory,settings)
    eid=engine.create(EpisodeInput(**BASE).model_dump());root=engine.directory(eid)
    (root/'visual_reference.json').write_text('{"scene":"corridor"}')
    (root/'references').mkdir();(root/'references/ref.png').write_bytes(b'reference')
    (root/'references.json').write_text('["references/ref.png"]')
    calls={'design':0,'render':0,'qa':0}
    class Renderer:
        def __init__(self,*args): pass
        async def render(self,root,*args):
            calls['render']+=1;(root/'preview.mp4').write_bytes(b'preview')
            frames=root/'preview-frames';frames.mkdir(exist_ok=True)
            (frames/'frame-00000.png').write_bytes(b'frame');(frames/'complete.json').write_text('{}')
            return {'artifacts':['preview.mp4']}
    async def ask(e,n,prompt,schema):
        if schema is SceneSpec:
            calls['design']+=1
            return {'result':SceneSpec(explanation='Original procedural corridor scene').model_dump()}
        calls['qa']+=1
        if calls['qa']==1: raise RuntimeError('simulated QA interruption')
        (root/'unity_preview.json').write_text('{"qa":"inspected"}')
        return {'artifacts':['unity_preview.json'],'result':{'qa':'inspected'}}
    monkeypatch.setattr(module,'Unity',Renderer);monkeypatch.setattr(engine,'ask',ask);monkeypatch.setattr(engine,'tool',lambda n:n)
    with pytest.raises(RuntimeError,match='QA interruption'): await engine.dispatch(eid,'unity_preview')
    assert store.task(eid,'unity_preview')['data']['preview_checkpoint']
    if tamper: (root/'preview-frames/frame-00000.png').write_bytes(b'changed')
    store.update(eid,'visual_reference','Completed');store.update(eid,'unity_preview','Failed')
    await engine.retry(eid,'unity_preview')
    assert 'identity' not in store.task(eid,'unity_preview')['data']
    result=await engine.dispatch(eid,'unity_preview')
    assert result['qa']=={'qa':'inspected'}
    assert calls['render']==(2 if tamper else 1) and calls['design']==calls['render']
    assert calls['qa']==2

async def test_engine_outer_budget_also_excludes_permission_pauses(setup):
    store,settings=setup;engine=Engine(store,settings.working_directory,settings)
    eid=engine.create(EpisodeInput(**BASE).model_dump())
    async def paused(e,n):
        store.update(e,n,'Waiting for Permission');await asyncio.sleep(.06)
        store.update(e,n,'Running');return {'ready':True}
    engine.handlers={'visual_reference':paused}
    assert await engine.dispatch_with_budget(eid,'visual_reference',budget=.02)=={'ready':True}
    interrupted=asyncio.Event()
    async def hangs(e,n):
        store.update(e,n,'Running')
        try: await asyncio.sleep(10)
        finally: interrupted.set()
    engine.handlers={'visual_reference':hangs}
    with pytest.raises(TimeoutError,match='active-work'): await engine.dispatch_with_budget(eid,'visual_reference',budget=.02)
    assert interrupted.is_set()

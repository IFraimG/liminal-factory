import json
from pathlib import Path
import pytest
from backend.integrations.quota import remaining_percent,QuotaRouter
from backend.integrations.kimi import KimiSession
from backend.integrations.antigravity import ClientSessionError
from backend.models.schema import SceneDesign,RecordingPlan
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.models.schema import Settings

@pytest.mark.parametrize('used,selected',[(94,'codex'),(95,'codex'),(95.01,'kimi'),(100,'kimi'),(None,'codex')])
@pytest.mark.asyncio
async def test_quota_boundary_and_unknown(monkeypatch,used,selected):
    async def read(_):return None if used is None else 100-used
    monkeypatch.setattr('backend.integrations.quota.codex_limits',read)
    import time
    router=QuotaRouter(lambda p:{'remaining_percent':80,'expires_at':time.time()+100} if p=='kimi' else None)
    assert await router.choose(['codex','kimi'],'codex')==selected

def test_quota_windows_not_context_and_expired():
    assert remaining_percent({'primary':{'usedPercent':20},'secondary':{'usedPercent':99}})==1
    assert remaining_percent({'primary':{'usedPercent':99,'resetsAt':1}},now=100) is None
    assert remaining_percent({'tokens_used':100,'context_window':200}) is None
    assert remaining_percent({'primary':{'usedPercent':float('nan')}}) is None

def test_kimi_fingerprint_rejects_attach_wrapper(tmp_path):
    exe=tmp_path/'kimi'
    session=KimiSession(executable=exe,expected_cwd=tmp_path)
    terminal={'address':'t11','state':'live','argv':[str(exe),'--model','kimi-code/k3.1-pro'],'pid':13,'foreground':{'pid':13,'argv':['kimi-code']},'created_ms':123,'cwd':str(tmp_path),'labels':{'liminal_factory':'kimi-session'}}
    assert session.fingerprint(terminal)['pid']==13
    assert session.launcher_origin(terminal)
    terminal['foreground']={'pid':14,'argv':['hc','attach','t11']}
    with pytest.raises(ClientSessionError):session.fingerprint(terminal)

@pytest.mark.asyncio
async def test_recording_duration_preserves_approval_and_resets_outputs(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings())
    eid=engine.create({'name':'test','duration_minutes':60})
    store.update(eid,'visual_approval','Approved',data={'checksums':{'scene':'hash'}})
    await engine.set_recording_duration(eid,.5)
    assert store.config(eid)['recording_minutes']==.5
    assert store.config(eid)['duration_minutes']==.5
    assert store.task(eid,'visual_approval')['status']=='Approved'
    assert store.task(eid,'recording_setup')['status']=='Pending'
    for invalid in (None,0,-1,181,float('nan'),True):
        with pytest.raises(ValueError):await engine.set_recording_duration(eid,invalid)

@pytest.mark.asyncio
async def test_recording_plan_cannot_change_user_duration(tmp_path,monkeypatch):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings())
    eid=engine.create({'name':'test','recording_minutes':2,'fps':24,'resolution':'1080p'})
    async def ask(*args):return {'result':{'duration_minutes':3,'fps':24,'resolution':'1080p','camera':'approved_scene_camera'}}
    monkeypatch.setattr(engine,'ask',ask)
    with pytest.raises(ValueError,match='changed user duration'):await engine.dispatch(eid,'recording_setup')

@pytest.mark.asyncio
async def test_request_changes_invalidates_recording_and_keeps_music(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings())
    eid=engine.create({'name':'test'})
    for name in ('unity_preview','visual_approval','recording_setup','visual_render','final_assembly','music_approval'):
        store.update(eid,name,'Completed',data={'preview_checkpoint':{'old':True}})
    await engine.request_changes(eid,'visual_approval','Build enclosed carriage with opaque walls')
    for name in ('unity_preview','visual_approval','recording_setup','visual_render','final_assembly'):assert store.task(eid,name)['status']=='Pending'
    assert store.task(eid,'music_approval')['status']=='Completed'
    assert 'preview_checkpoint' not in store.task(eid,'unity_preview')['data']

@pytest.mark.asyncio
async def test_full_recording_assembly_never_loops(tmp_path,monkeypatch):
    from backend.media import ffmpeg
    calls=[]
    async def probe(*args):return {'format':{'duration':'2'},'streams':[]}
    async def run(args,**kw):calls.append(args);raise RuntimeError('stop after command inspection')
    monkeypatch.setattr(ffmpeg,'probe',probe);monkeypatch.setattr(ffmpeg,'run',run)
    with pytest.raises(RuntimeError,match='command inspection'):
        await ffmpeg.assemble(tmp_path/'a.wav',tmp_path/'v.mp4',tmp_path/'o.mp4',{'recording_minutes':2/60,'duration_minutes':2/60,'resolution':'1080p','fps':24})
    assert '-stream_loop' not in calls[0]

@pytest.mark.asyncio
@pytest.mark.parametrize('verified_stop',[True,False])
async def test_active_handoff_never_starts_competing_prompt(tmp_path,monkeypatch,verified_stop):
    import asyncio
    from backend.orchestration import engine as module
    from backend.orchestration.herdr_adapter import HerdrAdapter
    from backend.models.schema import MusicBrief
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings(agent_kind='codex'))
    eid=engine.create({'name':'test'});engine.quota_poll_interval=.01
    active={'primary':False,'kimi':False,'stopped':False}
    class Primary(HerdrAdapter):
        async def launch(self,root,prompt,result,save):
            save({'agent':'owned','pane':'owned','result':result});active['primary']=True
            try:await asyncio.Event().wait()
            finally:active['primary']=False
        async def cancel(self,identity):active['stopped']=verified_stop;return verified_stop
        async def logs(self,identity):return ''
    class Kimi:
        def __init__(self,session):self.session=session
        async def launch(self,root,prompt,result,save):
            assert not active['primary'] and active['stopped'];active['kimi']=True
            save({'agent':'kimi','pane':'t11','result':result})
            return {'brief':'Original ambient composition','prompts':['one','two']}
        async def cancel(self,identity):pass
        async def logs(self,identity):return ''
    selection=iter(['codex','kimi'])
    async def choose(*args):return next(selection)
    async def read(*args):return 4.9
    monkeypatch.setattr(engine,'herdr',lambda task,provider=None:Primary() if provider=='codex' else Kimi(object()));monkeypatch.setattr(engine,'kimi_session',lambda:object())
    monkeypatch.setattr(engine.quota,'choose',choose);monkeypatch.setattr(engine.quota,'read',read)
    monkeypatch.setattr(module,'AntigravityAdapter',Kimi)
    if verified_stop:
        result=await engine.ask(eid,'music_brief','compose',MusicBrief)
        assert result['result']['brief']=='Original ambient composition' and active['kimi']
    else:
        with pytest.raises(RuntimeError,match='Cannot verify active CLI stopped'):await engine.ask(eid,'music_brief','compose',MusicBrief)
        assert not active['kimi']
    assert not active['primary']

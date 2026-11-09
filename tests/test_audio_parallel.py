import asyncio,json
import pytest
from backend.models.schema import Settings,PresentationInput
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.audio.settings import extension_settings
from backend.orchestration.workflow import EXTENDED_DAG

@pytest.mark.asyncio
async def test_audio_starts_after_music_approval_while_unity_is_running(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings(max_concurrent_agents=3));e=engine.create({'name':'parallel','postproduction_enabled':True,'duration_minutes':60,'presentation_minutes':None,'recording_minutes':3,'audio_mode':'Seamless Loop'})
    for name in ('audio_reference','music_brief','visual_reference'):store.update(e,name,'Completed')
    store.update(e,'music_approval','Approved');store.update(e,'channel_reference','Cancelled')
    started=set();both=asyncio.Event();finish=asyncio.Event()
    async def work(e,n):
        started.add(n)
        if {'audio_engineer','unity_preview'}<=started:both.set()
        await finish.wait();return {}
    engine.handlers={name:work for name in EXTENDED_DAG}
    store.execute('INSERT INTO cache VALUES(?,?,?)',('started:'+e,'true',0));engine.scheduler=asyncio.create_task(engine.serve())
    try:
        async with asyncio.timeout(3):await both.wait()
        assert store.task(e,'audio_engineer')['status']=='Running'
        assert store.task(e,'visual_choice')['status']=='Pending'
        assert store.config(e)['presentation_minutes'] is None
        assert extension_settings(store.config(e))==(60,'Variational Extend')
    finally:await engine.close()

@pytest.mark.asyncio
async def test_first_visual_choice_keeps_audio_running_at_same_duration(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings());e=engine.create({'name':'test','postproduction_enabled':True,'duration_minutes':60,'recording_minutes':3,'audio_mode':'Seamless Loop'});root=engine.directory(e);(root/'visual-recording.mp4').write_bytes(b'clip');store.update(e,'visual_render','Completed')
    store.update(e,'audio_engineer','Running',data={'process':'do not restart'});task=asyncio.create_task(asyncio.Event().wait());engine.running[e,'audio_engineer']=task;before=store.task(e,'audio_engineer')
    try:
        await engine.presentation.choose(e,PresentationInput(minutes=60))
        assert store.task(e,'audio_engineer')==before and engine.running[e,'audio_engineer'] is task and not task.done()
        with pytest.raises(ValueError,match='Stop the affected'):await engine.presentation.choose(e,PresentationInput(minutes=30))
        assert store.config(e)['duration_minutes']==60
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_audio_dispatch_uses_release_target_and_preserves_legacy_mode(tmp_path,monkeypatch):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings());e=engine.create({'name':'test','postproduction_enabled':True,'duration_minutes':42,'recording_minutes':3,'audio_mode':'Seamless Loop'});seen=[]
    monkeypatch.setattr(engine,'verify_approval',lambda *args:{'music':['music/source.wav']});monkeypatch.setattr(engine,'tool',lambda name:name)
    async def process(*args,**kwargs):seen.append((args[2],args[3]))
    monkeypatch.setattr('backend.orchestration.engine.process_audio',process)
    await engine.dispatch(e,'audio_engineer');assert seen==[(42*60,'Variational Extend')]
    assert extension_settings({'duration_minutes':7,'audio_mode':'Multi-track'})==(7,'Multi-track')

@pytest.mark.asyncio
async def test_recording_duration_can_be_saved_without_stopping_independent_audio(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings());e=engine.create({'name':'test','postproduction_enabled':True,'duration_minutes':60,'audio_mode':'Variational Extend'})
    store.update(e,'music_approval','Approved',data={'keep':'music approval'});store.update(e,'visual_approval','Approved',data={'keep':'visual approval'});store.update(e,'audio_engineer','Running',data={'process':'keep rendering audio'})
    before=store.task(e,'audio_engineer');audio=asyncio.create_task(asyncio.Event().wait());engine.running[e,'audio_engineer']=audio
    try:
        await engine.set_recording_duration(e,3)
        assert store.config(e)['recording_minutes']==3 and store.config(e)['duration_minutes']==60
        assert store.task(e,'audio_engineer')==before and not audio.done()
        assert store.task(e,'music_approval')['data']=={'keep':'music approval'}
        assert store.task(e,'visual_approval')['data']=={'keep':'visual approval'}
        assert store.task(e,'recording_setup')['status']=='Pending'
    finally:audio.cancel();await asyncio.gather(audio,return_exceptions=True)

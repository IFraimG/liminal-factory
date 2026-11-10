import asyncio,json
from pathlib import Path
import pytest
from backend.integrations.unity import Unity
from backend.integrations.process import ProcessFailure,checksum
from backend.integrations.quota import QuotaRouter,eligible
from backend.orchestration.priorities import default_order,order_for

@pytest.mark.parametrize('provider',['codex','antigravity','kimi'])
@pytest.mark.parametrize('task',['recording_setup','music_brief','visual_render'])
def test_default_argon_before_kimi_and_explicit_order_preserved(provider,task):
    default=default_order(provider,task)
    assert default.index('antigravity')<default.index('kimi')
    manual=['kimi','codex','antigravity']
    assert order_for({'agent_priorities':{task:manual}},provider,task)==manual

def test_unknown_balances_are_allowed_without_fabricating_percent():
    assert eligible('antigravity',None)
    assert eligible('kimi',None)
    assert eligible('codex',None)
    assert not eligible('antigravity',4.99)
    assert eligible('antigravity',5)

@pytest.mark.asyncio
async def test_argon_unknown_prevents_fallthrough_to_kimi(monkeypatch):
    router=QuotaRouter()
    async def read(provider,_):return None if provider=='antigravity' else 99
    monkeypatch.setattr(router,'read',read)
    assert await router.choose(['antigravity','kimi'])=='antigravity'
    assert await router.choose(['kimi','antigravity'])=='kimi'

@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[None,'kill','duration','frames'])
async def test_capture_saved_scene_no_regeneration_and_publish_only_valid_file(tmp_path,monkeypatch,failure):
    import backend.integrations.unity as module
    assets=tmp_path/'unity-project/Assets';(assets/'Editor').mkdir(parents=True)
    (assets/'Liminal.unity').write_text('approved saved scene')
    (assets/'Editor/LiminalScene.cs').write_text('approved builder')
    (tmp_path/'unity-project/ProjectSettings').mkdir();(tmp_path/'unity-project/ProjectSettings/ProjectVersion.txt').write_text('Unity')
    before={p:checksum(p) for p in (assets/'Liminal.unity',assets/'Editor/LiminalScene.cs')}
    target=tmp_path/'visual-recording.mp4';target.write_bytes(b'previous recording')
    calls=[]
    async def run(args,**kw):
        calls.append(args);config=json.loads((tmp_path/'unity-render-config.json').read_text());folder=tmp_path/'recording-frames'
        (folder/'progress.json').write_text('{"frames":24,"state":"recording"}')
        if failure=='kill':raise ProcessFailure('Unity',-9,'Stopped externally')
        Path(config['video_path']).write_bytes(b'new complete recording')
        (folder/'complete.json').write_text(json.dumps({'frames':72,'fps':24,'state':'completed'}))
        return ''
    async def probe(*args):return {'format':{'duration':'4' if failure=='duration' else '3'},'streams':[{'codec_type':'video','codec_name':'h264','width':1920,'height':1080,'avg_frame_rate':'24/1','nb_frames':'71' if failure=='frames' else '72'}]}
    monkeypatch.setattr(module,'run',run);monkeypatch.setattr(module,'probe',probe)
    operation=Unity('/Unity','/bin/ffmpeg').render(tmp_path,{'resolution':'1080p','fps':24,'recording_minutes':None,'duration_minutes':.05,'style':'Liminal Space','loop_seconds':12},False)
    if failure:
        with pytest.raises(RuntimeError,match={'kill':'SIGKILL','duration':'duration mismatch','frames':'frame count mismatch'}[failure]):await operation
        assert target.read_bytes()==b'previous recording'
    else:
        result=await operation;assert target.read_bytes()==b'new complete recording'
        assert 'visual-recording.report.json' in result['artifacts']
    assert '-quit' not in calls[0] and calls[0][calls[0].index('-executeMethod')+1]=='LiminalRecording.Render'
    assert all(checksum(p)==digest for p,digest in before.items())

@pytest.mark.asyncio
async def test_missing_approved_scene_does_not_create_new_project(tmp_path):
    with pytest.raises(RuntimeError,match='Approved Unity scene is missing'):
        await Unity('/Unity').render(tmp_path,{},False)

@pytest.mark.asyncio
@pytest.mark.parametrize("provider",["codex","antigravity","kimi"])
async def test_running_unknown_quota_is_not_interrupted(tmp_path,monkeypatch,provider):
    from backend.orchestration.engine import Engine
    from backend.storage.db import Store
    from backend.models.schema import Settings,MusicBrief
    engine=Engine(Store(tmp_path/'db'),tmp_path/'episodes',Settings(agent_kind='antigravity'));engine.quota_poll_interval=.005
    eid=engine.create({'name':'unknown Argon allowed'})
    started=asyncio.Event();finish=asyncio.Event();cancelled=[]
    class Adapter:
        async def launch(self,root,prompt,result,save):
            save({'agent':'argon','pane':'t13','result':result});started.set();await finish.wait()
            return {'brief':'Original ambient composition','prompts':['one','two']}
        async def cancel(self,identity):cancelled.append(identity);return True
        async def logs(self,identity):return ''
    async def choose(*args):return provider
    async def read(*args):return None
    monkeypatch.setattr(engine.quota,'choose',choose);monkeypatch.setattr(engine.quota,'read',read)
    monkeypatch.setattr(engine,'herdr',lambda *args:Adapter())
    task=asyncio.create_task(engine.ask(eid,'music_brief','compose',MusicBrief))
    try:
        await asyncio.wait_for(started.wait(),1);await asyncio.sleep(.03)
        assert not task.done() and not cancelled
        finish.set();await asyncio.wait_for(task,1)
    finally:
        if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)


def test_local_plan_task_id_is_a_schema_constant():
    from backend.models.schema import step_preparation_schema
    from pydantic import ValidationError
    schema=step_preparation_schema('visual_render')
    assert schema.model_json_schema()['properties']['task']['const']=='visual_render'
    with pytest.raises(ValidationError):schema.model_validate({'task':'Prepare visual_render execution plan','summary':'Prepare the approved scene capture','checks':['Check encoded output']})
    assert schema.model_validate({'task':'visual_render','summary':'Prepare the approved scene capture','checks':['Check encoded output']}).task=='visual_render'

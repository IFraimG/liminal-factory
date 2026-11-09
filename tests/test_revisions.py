import asyncio,json,time
from pathlib import Path
import pytest
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.orchestration.revisions import impact
from backend.orchestration.versions import Versions
from backend.orchestration.workflow import DAG,GATES
from backend.models.schema import Settings,RevisionPlan,RevisionInput,Metadata
from backend.integrations.process import checksum

@pytest.fixture
def completed(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings(agent_kind='antigravity'));eid=engine.create({'name':'Version test','duration_minutes':3,'recording_minutes':3,'resolution':'1080p','fps':24,'audio_mode':'Seamless Loop','agent_priorities':{'unity_preview':['antigravity','codex','kimi']}});root=engine.directory(eid)
    for name in DAG:
        path=root/'task-files'/f'{name}.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps({'original':name}))
        store.update(eid,name,'Approved' if name in GATES else 'Completed',data={'artifacts':[str(path.relative_to(root))],'artifact_checksums':{str(path.relative_to(root)):checksum(path)}})
    (root/'output').mkdir();(root/'output/final.mp4').write_bytes(b'original complete video');(root/'output/metadata.json').write_text('{"title":"original"}')
    arts=['output/final.mp4','output/metadata.json'];store.update(eid,'final_assembly','Completed',data={'artifacts':arts,'artifact_checksums':{p:checksum(root/p) for p in arts}})
    return engine,store,eid,root

def plan(scope,**patch):return RevisionPlan(changes=[{'scope':scope,'instruction':'Change only the requested part'}],config_updates=patch,explanation='Only the named scope must be regenerated',needs_clarification=False,clarification='').model_dump()

def request_row(engine,eid,prompt='Make the fog lighter',scope='auto'):
    identifier='r'+str(time.time_ns());root=engine.directory(eid)
    engine.store.execute('INSERT INTO revisions(id,episode,created,status,prompt,provider,model,effort,scope,data) VALUES(?,?,?,?,?,?,?,?,?,?)',(identifier,eid,time.time(),'Planning',prompt,'codex','gpt-6.1-sol','medium',scope,json.dumps({'base_final_sha256':checksum(root/'output/final.mp4')})))
    return identifier

@pytest.mark.parametrize('scope,expected',[
 ('unity_scene',{'unity_preview','visual_approval','recording_setup','visual_render','final_assembly'}),
 ('metadata',{'metadata','final_assembly'}),
 ('audio_processing',{'audio_engineer','final_assembly'}),
 ('recording',{'recording_setup','visual_render','final_assembly'}),
 ('music_brief',{'music_brief','music_approval','audio_engineer','metadata','final_assembly'})])
def test_minimal_dependency_closure(scope,expected):assert impact(plan(scope))[1]==expected

@pytest.mark.asyncio
@pytest.mark.parametrize('scope',['unity_scene','metadata','audio_processing','recording','music_brief'])
async def test_archive_before_reset_and_preserve_every_independent_task(completed,scope):
    engine,store,eid,root=completed;before={name:store.task(eid,name) for name in DAG};files={str(p.relative_to(root)):p.read_bytes() for p in (root/'task-files').glob('*')};cfg=store.config(eid)
    identifier=request_row(engine,eid);p=plan(scope);affected=impact(p)[1]
    await engine.revisions.apply(identifier,p)
    for name in DAG:
        if name in affected:
            task=store.task(eid,name);assert task['status']=='Pending'
            assert task['data']['revision_agent']=={'provider':'codex','model':'gpt-6.1-sol','effort':'medium'}
        else:assert store.task(eid,name)==before[name]
    assert all((root/path).read_bytes()==content for path,content in files.items())
    assert store.config(eid)==cfg
    versions=Versions(store,engine.root).list(eid);assert len(versions)==1 and versions[0]['status']=='superseded'
    archive=root/versions[0]['video'];assert archive.read_bytes()==b'original complete video'
    (root/'output/final.mp4').write_bytes(b'new complete video');assert archive.read_bytes()==b'original complete video'
    manifest=json.loads((root/versions[0]['manifest_path']).read_text());assert manifest['tasks']['final_assembly']['status']=='Completed'

@pytest.mark.asyncio
async def test_duration_revision_invalidates_audio_without_music_or_visual_gate(completed):
    engine,store,eid,_=completed;before={n:store.task(eid,n) for n in DAG}
    await engine.revisions.apply(request_row(engine,eid),plan('recording',recording_minutes=2))
    assert store.config(eid)['duration_minutes']==2
    assert store.task(eid,'audio_engineer')['status']=='Pending'
    for name in ('music_brief','music_approval','visual_reference','unity_preview','visual_approval','metadata'):assert store.task(eid,name)==before[name]

@pytest.mark.asyncio
async def test_out_of_scope_patch_leaves_final_current(completed):
    engine,store,eid,_=completed;before=store.task(eid,'final_assembly')
    with pytest.raises(ValueError):await engine.revisions.apply(request_row(engine,eid),plan('unity_scene',audio_gain_db=-6))
    assert store.task(eid,'final_assembly')==before and not Versions(store,engine.root).list(eid)

@pytest.mark.asyncio
async def test_changed_final_and_snapshot_failure_do_not_invalidate(completed,monkeypatch):
    engine,store,eid,root=completed;identifier=request_row(engine,eid)
    def fail(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr('backend.orchestration.versions.shutil.copy2',fail)
    with pytest.raises(OSError):await engine.revisions.apply(identifier,plan('metadata'))
    assert store.task(eid,'final_assembly')['status']=='Completed'
    assert not Versions(store,engine.root).list(eid)
    (root/'output/final.mp4').write_bytes(b'edited externally')
    with pytest.raises(ValueError,match='changed'):await engine.revisions.apply(identifier,plan('metadata'))

@pytest.mark.asyncio
async def test_revision_default_exact_model_and_ambiguous_plan_does_not_apply(completed,monkeypatch):
    engine,store,eid,_=completed;seen={}
    class Adapter:
        async def launch(self,root,prompt,result,save):
            save({'agent':'test','pane':'test'});return RevisionPlan(changes=[],config_updates={},explanation='Need a more concrete requested change',needs_clarification=True,clarification='What should change in the scene?').model_dump()
        async def cancel(self,identity):pass
    def herdr(task,provider,**kwargs):seen.update(provider=provider,**kwargs);return Adapter()
    async def choose(*args):return 'codex'
    monkeypatch.setattr(engine,'herdr',herdr);monkeypatch.setattr(engine.quota,'choose',choose)
    identifier=engine.revisions.create(eid,RevisionInput(prompt='Make it different'))
    await engine.revisions.jobs[identifier]
    assert seen=={'provider':'codex','model':'gpt-6.1-sol','effort':'medium'}
    assert engine.revisions.get(identifier)['status']=='Needs clarification'
    assert store.task(eid,'final_assembly')['status']=='Completed' and not Versions(store,engine.root).list(eid)

@pytest.mark.asyncio
async def test_metadata_description_revision_keeps_original_titles(completed):
    engine,store,eid,root=completed
    old={'titles':['one','two','three','four','five'],'recommended':'one','description':'Original description','hashtags':'#original'}
    new={'titles':['a','b','c','d','e'],'recommended':'a','description':'Corrected description','hashtags':'#changed'}
    (root/'metadata.json').write_text(json.dumps(old));store.update(eid,'metadata',data={'revision_fields':['description']})
    class Adapter:
        async def launch(self,root,prompt,result,save):return new
        async def cancel(self,identity):pass
    engine.adapter=Adapter()
    result=await engine.ask(eid,'metadata','Edit description only',Metadata)
    assert result['result']=={**old,'description':'Corrected description'}


def test_stale_old_source_hash_is_reported_not_rewritten(completed):
    engine,store,eid,root=completed
    task=store.task(eid,'unity_preview');path=task['data']['artifacts'][0];expected=task['data']['artifact_checksums'][path];(root/path).write_text('Updated by old renderer')
    version=Versions(store,engine.root).archive(eid,{'unity_preview','final_assembly'})
    assert version['manifest']['integrity_warnings']
    assert version['manifest']['tasks']['unity_preview']['data']['artifact_checksums'][path]==expected
    assert version['manifest']['files'][path]['sha256']==checksum(root/path)

@pytest.mark.asyncio
async def test_revision_runs_only_affected_steps_and_delivers_new_current_final(completed):
    engine,store,eid,root=completed;before={n:store.task(eid,n) for n in DAG};executed=[]
    async def metadata(e,n):
        executed.append(n);path=root/'task-files/metadata.json';path.write_text('{"revised":true}');return {'artifacts':['task-files/metadata.json']}
    async def final(e,n):
        executed.append(n);(root/'output/final.mp4').write_bytes(b'new delivered video');return {'artifacts':['output/final.mp4','output/metadata.json']}
    engine.handlers={'metadata':metadata,'final_assembly':final}
    identifier=request_row(engine,eid);await engine.revisions.apply(identifier,plan('metadata'))
    engine.scheduler=asyncio.create_task(engine.serve())
    try:
        async with asyncio.timeout(5):
            while store.task(eid,'final_assembly')['status']!='Completed':await asyncio.sleep(.01)
        assert executed==['metadata','final_assembly']
        assert engine.revisions.get(identifier)['status']=='Completed'
        for name in set(DAG)-{'metadata','final_assembly'}:assert store.task(eid,name)==before[name]
        versions=Versions(store,engine.root).list(eid)
        assert (root/versions[0]['video']).read_bytes()==b'original complete video'
        assert (root/'output/final.mp4').read_bytes()==b'new delivered video'
        # A second change preserves the second final too, rather than overwriting history.
        await engine.revisions.apply(request_row(engine,eid,'Shorter description'),plan('metadata'))
        versions=Versions(store,engine.root).list(eid);assert len(versions)==2
        assert {(root/v['video']).read_bytes() for v in versions}=={b'original complete video',b'new delivered video'}
    finally:await engine.close()

@pytest.mark.asyncio
async def test_new_gate_feedback_is_not_constrained_by_an_older_narrow_edit(completed):
    engine,store,eid,root=completed
    old=store.task(eid,'unity_preview')['data'];old.update(revision_agent={'provider':'codex','model':'gpt-6.1-sol','effort':'medium'},revision_fields=['fog_density'])
    store.update(eid,'unity_preview',data=old)
    await engine.request_changes(eid,'visual_approval','Move the camera farther back as well')
    revised=store.task(eid,'unity_preview')['data']
    assert 'revision_fields' not in revised
    assert revised['revision_agent']['model']=='gpt-6.1-sol'
    assert revised['feedback']=='Move the camera farther back as well'

import json
from pathlib import Path
import pytest
from backend.models.schema import EpisodeInput,Metadata,RevisionInput,RevisionPlan,Settings
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.agents.context import episode_context

BASE={'name':'Direction test','audio_url':'https://youtu.be/dQw4w9WgXcQ','channel_url':'https://youtube.com/@ambient'}

def test_defaults_validation_and_durable_direction(tmp_path):
    config=EpisodeInput(**BASE,agent_guidance='  Keep warm lighting and original music mood.  ').model_dump()
    assert config['image_resolution']=='1920x1080' and config['resolution']=='1080p'
    assert config['agent_guidance']=='Keep warm lighting and original music mood.'
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings());e=engine.create(config)
    reloaded=Store(tmp_path/'db');assert reloaded.config(e)==config
    for patch in ({'image_resolution':'123x456'},{'agent_guidance':'x'*8001}):
        with pytest.raises(ValueError):EpisodeInput(**BASE,**patch)

@pytest.mark.asyncio
async def test_every_ask_keeps_baseline_and_later_feedback_across_retry(tmp_path):
    config=EpisodeInput(**BASE,agent_guidance='Warm light; keep the scene empty.').model_dump();store=Store(tmp_path/'db');seen=[]
    class Adapter:
        async def launch(self,root,prompt,result,save):
            seen.append(prompt);return {'titles':['one','two','three','four','five'],'recommended':'one','description':'updated','hashtags':'#ambient'}
        async def cancel(self,identity):return True
    engine=Engine(store,tmp_path/'episodes',Settings(),adapter=Adapter());e=engine.create(config)
    store.update(e,'metadata','Failed',data={'feedback':'Use cool lighting in this revision only.'})
    for dependency in engine.workflow(e)['metadata']:store.update(e,dependency,'Completed')
    await engine.retry(e,'metadata');await engine.ask(e,'metadata','Update this step.',Metadata)
    text=seen[0];assert 'Warm light; keep the scene empty.' in text and 'Use cool lighting' in text
    assert 'override conflicting parts' in text and 'within their requested scope' in text
    assert 'video=1920x1080' in text and 'generated image=1920x1080' in text
    assert store.config(e)['agent_guidance']==config['agent_guidance']

@pytest.mark.asyncio
async def test_revision_planner_receives_persistent_episode_direction(tmp_path,monkeypatch):
    config=EpisodeInput(**BASE,agent_guidance='Keep the music quiet and retain brown materials.').model_dump();store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings());e=engine.create(config);root=engine.directory(e);(root/'output').mkdir();(root/'output/final.mp4').write_bytes(b'final');store.update(e,'final_assembly','Completed');seen=[]
    class Adapter:
        async def launch(self,root,prompt,result,save):
            seen.append(prompt);return RevisionPlan(changes=[],config_updates={},explanation='Need a more specific correction',needs_clarification=True,clarification='Which material should change?').model_dump()
        async def cancel(self,identity):return True
    monkeypatch.setattr(engine,'herdr',lambda *args,**kwargs:Adapter())
    async def choose(*args):return 'codex'
    monkeypatch.setattr(engine.quota,'choose',choose)
    revision=engine.revisions.create(e,RevisionInput(prompt='Change one material'))
    await engine.revisions.jobs[revision]
    assert config['agent_guidance'] in seen[0] and 'Change one material' in seen[0]

def test_legacy_episode_context_does_not_require_new_fields():
    text=episode_context({'resolution':'1440p'})
    assert 'video=2560x1440' in text and 'generated image=1920x1080' in text

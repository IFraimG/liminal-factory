import asyncio,json
from pathlib import Path
import pytest
from backend.models.schema import EpisodeInput,Settings,UnityBlueprint,SceneSpec,SceneDesign
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.orchestration.workflow import workflow
from backend.orchestration.priorities import AI_TASKS
from backend.integrations.process import checksum


def blueprint(category='custom_scene'):
    return {'scene_type':category,'reference_observations':'Observed architecture, framing and actual reference details. '*5,'geometry_and_layout':'Arrange the primary structures, foreground props and distant background in measured layers. '*4,'materials_and_surface_detail':'Rough weathered surfaces with visible scale-appropriate variation, joints and contact detail. '*3,'lighting_and_color':'Match the source light direction, color temperature, lit/unlit distribution and shadow contrast. '*3,'camera_and_composition':'Match the observed elevated or eye-level viewpoint, horizon, framing and perspective. '*3,'atmosphere_and_motion':'Match only observed weather, depth haze and restrained movement. '*3,'implementation_prompt':'Inspect the source reference and reproduce its scene category with detailed supported geometry, layered composition, weathered materials, lighting, camera position and atmospheric depth. '*10,'fidelity_checks':['Compare '+x for x in ['scene category','object proportions','camera framing','material detail','light placement','atmosphere']],'limitations':['Procedural primitives approximate source shapes; no exact photographic reconstruction.']}

@pytest.fixture
def setup(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings(vision_enabled=True));e=engine.create({'name':'scene','style':'Coldcore','channel_url':'https://youtube.com/@ambient'});root=engine.directory(e)
    (root/'references').mkdir();(root/'references/source.png').write_bytes(b'pixels');(root/'references.json').write_text('["references/source.png"]');(root/'visual_reference.json').write_text('{}');store.update(e,'visual_reference','Completed',data={'artifacts':['visual_reference.json'],'artifact_checksums':{'visual_reference.json':checksum(root/'visual_reference.json')}})
    return engine,store,e,root

async def ready_plan(setup,category='custom_scene'):
    engine,store,e,root=setup
    await engine.scene_planning.enable(e)
    plan=blueprint(category)
    (root/'unity_blueprint.json').write_text(json.dumps(plan));(root/'unity_blueprint.md').write_text(plan['implementation_prompt'])
    paths=['unity_blueprint.json','unity_blueprint.md'];store.update(e,'unity_blueprint','Completed',data={'result':plan,'artifacts':paths,'artifact_checksums':{p:checksum(root/p) for p in paths}})
    return plan

def test_blueprint_is_before_unity_and_has_independent_agent_priority():
    graph=workflow({'unity_planning_enabled':True})
    assert graph['unity_blueprint']==['visual_reference'] and graph['unity_preview']==['unity_blueprint']
    assert 'unity_blueprint' in AI_TASKS
    assert 'unity_blueprint' not in workflow({})
    assert EpisodeInput(name='test',audio_url='https://youtube.com/watch?v=dQw4w9WgXcQ',channel_url='https://youtube.com/@ambient').unity_planning_enabled

async def test_detailed_prompt_generation_reads_actual_references_before_any_unity(setup,monkeypatch):
    engine,store,e,root=setup;await engine.scene_planning.enable(e,'Preserve the wide composition')
    async def ask(e,n,prompt,schema):
        assert n=='unity_blueprint' and schema is UnityBlueprint
        assert 'references/source.png' in prompt and 'Before any Unity project creation' in prompt
        assert 'custom_scene' in prompt and 'not hard-code a snowy courtyard' in prompt
        checked=schema.model_validate(blueprint()).model_dump();(root/'unity_blueprint.json').write_text(json.dumps(checked));return {'result':checked,'artifacts':['unity_blueprint.json']}
    monkeypatch.setattr(engine,'ask',ask)
    result=await engine.dispatch(e,'unity_blueprint')
    assert 'unity_blueprint.md' in result['artifacts'] and 'Fidelity checks' in (root/'unity_blueprint.md').read_text()
    assert not (root/'unity-project').exists()

async def test_enabling_plan_preserves_audio_metadata_and_clears_only_visual_consumers(setup):
    engine,store,e,root=setup
    for name in ('audio_reference','music_brief','music_approval','audio_engineer','channel_reference','metadata'):
        store.update(e,name,'Completed',data={'kept':name})
    before={n:store.task(e,n) for n in ('audio_engineer','metadata','music_brief')}
    await engine.scene_planning.enable(e,'Match source geometry')
    for n,t in before.items():assert store.task(e,n)==t
    assert store.task(e,'unity_preview')['status']=='Pending'
    assert store.task(e,'unity_blueprint')['data']['feedback']=='Match source geometry'

async def test_active_visual_task_blocks_regeneration_but_audio_does_not(setup):
    engine,store,e,root=setup
    running=asyncio.create_task(asyncio.sleep(20));engine.running[(e,'unity_preview')]=running
    try:
        with pytest.raises(ValueError,match='Stop the active'):await engine.scene_planning.enable(e)
        engine.running.pop((e,'unity_preview'));engine.running[(e,'audio_engineer')]=running
        await engine.scene_planning.enable(e)
    finally:running.cancel();await asyncio.gather(running,return_exceptions=True);engine.running.clear()

@pytest.mark.parametrize('category',['unsupported','custom_scene'])
async def test_unsupported_or_mismatched_design_never_starts_unity(setup,monkeypatch,category):
    import backend.orchestration.engine as module
    engine,store,e,root=setup;await ready_plan(setup,category)
    def forbidden(*args):raise AssertionError('Unity must not start')
    monkeypatch.setattr(module,'Unity',forbidden)
    async def ask(*args,**kw):return {'result':SceneSpec(scene_type='enclosed_corridor',explanation='An unrelated corridor design').model_dump()}
    monkeypatch.setattr(engine,'ask',ask)
    with pytest.raises(ValueError,match='unsupported geometry|changed the reference category'):await engine.dispatch(e,'unity_preview')


def custom_scene():
    return dict(scene_type='custom_scene',explanation='Reference-first generic scene geometry',custom_materials=[{'name':'stone','color':[.3,.3,.3],'texture':'concrete'}],custom_objects=[{'name':'Main structure','primitive':'box','position':[0,1,5],'scale':[10,2,2],'material':'stone','repeat':[2,1,1],'step':[12,0,0]}])

@pytest.mark.parametrize('bad',['missing_geometry','unknown_material','too_many','nan','repeat_bounds'])
def test_custom_scene_rejects_invalid_or_unbounded_geometry(bad):
    data=custom_scene()
    if bad=='missing_geometry':data['custom_objects']=[]
    if bad=='unknown_material':data['custom_objects'][0]['material']='undefined'
    if bad=='too_many':data['custom_objects'][0]['repeat']=[100,100,100]
    if bad=='nan':data['custom_objects'][0]['position'][0]=float('nan')
    if bad=='repeat_bounds':data['custom_objects'][0]['repeat']=[100,1,1]
    with pytest.raises(ValueError):SceneSpec(**data)

def test_generic_scene_supports_different_reference_categories_without_presets():
    for name in ('Courtyard facade','Forest trunks','Warehouse beams','Coastal rock'):
        data=custom_scene();data['custom_objects'][0]['name']=name
        spec=SceneSpec(**data);assert spec.scene_type=='custom_scene' and spec.custom_objects[0].name==name

async def test_visual_request_changes_regenerates_blueprint_without_touching_audio(setup):
    engine,store,e,root=setup;await ready_plan(setup)
    store.update(e,'visual_approval','Waiting for Approval');store.update(e,'audio_engineer','Running',data={'keep':'audio'})
    audio=store.task(e,'audio_engineer')
    await engine.request_changes(e,'visual_approval','Preserve the reference framing')
    assert store.task(e,'unity_blueprint')['status']=='Pending'
    assert store.task(e,'unity_blueprint')['data']['feedback']=='Preserve the reference framing'
    assert store.task(e,'audio_engineer')==audio

async def test_blueprint_archives_previous_final_and_preserves_it(setup):
    from backend.orchestration.versions import Versions
    engine,store,e,root=setup;(root/'output').mkdir();(root/'output/final.mp4').write_bytes(b'previous final')
    store.update(e,'final_assembly','Completed',data={'artifacts':['output/final.mp4'],'artifact_checksums':{'output/final.mp4':checksum(root/'output/final.mp4')}})
    await engine.scene_planning.enable(e,'Improve reference matching')
    archived=Versions(store,engine.root).list(e);assert len(archived)==1
    assert (root/archived[0]['video']).read_bytes()==b'previous final'
    assert store.task(e,'final_assembly')['status']=='Pending'

async def test_matching_design_consumes_blueprint_before_render_and_blocks_wrong_category_qa(setup,monkeypatch):
    import backend.orchestration.engine as module
    from backend.models.schema import UnityFidelityReport
    engine,store,e,root=setup;await ready_plan(setup);calls=[]
    class Renderer:
        def __init__(self,*args):pass
        async def render(self,root,*args):
            calls.append('render');(root/'preview.mp4').write_bytes(b'preview');(root/'preview-frames').mkdir(exist_ok=True)
            for n in ('frame-00000.png','complete.json'):(root/'preview-frames'/n).write_bytes(b'preview')
            return {'artifacts':['preview.mp4']}
    async def ask(e,n,prompt,schema):
        if schema is SceneDesign:
            assert 'unity_blueprint.json and unity_blueprint.md in full' in prompt
            calls.append('design');return {'result':SceneSpec(**custom_scene()).model_dump()}
        assert schema is UnityFidelityReport
        assert 'each fidelity check' in prompt;calls.append('qa')
        qa={'reference_category':'Outdoor landscape','rendered_category':'Indoor corridor','category_matches':False,'summary':'The preview changed an outdoor reference into an unrelated indoor scene.','limitations':['Procedural approximation'],'checks':[{'criterion':str(i)+' category','passed':False,'observation':'The actual frame does not match this reference feature.'} for i in range(6)]}
        (root/'unity_preview.json').write_text(json.dumps(qa));return {'artifacts':['unity_preview.json'],'result':qa}
    monkeypatch.setattr(module,'Unity',Renderer);monkeypatch.setattr(engine,'ask',ask);monkeypatch.setattr(engine,'tool',lambda n:n)
    with pytest.raises(ValueError,match='does not match'):await engine.dispatch(e,'unity_preview')
    assert calls==['design','render','qa']
    assert 'unity_blueprint.json' in store.task(e,'unity_preview')['data']['preview_checkpoint']['checksums']

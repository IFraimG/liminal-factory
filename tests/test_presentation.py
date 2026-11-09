import asyncio,json,shutil
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from PIL import Image
from backend.models.schema import Settings,PresentationInput
from backend.orchestration.engine import Engine
from backend.orchestration.workflow import DAG,EXTENDED_DAG
from backend.storage.db import Store
from backend.integrations.process import checksum,run
from backend.media.extend import extend_visual
from backend.media.ffmpeg import probe,assemble
from backend.audio.engineer import process_audio
from backend.orchestration.priorities import order_for

@pytest.fixture
def captured(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings(agent_kind='codex'))
    e=engine.create({'name':'test','duration_minutes':3,'recording_minutes':3,'resolution':'1080p','fps':24,'audio_mode':'Seamless Loop'})
    root=engine.directory(e);(root/'visual-recording.mp4').write_bytes(b'Unity capture')
    for n in DAG:store.update(e,n,'Approved' if n.endswith('_approval') else 'Completed')
    store.update(e,'visual_render',data={'artifacts':['visual-recording.mp4'],'artifact_checksums':{'visual-recording.mp4':checksum(root/'visual-recording.mp4')}})
    # No final file: test a recording that has not been assembled yet.
    return engine,store,e,root

@pytest.mark.asyncio
async def test_choose_hour_keeps_capture_and_independent_branches(captured):
    engine,store,e,root=captured;before={n:store.task(e,n) for n in DAG}
    await engine.presentation.choose(e,PresentationInput())
    config=store.config(e);assert config['duration_minutes']==config['presentation_minutes']==60
    assert config['recording_minutes']==3 and config['audio_mode']=='Variational Extend'
    assert set(engine.workflow(e))==set(EXTENDED_DAG)
    for n in set(DAG)-{'audio_engineer','final_assembly'}:assert store.task(e,n)==before[n]
    assert store.task(e,'image_edit')['status']=='Completed' and store.task(e,'image_approval')['status']=='Approved'
    assert store.task(e,'visual_extend')['status']=='Pending'
    assert order_for(config,'codex','image_edit')[0]=='antigravity'
    assert (root/'visual-recording.mp4').read_bytes()==b'Unity capture'
    # Changing only the visual source at the same length does not restart audio.
    store.update(e,'audio_engineer','Completed',data={'kept':True});audio=store.task(e,'audio_engineer')
    await engine.presentation.choose(e,PresentationInput(minutes=60))
    assert store.task(e,'audio_engineer')==audio

@pytest.mark.asyncio
async def test_image_edit_requires_real_changed_pixels_and_preserves_iterations(captured,monkeypatch):
    engine,store,e,root=captured
    async def probe(*args):return {'format':{'duration':3}}
    async def extract(args,**kwargs):Image.fromarray(np.tile(np.arange(640,dtype=np.uint8),(360,1))).save(args[-1])
    monkeypatch.setattr('backend.orchestration.presentation.probe',probe);monkeypatch.setattr('backend.orchestration.presentation.run',extract)
    engine.settings.tools={'ffmpeg':'ffmpeg','ffprobe':'ffprobe'}
    await engine.presentation.choose(e,PresentationInput(mode='image',minutes=1,prompt='Improve texture detail'))
    assert store.task(e,'image_edit')['status']=='Pending'
    async def ask(e,n,prompt,schema):
        output=next((root/'image-edits').glob('*/edited.png'),None)
        import re
        destination=re.search(r'Save the generated pixels as ([^ ]+)\.',prompt).group(1)
        Image.fromarray(np.tile(np.arange(640,dtype=np.uint8),(360,1))[:,::-1]).save(root/destination)
        return {'result':{'image_path':destination,'description':'Edited generated texture detail'},'artifacts':[]}
    monkeypatch.setattr(engine,'ask',ask)
    result=await engine.presentation.dispatch(e,'image_edit');store.update(e,'image_edit','Completed',data={**store.task(e,'image_edit')['data'],**result,'artifact_checksums':{result['image']:checksum(root/result['image'])}})
    store.update(e,'image_approval','Waiting for Approval');engine.presentation.approve_image(e)
    assert store.task(e,'image_approval')['data']['image']==result['image']
    audio=store.task(e,'audio_engineer');unity=store.task(e,'visual_render')
    await engine.presentation.change_image(e,'Make the background lighter')
    assert store.task(e,'image_edit')['data']['source_image']==result['image']
    assert len(engine.presentation.state(e)['image_history'])==1
    assert store.task(e,'audio_engineer')==audio and store.task(e,'visual_render')==unity
    async def missing(*args):return {'result':{'image_path':'not-generated.png','description':'No real image was produced'},'artifacts':[]}
    monkeypatch.setattr(engine,'ask',missing)
    with pytest.raises(ValueError,match='unexpected image'):await engine.presentation.dispatch(e,'image_edit')

@pytest.mark.asyncio
async def test_audio_and_visual_extension_can_run_concurrently(captured,monkeypatch):
    engine,store,e,root=captured;await engine.presentation.choose(e,PresentationInput())
    started=set();release=asyncio.Event()
    async def handler(e,n):
        started.add(n)
        if len(started)==2:release.set()
        await release.wait();return {}
    engine.handlers={'audio_engineer':handler,'visual_extend':handler}
    for dep in engine.workflow(e)['audio_engineer']:store.update(e,dep,'Approved')
    engine.scheduler=asyncio.create_task(engine.serve())
    try:
        async with asyncio.timeout(3):await release.wait()
        assert started=={'audio_engineer','visual_extend'}
    finally:await engine.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['video','image'])
async def test_real_release_duration_and_final_mux(tmp_path,mode):
    if not shutil.which('ffmpeg'):pytest.skip('ffmpeg unavailable')
    source=tmp_path/('source.png' if mode=='image' else 'source.mp4')
    if mode=='image':Image.fromarray(np.tile(np.arange(640,dtype=np.uint8),(360,1))).save(source)
    else:await run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=24','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
    config={'presentation_minutes':.1,'presentation_mode':mode,'postproduction_enabled':True,'duration_minutes':.1,'recording_minutes':1/60,'resolution':'1080p','fps':24}
    out=tmp_path/'extended-visual.mp4';await extend_visual(source,out,config)
    assert float((await probe(out))['format']['duration'])==pytest.approx(6,abs=.1)
    audio=tmp_path/'audio.wav';sf.write(audio,np.sin(np.arange(48000*6)*2*np.pi*220/48000)*.1,48000)
    final=tmp_path/'final.mp4';await assemble(audio,out,final,config)
    report=await probe(final);assert {s['codec_type'] for s in report['streams']}=={'video','audio'}

@pytest.mark.asyncio
async def test_real_variational_audio_exact_length_and_changed_sections(tmp_path):
    rate=48000;t=np.arange(rate*2)/rate;source=tmp_path/'music.wav';sf.write(source,np.column_stack([.15*np.sin(2*np.pi*220*t),.12*np.sin(2*np.pi*330*t)]),rate)
    out=tmp_path/'extended/final.wav';report=await process_audio([source],out,12,'Variational Extend')
    assert sf.info(out).frames==12*rate and report['true_peak_dbtp']<=-1
    sections=report['variation']['sections'];assert len(sections)>1 and len({s['tempo'] for s in sections})==len(sections)
    audio,_=sf.read(out);assert np.max(np.abs(np.diff(audio,axis=0)))<.2

@pytest.mark.asyncio
async def test_adopting_a_completed_legacy_episode_archives_final_before_reset(captured):
    from backend.orchestration.versions import Versions
    engine,store,e,root=captured;(root/'output').mkdir();(root/'output/final.mp4').write_bytes(b'old delivered final');(root/'output/metadata.json').write_text('{}')
    paths=['output/final.mp4','output/metadata.json'];store.update(e,'final_assembly','Completed',data={'artifacts':paths,'artifact_checksums':{p:checksum(root/p) for p in paths}})
    await engine.presentation.choose(e,PresentationInput(minutes=60))
    version=Versions(store,engine.root).list(e)[0]
    assert (root/version['video']).read_bytes()==b'old delivered final'
    assert store.task(e,'final_assembly')['status']=='Pending'
    (root/'output/final.mp4').write_bytes(b'new final')
    assert (root/version['video']).read_bytes()==b'old delivered final'

@pytest.mark.asyncio
async def test_tampered_unity_capture_cannot_be_selected(captured):
    engine,store,e,root=captured;before=store.config(e);(root/'visual-recording.mp4').write_bytes(b'changed externally')
    with pytest.raises(ValueError,match='Dependency artifact changed'):await engine.presentation.choose(e,PresentationInput())
    assert store.config(e)==before and set(engine.workflow(e))==set(DAG)

@pytest.mark.asyncio
async def test_each_extended_export_preserves_existing_release_folder(captured,monkeypatch,tmp_path):
    engine,store,e,root=captured;config=store.config(e);export=tmp_path/'exports';export.mkdir();old=export/('liminal-'+e);old.mkdir();(old/'final.mp4').write_bytes(b'old exported video')
    config.update(postproduction_enabled=True,output_directory=str(export));store.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(config),e))
    monkeypatch.setattr(engine,'verify_approval',lambda *args:{})
    async def assemble(audio,video,out,*args):out.write_bytes(b'extended video')
    monkeypatch.setattr('backend.orchestration.engine.assemble',assemble);(root/'metadata.json').write_text('{}')
    await engine.dispatch(e,'final_assembly');await engine.dispatch(e,'final_assembly')
    assert (old/'final.mp4').read_bytes()==b'old exported video'
    new=list(export.glob('liminal-'+e+'-extended-*'));assert len(new)==2
    assert all((p/'final.mp4').read_bytes()==b'extended video' for p in new)

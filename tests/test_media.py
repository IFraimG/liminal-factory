import json,shutil
from pathlib import Path
import pytest
import numpy as np
import soundfile as sf
from backend.audio.engineer import process_audio
from backend.media.ffmpeg import assemble,probe
from backend.integrations.process import run

pytestmark=pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg not installed')

@pytest.mark.parametrize('mode',['Seamless Loop','Ambient Evolution','Multi-track'])
async def test_real_audio_duration_peak_and_crossfade(tmp_path,mode):
    rate=48000;t=np.arange(rate*2)/rate
    wave=.18*np.sin(2*np.pi*220*t)+.04*np.sin(2*np.pi*330*t)
    source=tmp_path/'music.wav';sf.write(source,np.column_stack([wave,wave]),rate)
    other=tmp_path/'other.wav';sf.write(other,np.column_stack([wave*.8,wave*.8]),rate)
    out=tmp_path/'processed/final.wav'
    report=await process_audio([source,other] if mode=='Multi-track' else [source],out,6.25,mode)
    assert abs(sf.info(out).duration-6.25)<1/rate
    assert report['true_peak_dbtp']<=-1
    assert report['sample_peak']<1
    with sf.SoundFile(out) as f:
        maximum=0
        for block in f.blocks(blocksize=32768): maximum=max(maximum,float(np.max(np.abs(np.diff(block,axis=0)))))
    assert maximum<.1

async def test_real_video_assembly(tmp_path):
    audio=tmp_path/'audio.wav';sf.write(audio,np.sin(np.arange(96000)*2*np.pi*220/48000)*.1,48000)
    loop=tmp_path/'loop.mp4'
    await run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=0x303448:s=320x180:r=24','-t','0.5','-c:v','libx264','-pix_fmt','yuv420p',str(loop)])
    out=tmp_path/'final.mp4'
    report=await assemble(audio,loop,out,{'duration_minutes':2/60,'resolution':'1080p','fps':24})
    assert float(report['format']['duration'])==pytest.approx(2,abs=.05)
    assert {s['codec_type'] for s in report['streams']}=={'video','audio'}

async def test_revision_gain_and_fades_change_audio_without_changing_duration(tmp_path):
    rate=48000;t=np.arange(rate*2)/rate;wave=.18*np.sin(2*np.pi*220*t)
    source=tmp_path/'music.wav';sf.write(source,np.column_stack([wave,wave]),rate)
    base=tmp_path/'base/final.wav';edited=tmp_path/'edit/final.wav'
    await process_audio([source],base,6,'Seamless Loop')
    report=await process_audio([source],edited,6,'Seamless Loop',gain_db=-6,fade_seconds=1)
    original,_=sf.read(base);result,_=sf.read(edited)
    assert original.shape==result.shape==(rate*6,2)
    mid=slice(rate*2,rate*3)
    assert np.sqrt(np.mean(result[mid]**2)/np.mean(original[mid]**2))==pytest.approx(10**(-6/20),rel=.02)
    assert np.sqrt(np.mean(result[:rate//10]**2))<np.sqrt(np.mean(result[mid]**2))*.1
    assert np.sqrt(np.mean(result[-rate//10:]**2))<np.sqrt(np.mean(result[mid]**2))*.1
    assert report['gain_db']==-6 and report['fade_seconds']==1 and report['true_peak_dbtp']<=-1

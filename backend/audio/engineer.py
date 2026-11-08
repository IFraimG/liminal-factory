"""File-backed cyclic crossfade and two-pass EBU normalization. Memory bounded by source blocks."""
import json,re
from pathlib import Path
import numpy as np
import soundfile as sf
from backend.integrations.process import run
from backend.media.ffmpeg import probe

async def process_audio(inputs:list[Path],out:Path,seconds:float,mode='Seamless Loop',ffmpeg='ffmpeg',ffprobe='ffprobe'):
    if not inputs: raise ValueError('Import music first')
    if mode=='Multi-track' and len(inputs)<2: raise ValueError('Multi-track requires at least two approved files')
    out.parent.mkdir(parents=True,exist_ok=True)
    sources=[]
    for i,p in enumerate(inputs):
        dest=out.parent/f'source-{i}.wav'
        await run([ffmpeg,'-y','-v','error','-i',str(p),'-vn','-ar','48000','-ac','2','-c:a','pcm_f32le',str(dest)],timeout=600)
        sources.append(dest)
    source=sources[0]
    if mode=='Multi-track':
        source=out.parent/'multitrack.wav'
        args=[ffmpeg,'-y','-v','error']; filters=[]; last='0:a'
        for p in sources: args+=['-i',str(p)]
        for i in range(1,len(sources)):
            duration=min(3,sf.info(sources[i-1]).duration/4,sf.info(sources[i]).duration/4)
            label=f'm{i}'; filters.append(f'[{last}][{i}:a]acrossfade=d={duration}:c1=tri:c2=tri[{label}]'); last=label
        await run([*args,'-filter_complex',';'.join(filters),'-map',f'[{last}]','-c:a','pcm_f32le',str(source)],timeout=1200)
    info=sf.info(source)
    if info.duration<.5: raise ValueError('Music file must be at least 0.5 seconds')
    fade=min(int(info.samplerate*3),info.frames//4)
    # Search quiet sample windows near both boundaries; trim at most 1 second each.
    with sf.SoundFile(source) as src:
        window=min(info.samplerate,info.frames//10)
        head=src.read(window,always_2d=True); src.seek(info.frames-window); tail=src.read(window,always_2d=True)
        block=max(1,info.samplerate//100)
        def quiet(x):
            rms=[np.mean(x[i:i+block]**2) for i in range(0,len(x)-block+1,block)]
            return int(np.argmin(rms))*block
        start=quiet(head); end=info.frames-window+quiet(tail)+block
        if end-start<fade*3: start=0; end=info.frames
        src.seek(start); head=src.read(fade,always_2d=True)
        src.seek(end-fade); tail=src.read(fade,always_2d=True)
        weight=np.linspace(0,1,fade)[:,None]
        mixed=tail*(1-weight)+head*weight
        cycle=out.parent/'cycle.wav'
        with sf.SoundFile(cycle,'w',samplerate=48000,channels=2,subtype='FLOAT') as dst:
            src.seek(start+fade); remaining=end-start-2*fade
            while remaining>0:
                chunk=src.read(min(65536,remaining),always_2d=True); dst.write(chunk); remaining-=len(chunk)
            dst.write(mixed)
    evolution="volume='0.9875+0.0125*cos(2*PI*t/125)':eval=frame," if mode=='Ambient Evolution' else ''
    filters=evolution+'loudnorm=I=-18:TP=-1.5:LRA=11'
    measurement=await run([ffmpeg,'-hide_banner','-stream_loop','-1','-i',str(cycle),'-t',str(seconds),'-af',filters+':print_format=json','-f','null','-'],timeout=max(180,seconds*2))
    matches=re.findall(r'\{\s*"input_i".*?\}',measurement,re.S)
    if not matches: raise RuntimeError('Loudness measurement missing')
    stats=json.loads(matches[-1])
    if any(stats[k] in ('-inf','inf','nan') for k in ('input_i','input_tp','input_lra','input_thresh')): raise ValueError('Silent or invalid music cannot be normalized')
    norm=filters+f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true"
    await run([ffmpeg,'-y','-v','error','-stream_loop','-1','-i',str(cycle),'-t',str(seconds),'-af',norm,'-ar','48000','-c:a','pcm_s24le',str(out)],timeout=max(180,seconds*2))
    peak=0.; frames=0
    with sf.SoundFile(out) as f:
        for chunk in f.blocks(blocksize=65536): peak=max(peak,float(np.max(np.abs(chunk)))); frames+=len(chunk)
    if abs(frames/48000-seconds)>1/48000+.00001 or peak>=1: raise RuntimeError('Audio duration/clipping verification failed')
    verification=await run([ffmpeg,'-hide_banner','-i',str(out),'-af','loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json','-f','null','-'],timeout=max(180,seconds*2))
    final_stats=json.loads(re.findall(r'\{\s*"input_i".*?\}',verification,re.S)[-1])
    if float(final_stats['input_tp']) > -1.0: raise RuntimeError('True peak exceeded safety ceiling')
    report={'mode':mode,'duration':frames/48000,'sample_peak':peak,'true_peak_dbtp':float(final_stats['input_tp']),'integrated_lufs':float(final_stats['input_i']),'crossfade_seconds':fade/48000,'trim_samples':[start,end],'measurement':stats,'inputs':[p.name for p in inputs]}
    out.with_suffix('.report.json').write_text(json.dumps(report,indent=2)); return report

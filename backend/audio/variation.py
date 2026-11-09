"""Deterministic source-derived variations, streamed with crossfades; not new AI composition."""
import random
import numpy as np
import soundfile as sf
from backend.integrations.process import run

async def vary(cycle,out,seconds,ffmpeg='ffmpeg',seed=1701):
    rng=random.Random(seed);rate=48000;info=sf.info(cycle);overlap=min(8,info.duration/4,seconds/4);fade=max(1,int(overlap*rate))
    total=round(seconds*rate);written=0;tail=None;sections=[];variant=out.with_name('variation-part.wav')
    with sf.SoundFile(out,'w',samplerate=rate,channels=2,subtype='FLOAT') as dst:
        while written<total:
            index=len(sections);tempo=1 if not index else rng.uniform(.97,1.03);offset=0 if not index else rng.uniform(0,max(0,info.duration-overlap));tone=0 if not index else rng.uniform(-.8,.8)
            length=min(max(4,info.duration*rng.uniform(.85,1.15)),180,(total-written)/rate+overlap)
            await run([ffmpeg,'-y','-v','error','-stream_loop','-1','-ss',str(offset),'-i',str(cycle),'-t',str(length),'-af',f'atempo={tempo},equalizer=f=220:t=q:w=0.7:g={tone}','-ar',str(rate),'-ac','2','-c:a','pcm_f32le',str(variant)],timeout=max(120,length*4))
            with sf.SoundFile(variant) as src:
                if tail is not None:
                    head=src.read(min(len(tail),src.frames),always_2d=True);count=min(len(head),total-written)
                    angle=np.linspace(0,np.pi/2,len(head))[:,None]
                    mixed=tail[:len(head)]*np.cos(angle)+head*np.sin(angle);dst.write(mixed[:count]);written+=count
                remaining=src.frames-src.tell();keep=min(fade,max(0,remaining//2))
                while remaining>keep and written<total:
                    chunk=src.read(min(65536,remaining-keep,total-written),always_2d=True)
                    if not len(chunk):break
                    dst.write(chunk);written+=len(chunk);remaining-=len(chunk)
                tail=src.read(keep,always_2d=True)
            sections.append({'tempo':tempo,'source_offset_seconds':offset,'tone_db':tone,'seconds':length})
            if total-written<=len(tail):dst.write(tail[:total-written]);written=total
    variant.unlink(missing_ok=True)
    return {'seed':seed,'sections':sections,'crossfade_seconds':overlap,'method':'source-derived tempo/EQ/entry variations with equal-power crossfades','limitation':'Original timbre and motifs recur; this is not a newly composed hour of music.'}

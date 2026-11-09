"""Build a short seamless cycle once, then stream-copy repeats to the release length."""
import json
from fractions import Fraction
from backend.media.ffmpeg import probe
from backend.integrations.process import run

async def extend_visual(source,out,config,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    seconds=config['presentation_minutes']*60;fps=config['fps'];w,h={'1080p':(1920,1080),'1440p':(2560,1440),'4K':(3840,2160)}[config['resolution']]
    mode=config['presentation_mode'];cycle=out.with_name('release-cycle.mp4');partial=out.with_name('extended-visual.inprogress.mp4')
    scale=f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p'
    if mode=='image':
        await run([ffmpeg,'-y','-v','error','-loop','1','-i',str(source),'-t','2','-vf',scale,'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','20',str(cycle)],timeout=180)
        fade=0
    else:
        report=await probe(source,ffprobe);duration=float(report['format']['duration']);fade=min(.75,duration/4)
        if duration<.2:raise ValueError('Unity recording is too short to loop')
        graph=f'[0:v]{scale},split=3[m][t][h];[m]trim=start={fade}:end={duration-fade},setpts=PTS-STARTPTS[mid];[t]trim=start={duration-fade},setpts=PTS-STARTPTS[tail];[h]trim=end={fade},setpts=PTS-STARTPTS[head];[tail][head]xfade=transition=fade:duration={fade}:offset=0[seam];[mid][seam]concat=n=2:v=1:a=0[v]'
        await run([ffmpeg,'-y','-v','error','-filter_complex_threads','1','-i',str(source),'-filter_complex',graph,'-map','[v]','-an','-c:v','libx264','-threads','2','-preset','fast','-crf','20',str(cycle)],timeout=max(180,duration*20))
    await run([ffmpeg,'-y','-v','error','-stream_loop','-1','-i',str(cycle),'-t',str(seconds),'-an','-c:v','copy','-movflags','+faststart',str(partial)],timeout=max(180,seconds))
    report=await probe(partial,ffprobe);video=next(s for s in report['streams'] if s['codec_type']=='video')
    if abs(float(report['format']['duration'])-seconds)>max(.1,1/fps) or (video['width'],video['height'])!=(w,h) or abs(float(Fraction(video['avg_frame_rate']))-fps)>.01:raise ValueError('Extended visual duration/resolution/FPS verification failed')
    for position in (0,max(0,seconds/2-.25),max(0,seconds-.25)):
        await run([ffmpeg,'-v','error','-ss',str(position),'-i',str(partial),'-t','0.25','-f','null','-'],timeout=60)
    partial.replace(out);report.update(source=str(source.name),mode=mode,seam_crossfade_seconds=fade)
    out.with_suffix('.report.json').write_text(json.dumps(report,indent=2))
    return {'artifacts':[out.name,out.with_suffix('.report.json').name]}

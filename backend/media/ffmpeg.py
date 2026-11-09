import json
from fractions import Fraction
from pathlib import Path
from backend.integrations.process import run

async def probe(path,ffprobe='ffprobe'):
    return json.loads(await run([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(path)]))

async def assemble(audio:Path,loop:Path,out:Path,config,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    w,h={'1080p':(1920,1080),'1440p':(2560,1440),'4K':(3840,2160)}[config['resolution']]
    seconds=config['duration_minutes']*60; fps=config['fps']
    loop_args=[] if config.get('recording_minutes') or config.get('postproduction_enabled') else ['-stream_loop','-1']
    if config.get('recording_minutes') or config.get('postproduction_enabled'):
        source=await probe(loop,ffprobe)
        if abs(float(source['format']['duration'])-seconds)>max(.1,1/fps):raise RuntimeError('Unity recording duration does not match the user input')
    encode=['-c:v','copy'] if config.get('postproduction_enabled') else ['-vf',f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps}','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p']
    await run([ffmpeg,'-y','-v','warning',*loop_args,'-i',str(loop),'-i',str(audio),'-t',str(seconds),'-map','0:v:0','-map','1:a:0',*encode,'-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)],timeout=max(600,seconds*20),log=out.with_suffix('.log'))
    report=await probe(out,ffprobe)
    video=next((s for s in report['streams'] if s['codec_type']=='video'),None)
    audio_stream=next((s for s in report['streams'] if s['codec_type']=='audio'),None)
    if not video or not audio_stream: raise RuntimeError('Output is missing an audio/video stream')
    if video['codec_name']!='h264' or audio_stream['codec_name']!='aac': raise RuntimeError('Unexpected output codecs')
    if (video['width'],video['height'])!=(w,h) or abs(float(Fraction(video['avg_frame_rate']))-fps)>.01: raise RuntimeError('Resolution/FPS verification failed')
    if abs(float(report['format']['duration'])-seconds)>max(.1,1/fps): raise RuntimeError('Video duration verification failed')
    for start in (0,max(0,seconds/2-1),max(0,seconds-1)):
        await run([ffmpeg,'-v','error','-ss',str(start),'-i',str(out),'-t','1','-f','null','-'],timeout=60)
    out.with_suffix('.report.json').write_text(json.dumps(report,indent=2))
    return report

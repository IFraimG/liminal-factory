import asyncio,json,time
from pathlib import Path
import numpy as np
import soundfile as sf
from backend.audio.engineer import process_audio
from backend.media.extend import extend_visual
from backend.media.ffmpeg import assemble,probe
from backend.integrations.process import run

async def main():
 root=Path('work/extended-hour-check');root.mkdir(exist_ok=True);rate=48000
 source=root/'ambient.wav'
 with sf.SoundFile(source,'w',samplerate=rate,channels=2,subtype='PCM_16') as dst:
  for second in range(60):
   t=(np.arange(rate)+second*rate)/rate
   wave=(.12*np.sin(2*np.pi*110*t)+.05*np.sin(2*np.pi*165*t)+.03*np.sin(2*np.pi*220*t))*(.8+.2*np.sin(2*np.pi*t/37))
   dst.write(np.column_stack([wave,wave*.97]))
 clip=root/'unity-fixture.mp4'
 await run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=0x303448:s=640x360:r=24','-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(clip)])
 cfg={'presentation_minutes':60,'duration_minutes':60,'presentation_mode':'video','postproduction_enabled':True,'resolution':'1080p','fps':24,'recording_minutes':2/60}
 start=time.monotonic()
 audio_task=asyncio.create_task(process_audio([source],root/'audio/final.wav',3600,'Variational Extend'))
 video_task=asyncio.create_task(extend_visual(clip,root/'extended-visual.mp4',cfg))
 audio,video=await asyncio.gather(audio_task,video_task)
 await assemble(root/'audio/final.wav',root/'extended-visual.mp4',root/'final.mp4',cfg)
 report=await probe(root/'final.mp4');assert abs(float(report['format']['duration'])-3600)<.1
 assert sf.info(root/'audio/final.wav').frames==48000*3600
 result={'elapsed_seconds':time.monotonic()-start,'duration':report['format']['duration'],'video':[{k:s.get(k) for k in ['codec_name','width','height','avg_frame_rate','duration']} for s in report['streams']],'variation_sections':len(audio['variation']['sections']),'true_peak':audio['true_peak_dbtp'],'source':'isolated synthetic fixture; no production episode changed'}
 (root/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
asyncio.run(main())

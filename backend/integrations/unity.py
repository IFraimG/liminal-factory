import json,shutil,sys
from fractions import Fraction
from backend.media.ffmpeg import probe
from pathlib import Path
from backend.integrations.process import run

def template_path():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))/'unity-template'

def discover():
    return sorted(Path('/Applications/Unity/Hub/Editor').glob('*/Unity.app/Contents/MacOS/Unity'),reverse=True)

class Unity:
    def __init__(self,executable,ffmpeg='ffmpeg',ffprobe='ffprobe'): self.exe=executable; self.ffmpeg=ffmpeg; self.ffprobe=ffprobe
    async def render(self,root,config,preview=True):
        project=root/'unity-project'; log=root/('unity-preview.log' if preview else 'unity-render.log')
        if not preview and not (project/'Assets/Liminal.unity').is_file():raise RuntimeError('Approved Unity scene is missing. Rebuild and approve a preview before recording.')
        if not (project/'ProjectSettings/ProjectVersion.txt').exists():
            try:
                await run([self.exe,'-batchmode','-quit','-createProject',str(project),'-logFile',str(root/'unity-create.log')],timeout=300)
            except Exception as exc:
                create_log=root/'unity-create.log'
                detail=create_log.read_text(errors='replace')[-3000:] if create_log.exists() else ''
                raise RuntimeError(f'Unity project creation failed ({type(exc).__name__}). Check Unity Hub licensing and graphics. {detail}') from None
        editor=project/'Assets/Editor'; editor.mkdir(parents=True,exist_ok=True)
        script='LiminalScene.cs' if preview else 'LiminalRecording.cs'
        shutil.copy2(template_path()/'Assets/Editor'/script,editor/script)
        w,h=(1280,720) if preview else {'1080p':(1920,1080),'1440p':(2560,1440),'4K':(3840,2160)}[config['resolution']]
        folder=root/('preview-frames' if preview else 'recording-frames'); folder.mkdir(exist_ok=True)
        for name in ('complete.json','progress.json','error.txt'):(folder/name).unlink(missing_ok=True)
        c={'width':w,'height':h,'fps':12 if preview else config['fps'],'seconds':config['loop_seconds'] if preview else (config.get('recording_minutes') or config['duration_minutes'])*60,'style':config['style']}
        spec=root/'scene_spec.json'
        if spec.exists():
            from backend.models.schema import SceneSpec
            c.update(SceneSpec.model_validate_json(spec.read_text()).model_dump())
        target=root/('preview.mp4' if preview else 'visual-recording.mp4')
        partial=root/'visual-recording.inprogress.mp4'
        if not preview:c.update(ffmpeg=str(Path(self.ffmpeg).resolve()) if '/' in self.ffmpeg else shutil.which(self.ffmpeg),video_path=str(partial))
        config_path=root/'unity-render-config.json'; config_path.write_text(json.dumps(c))
        try:
            await run([self.exe,'-batchmode',*(['-quit'] if preview else []),'-projectPath',str(project),'-executeMethod','LiminalScene.Render' if preview else 'LiminalRecording.Render','-lfOutput',str(folder),'-lfConfig',str(config_path),'-logFile',str(log)],timeout=max(3600,c['seconds']*30))
        except Exception as exc:
            detail=log.read_text(errors='replace')[-3000:] if log.exists() else ''
            capture_error=(folder/'error.txt').read_text(errors='replace')[-1500:] if (folder/'error.txt').exists() else ''
            progress=(folder/'progress.json').read_text() if (folder/'progress.json').exists() else 'No capture progress recorded'
            reason='Unity was terminated by SIGKILL (-9). This can be memory pressure or an external kill; the exit code does not prove a license/graphics failure.' if getattr(exc,'returncode',None)==-9 else 'Unity capture failed; inspect the capture error and Unity log.'
            raise RuntimeError(f'{reason} Last progress: {progress}\n{capture_error}\n{exc}\n{detail}') from None
        if not (folder/'complete.json').exists(): raise RuntimeError('Unity did not finish frame capture; inspect Unity log for compile/graphics errors')
        if not preview:
            manifest=json.loads((folder/'complete.json').read_text())
            if manifest.get('frames')!=round(c['seconds']*c['fps']) or not partial.is_file():raise RuntimeError('Incomplete Unity recording')
            report=await probe(partial,self.ffprobe)
            video=next((stream for stream in report.get('streams',[]) if stream.get('codec_type')=='video'),{})
            if (video.get('width'),video.get('height'))!=(w,h) or abs(float(Fraction(video.get('avg_frame_rate','0')))-c['fps'])>.01:raise RuntimeError('Recording resolution/frame rate mismatch')
            if abs(float(report['format']['duration'])-c['seconds'])>max(.1,1/c['fps']):raise RuntimeError('Recording duration mismatch')
            if int(video.get('nb_frames',0))!=manifest['frames']:raise RuntimeError('Recording frame count mismatch')
            partial.replace(target)
            (root/'visual-recording.report.json').write_text(json.dumps(report,indent=2))
            return {'artifacts':[target.name,'visual-recording.report.json','recording-frames/complete.json','recording-frames/progress.json','unity-project/Assets/Editor/LiminalRecording.cs','unity-project/Assets/Liminal.unity',log.name,*[str(p.relative_to(root)) for p in sorted((project/'Assets/LiminalGenerated').glob('*')) if p.suffix in {'.mat','.asset'}]]}
        await run([self.ffmpeg,'-y','-v','error','-framerate',str(c['fps']),'-i',str(folder/'frame-%05d.png'),'-frames:v',str(round(c['seconds']*c['fps'])),'-c:v','libx264','-pix_fmt','yuv420p',str(target)],timeout=600)
        return {'artifacts':[target.name,'unity-project/Assets/Liminal.unity',log.name,*[str(p.relative_to(root)) for p in sorted((project/'Assets/LiminalGenerated').glob('*')) if p.suffix in {'.mat','.asset'}]]}

import json,shutil,sys
from pathlib import Path
from backend.integrations.process import run

def template_path():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))/'unity-template'

def discover():
    return sorted(Path('/Applications/Unity/Hub/Editor').glob('*/Unity.app/Contents/MacOS/Unity'),reverse=True)

class Unity:
    def __init__(self,executable,ffmpeg='ffmpeg'): self.exe=executable; self.ffmpeg=ffmpeg
    async def render(self,root,config,preview=True):
        project=root/'unity-project'; log=root/('unity-preview.log' if preview else 'unity-render.log')
        if not (project/'ProjectSettings/ProjectVersion.txt').exists():
            try:
                await run([self.exe,'-batchmode','-quit','-createProject',str(project),'-logFile',str(root/'unity-create.log')],timeout=300)
            except Exception as exc:
                create_log=root/'unity-create.log'
                detail=create_log.read_text(errors='replace')[-3000:] if create_log.exists() else ''
                raise RuntimeError(f'Unity project creation failed ({type(exc).__name__}). Check Unity Hub licensing and graphics. {detail}') from None
        editor=project/'Assets/Editor'; editor.mkdir(parents=True,exist_ok=True)
        shutil.copy2(template_path()/'Assets/Editor/LiminalScene.cs',editor/'LiminalScene.cs')
        w,h=(640,360) if preview else {'1080p':(1920,1080),'1440p':(2560,1440),'4K':(3840,2160)}[config['resolution']]
        folder=root/('preview-frames' if preview else 'loop-frames'); folder.mkdir(exist_ok=True)
        (folder/'complete.json').unlink(missing_ok=True)
        c={'width':w,'height':h,'fps':12 if preview else config['fps'],'seconds':config['loop_seconds'],'style':config['style']}
        spec=root/'scene_spec.json'
        if spec.exists(): c.update(json.loads(spec.read_text()))
        config_path=root/'unity-render-config.json'; config_path.write_text(json.dumps(c))
        try:
            await run([self.exe,'-batchmode','-quit','-projectPath',str(project),'-executeMethod','LiminalScene.Render','-lfOutput',str(folder),'-lfConfig',str(config_path),'-logFile',str(log)],timeout=3600)
        except Exception as exc:
            detail=log.read_text(errors='replace')[-3000:] if log.exists() else ''
            raise RuntimeError(f'Unity batch render failed. Requires licensed Editor and working graphics. {exc}\n{detail}') from None
        if not (folder/'complete.json').exists(): raise RuntimeError('Unity did not finish frame capture; inspect Unity log for compile/graphics errors')
        target=root/('preview.mp4' if preview else 'visual-loop.mp4')
        await run([self.ffmpeg,'-y','-v','error','-framerate',str(c['fps']),'-i',str(folder/'frame-%05d.png'),'-frames:v',str(round(c['seconds']*c['fps'])),'-c:v','libx264','-pix_fmt','yuv420p',str(target)],timeout=600)
        return {'artifacts':[target.name,'unity-project/Assets/Liminal.unity',log.name]}

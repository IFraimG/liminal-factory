import asyncio,json,uuid,time,shutil
from pathlib import Path
from backend.orchestration.workflow import DAG,GATES,AGENT_TASKS
from backend.orchestration.herdr_adapter import HerdrAdapter
from backend.integrations.antigravity import AntigravitySession,AntigravityAdapter
from backend.models.schema import MusicBrief,VisualBrief,Metadata,SceneSpec
from backend.integrations.process import checksum,contained,PROCESS_OBSERVER
from backend.integrations.unity import Unity
from backend.integrations.youtube import channel_titles
from backend.agents.providers import REFERENCE_POLICY
from backend.audio.reference import analyze
from backend.audio.engineer import process_audio
from backend.media.ffmpeg import assemble

SUCCESS={'Completed','Approved'}

class Engine:
    def __init__(self,store,root,settings,adapter=None,handlers=None):
        self.store=store; self.root=Path(root); self.settings=settings; self.adapter=adapter
        self.semaphore=asyncio.Semaphore(settings.max_concurrent_agents); self.running={}; self.wake=asyncio.Event(); self.stopping=False
        self.handlers=handlers or {}; self.scheduler=None; self._client_session=None
    def directory(self,e): return contained(self.root,e)
    def tool(self,name):
        value=self.settings.tools.get(name) or shutil.which(name)
        if not value: raise RuntimeError(f'{name} missing. Install it and set the executable path in Settings.')
        return value
    def client_session(self):
        if self._client_session is None:
            self._client_session=AntigravitySession(self.tool('hc'),self.settings.tools.get('agy'),self.settings.antigravity_port,self.settings.antigravity_wait_seconds,expected_cwd=self.root)
        return self._client_session
    def herdr(self,task=''):
        if self.adapter: return self.adapter
        if self.settings.agent_kind in {'gemini','antigravity'}: return AntigravityAdapter(self.client_session())
        return HerdrAdapter(self.tool('herdr'),self.settings.agent_kind,self.settings.agent_models.get(task,self.settings.model),[str(Path(self.tool(self.settings.agent_kind)).parent)])
    def create(self,config):
        e=uuid.uuid4().hex; self.directory(e).mkdir(parents=True)
        self.store.execute('INSERT INTO episodes VALUES(?,?,?)',(e,json.dumps(config),time.time()))
        for n in DAG: self.store.execute('INSERT INTO tasks(episode,name) VALUES(?,?)',(e,n))
        self.store.log(e,'system','Episode created. Import visual references, then Start Production.'); return e
    async def start(self,e):
        config=self.store.config(e)
        if not config['permission']: raise ValueError('Audio download permission is required')
        if not list((self.directory(e)/'references').glob('*')): raise ValueError('Add at least one visual reference')
        # Starting does not hide missing dependencies behind successful mock results.
        for tool in ('ffmpeg','ffprobe','yt-dlp','unity'): self.tool(tool)
        await self.herdr().check()
        if not self.settings.vision_enabled: raise ValueError('Enable image-capable agent support in Settings after verifying your model can inspect local images')
        if self.settings.agent_kind in {'gemini','antigravity'}:
            await self.client_session().prepare()
        self.store.log(e,'system','Production started')
        self.store.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)",('started:'+e,'true',time.time()))
        self.wake.set()
    def enabled(self,e): return bool(self.store.rows('SELECT key FROM cache WHERE key=?',('started:'+e,)))
    async def recover(self):
        # Never kill or trust a saved PID. Reconcile only the persisted Herdr identity.
        for t in self.store.rows("SELECT * FROM tasks WHERE status IN ('Running','Waiting for Client')"):
            e,n=t['episode'],t['name']; data=json.loads(t['data']); identity=data.get('identity')
            if identity and identity.get('owned') is False:
                message='Client task interrupted by restart. Its user-owned pane was left untouched; reconnect the Client-launched session and retry.'
            elif identity:
                try:
                    adapter=self.herdr(n)
                    await adapter.cli('agent','get',identity['agent'])
                    await adapter.cancel(identity)
                    message='Interrupted agent reconciled and stopped; retry to produce a newly validated artifact.'
                except Exception: message='Saved agent could not be verified; inspect Herdr before retrying. No PID was signalled.'
            else: message='Local operation interrupted by restart; retry explicitly.'
            self.store.update(e,n,'Failed',message); self.store.log(e,n,message)
    async def serve(self):
        await self.recover()
        while not self.stopping:
            for episode in self.store.rows('SELECT id FROM episodes'):
                e=episode['id']
                if not self.enabled(e): continue
                for n,deps in DAG.items():
                    key=(e,n); t=self.store.task(e,n)
                    if key in self.running or t['status']!='Pending': continue
                    if not all(self.store.task(e,d)['status'] in SUCCESS for d in deps): continue
                    if n in GATES:
                        self.store.update(e,n,'Waiting for Approval'); self.store.log(e,n,'User approval required'); continue
                    # Claim synchronously before yielding to prevent duplicate scheduling.
                    self.store.update(e,n,'Running',error='')
                    task=asyncio.create_task(self.execute(e,n)); self.running[key]=task
                    task.add_done_callback(lambda _,key=key:self.running.pop(key,None))
            try: await asyncio.wait_for(self.wake.wait(),.5)
            except asyncio.TimeoutError: pass
            self.wake.clear()
    async def execute(self,e,n):
        async with self.semaphore:
            self.store.log(e,n,'Task started')
            def observe(info):
                data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,'process':info})
            context=PROCESS_OBSERVER.set(observe)
            try:
                for dependency in DAG[n]: self.verify_artifacts(e,dependency)
                data=await asyncio.wait_for(self.dispatch(e,n),timeout=14400)
                data=data or {}
                data['artifact_checksums']={name:checksum(contained(self.directory(e),name)) for name in data.get('artifacts',[]) if contained(self.directory(e),name).is_file()}
                t=self.store.task(e,n); self.store.update(e,n,'Completed',data={**t['data'],**(data or {})})
                self.store.log(e,n,'Task completed; artifacts validated')
            except asyncio.CancelledError:
                self.store.update(e,n,'Cancelled'); self.store.log(e,n,'Cancelled'); raise
            except Exception as exc:
                message=str(exc) or type(exc).__name__
                self.store.update(e,n,'Failed',error=message); self.store.log(e,n,message)
            finally:
                PROCESS_OBSERVER.reset(context)
                self.wake.set()
    def verify_artifacts(self,e,n):
        data=self.store.task(e,n)['data']
        for name,digest in data.get('artifact_checksums',{}).items():
            if checksum(contained(self.directory(e),name))!=digest: raise ValueError('Dependency artifact changed: '+name)
    def verify_approval(self,e,gate):
        data=self.store.task(e,gate)['data']
        if not data.get('checksums'): raise ValueError('Approval has no file checksums')
        for name,digest in data['checksums'].items():
            if checksum(contained(self.directory(e),name))!=digest: raise ValueError(f'Approved artifact changed: {name}; request changes and approve again')
        return data
    async def ask(self,e,n,prompt,schema):
        root=self.directory(e); result=f'{n}-{uuid.uuid4().hex}.json'
        def save(identity):
            data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,'identity':identity})
        adapter=self.herdr(n)
        if isinstance(adapter,AntigravityAdapter):
            def waiting():
                self.store.update(e,n,'Waiting for Client')
                self.store.log(e,n,'Waiting for Antigravity Client → CLI → your confirmed idle Herdr pane. No direct Gemini/agy launch.')
            adapter.on_wait=waiting
            adapter.on_ready=lambda:self.store.update(e,n,'Running')
            adapter.on_state=lambda state:self.store.log(e,n,'Client CLI is waiting for your permission/auth response in Herdr; no dialog is auto-approved.' if state=='blocked' else 'Client CLI state: '+state)
        feedback=self.store.task(e,n)['data'].get('feedback','')
        if feedback: prompt+='\nUser requested changes (creative guidance only): '+feedback
        try:
            data=await adapter.launch(root,REFERENCE_POLICY+'\n'+prompt+'\nRequired JSON schema: '+json.dumps(schema.model_json_schema()),result,save)
            checked=schema.model_validate(data).model_dump()
            (root/f'{n}.json').write_text(json.dumps(checked,indent=2))
            return {'artifacts':[f'{n}.json'],'result':checked}
        finally:
            identity=self.store.task(e,n)['data'].get('identity')
            if identity:
                try:
                    text=await adapter.logs(identity); (root/f'{n}-agent.log').write_text(text)
                except Exception: pass
                await adapter.cancel(identity)
    async def dispatch(self,e,n):
        if n in self.handlers: return await self.handlers[n](e,n)
        c=self.store.config(e); root=self.directory(e)
        if n=='audio_reference': return await analyze(root,c,self.tool,self.settings.yt_dlp_use_chrome_cookies,self.settings.yt_dlp_chrome_profile)
        if n=='music_brief':
            return await self.ask(e,n,'Read audio_analysis.json (technical analysis only). Create an original ambient music brief and at least 2 Suno prompts for '+c['style']+'. Do not claim you listened to audio.',MusicBrief)
        if n=='visual_reference':
            if not self.settings.vision_enabled: raise RuntimeError('Visual analysis unavailable: configure an image-capable agent/model and enable vision in Settings')
            images=[str(contained(root,p)) for p in json.loads((root/'references.json').read_text())]
            return await self.ask(e,n,'Use your image viewing capability to inspect these actual images: '+json.dumps(images)+'. If you cannot inspect pixels, fail explicitly; do not infer their content from filenames. Describe the scene for a procedural Unity interpretation.',VisualBrief)
        if n=='channel_reference':
            titles=await channel_titles(c['channel_url'],self.tool('yt-dlp'),self.store,self.settings.cache_hours,self.settings.yt_dlp_use_chrome_cookies,self.settings.yt_dlp_chrome_profile)
            (root/'channel_titles.json').write_text(json.dumps(titles)); return {'artifacts':['channel_titles.json'],'count':len(titles)}
        if n=='metadata':
            result=await self.ask(e,n,'Read channel_titles.json, music_brief.json and visual_reference.json. Analyze title patterns and create 5 original titles, recommended title, description and hashtags as #tag, #tag. Do not copy source titles or make performance claims.',Metadata)
            originals=json.loads((root/'channel_titles.json').read_text())
            if any(t.casefold() in {s.casefold() for s in originals} for t in result['result']['titles']): raise ValueError('Generated title duplicates a channel reference')
            return result
        if n=='audio_engineer':
            data=self.verify_approval(e,'music_approval'); paths=[contained(root,p) for p in data['music']]
            await process_audio(paths,root/'final.wav',c['duration_minutes']*60,c['audio_mode'],self.tool('ffmpeg'),self.tool('ffprobe'))
            return {'artifacts':['final.wav','final.report.json']}
        if n=='unity_preview':
            spec=await self.ask(e,n,'Read visual_reference.json and design a procedural Unity scene using the available parameters. Choose numeric scene values matching the actual brief. Style: '+c['style'],SceneSpec)
            (root/'scene_spec.json').write_text(json.dumps(spec['result'],indent=2))
            result=await Unity(self.tool('unity'),self.tool('ffmpeg')).render(root,c,True)
            data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,**result})
            # A real image-capable model performs visual QA; it is an additional required artifact.
            qa=await self.ask(e,n,'Inspect preview-frames/frame-00000.png and the actual images in references/. Compare architecture, palette, framing and atmosphere. Describe discrepancies and suggestions truthfully, using the VisualBrief fields. Do not claim a match without inspecting both.',VisualBrief)
            return {'artifacts':result['artifacts']+qa['artifacts'],'qa':qa['result']}
        if n=='visual_render':
            self.verify_approval(e,'visual_approval')
            return await Unity(self.tool('unity'),self.tool('ffmpeg')).render(root,c,False)
        if n=='final_assembly':
            self.verify_approval(e,'music_approval'); self.verify_approval(e,'visual_approval')
            out=root/'output'; out.mkdir(exist_ok=True)
            await assemble(root/'final.wav',root/'visual-loop.mp4',out/'final.mp4',c,self.tool('ffmpeg'),self.tool('ffprobe'))
            shutil.copy2(root/'metadata.json',out/'metadata.json')
            if c.get('output_directory'):
                destination=Path(c['output_directory']).expanduser().resolve()/('liminal-'+e)
                destination.mkdir(parents=True,exist_ok=False)
                shutil.copy2(out/'final.mp4',destination/'final.mp4'); shutil.copy2(out/'metadata.json',destination/'metadata.json')
            return {'artifacts':['output/final.mp4','output/metadata.json']}
        raise ValueError('Unknown task '+n)
    async def cancel(self,e,n):
        if n not in DAG: raise ValueError('Unknown task')
        task=self.running.get((e,n))
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        identity=self.store.task(e,n)['data'].get('identity')
        if identity: await self.herdr(n).cancel(identity)
        self.store.update(e,n,'Cancelled')
    async def retry(self,e,n):
        if n not in DAG: raise ValueError('Unknown task')
        if self.store.task(e,n)['status'] not in {'Failed','Cancelled'}: raise ValueError('Only failed/cancelled tasks can be retried')
        if any(self.store.task(e,d)['status'] not in SUCCESS for d in DAG[n]): raise ValueError('Complete dependencies first')
        self.store.update(e,n,'Pending',error='',data={}); self.wake.set()
    async def request_changes(self,e,n,reason):
        if n not in GATES: raise ValueError('Changes require an approval gate')
        # Invalidate all transitive downstream consumers before rerunning upstream work.
        source='music_brief' if n=='music_approval' else 'unity_preview'
        affected={source,n}; changed=True
        while changed:
            new={task for task,deps in DAG.items() if any(d in affected for d in deps)}-affected
            changed=bool(new); affected|=new
        for task in affected:
            if (e,task) in self.running: await self.cancel(e,task)
            self.store.update(e,task,'Pending',error='',data={})
        self.store.update(e,source,data={'feedback':reason})
        self.store.log(e,n,'Requested changes: '+reason); self.wake.set()
    async def approve(self,e,n):
        if n not in GATES or self.store.task(e,n)['status']!='Waiting for Approval': raise ValueError('Task is not awaiting approval')
        root=self.directory(e)
        if n=='music_approval':
            paths=sorted((root/'music').glob('*'))
            if not paths: raise ValueError('Import generated music first')
            c=self.store.config(e)
            if c['audio_mode']=='Multi-track' and len(paths)<2: raise ValueError('Multi-track needs two music files')
            names=[str(p.relative_to(root)) for p in paths]; names+=['music_brief.json']
        else:
            names=['preview.mp4','unity_preview.json','scene_spec.json','unity-project/Assets/Editor/LiminalScene.cs','visual_reference.json']
        data={'checksums':{name:checksum(contained(root,name)) for name in names}}
        if n=='music_approval': data['music']=[name for name in names if name.startswith('music/')]
        self.store.update(e,n,'Approved',data=data); self.store.log(e,n,'Approved with SHA-256 checksums'); self.wake.set()
    async def close(self):
        self.stopping=True
        if self.scheduler: self.scheduler.cancel()
        tasks=list(self.running.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

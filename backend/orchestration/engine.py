import asyncio,json,uuid,time,shutil
from pathlib import Path
from backend.orchestration.workflow import DAG,GATES,AGENT_TASKS
from backend.orchestration.herdr_adapter import HerdrAdapter
from backend.integrations.antigravity import AntigravitySession,AntigravityAdapter
from backend.models.schema import MusicBrief,SunoMusicBrief,VisualBrief,Metadata,SceneSpec
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
        for t in self.store.rows("SELECT * FROM tasks WHERE status IN ('Running','Waiting for Client','Waiting for CLI','Waiting for Permission')"):
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
                data=await self.dispatch_with_budget(e,n)
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
    async def dispatch_with_budget(self,e,n,budget=14400):
        operation=asyncio.create_task(self.dispatch(e,n));last=time.monotonic()
        paused={'Waiting for Client','Waiting for CLI','Waiting for Permission'}
        try:
            while True:
                done,_=await asyncio.wait({operation},timeout=min(.5,max(.001,budget)))
                if done: return await operation
                now=time.monotonic()
                if self.store.task(e,n)['status'] not in paused: budget-=now-last
                last=now
                if budget<=0: raise TimeoutError('Task active-work safety limit reached; CLI queue and permission pauses are excluded.')
        finally:
            if not operation.done(): operation.cancel()
            await asyncio.gather(operation,return_exceptions=True)
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
            snapshot={}
            for dependency in DAG[n]:
                for path in self.store.task(e,dependency)['data'].get('artifacts',[]): snapshot[path]=checksum(contained(root,path))
            identity={**identity,'input_checksums':snapshot,'result_schema':schema.__name__}
            data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,'identity':identity})
        adapter=self.herdr(n)
        if isinstance(adapter,AntigravityAdapter):
            def waiting():
                self.store.update(e,n,'Waiting for Client')
                self.store.log(e,n,'Waiting for Antigravity Client → CLI → your confirmed idle Herdr pane. No direct Gemini/agy launch.')
            adapter.on_wait=waiting
            adapter.on_ready=lambda:self.store.update(e,n,'Running')
            def state_changed(state):
                if state in {'blocked','waiting_blocked'}:
                    self.store.update(e,n,'Waiting for Permission')
                    message='CLI is waiting for your permission in Herdr. Active-time timer is paused; no dialog is auto-approved.'
                elif state in {'queued','waiting_busy'}:
                    self.store.update(e,n,'Waiting for CLI')
                    message='Queued for the connected CLI; no prompt sent by this task yet.'
                else:
                    self.store.update(e,n,'Running')
                    message='Client CLI state: '+state
                self.store.log(e,n,message)
            adapter.on_state=state_changed
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
            return await self.ask(e,n,'Read audio_analysis.json (technical analysis only). Create an original ambient music brief and at least 2 Suno prompts for '+c['style']+'. Do not claim you listened to audio. Include required suno_options for Suno More Options: excluded styles, Weirdness and Style Influence (0–100), Variety (off/normal/high/extra/max), duration_seconds (30–600), Max Mode boolean, personalize off, vocal_gender none for instrumental. Explain why every choice fits the musical brief and measurements in rationale. These are generation settings, not measured properties. Do not blindly use defaults. If an existing music_brief.json is present and feedback requests only More Options, keep its brief and prompts exactly and add the settings.',SunoMusicBrief)
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
            checkpoint=self.store.task(e,n)['data'].get('preview_checkpoint')
            reuse=bool(checkpoint)
            if reuse:
                try:
                    for path,digest in checkpoint['checksums'].items():
                        if checksum(contained(root,path))!=digest: reuse=False;break
                except (OSError,KeyError,ValueError): reuse=False
            if reuse:
                result={'artifacts':checkpoint['artifacts']}
                self.store.log(e,n,'Reusing verified Unity preview; resuming visual QA only.')
            else:
                spec=await self.ask(e,n,'Read visual_reference.json and design a procedural Unity scene using the available parameters. Choose numeric scene values matching the actual brief. Style: '+c['style'],SceneSpec)
                (root/'scene_spec.json').write_text(json.dumps(spec['result'],indent=2))
                result=await Unity(self.tool('unity'),self.tool('ffmpeg')).render(root,c,True)
                paths=set(result['artifacts']+['scene_spec.json','visual_reference.json','references.json','preview-frames/frame-00000.png','preview-frames/complete.json'])
                paths.update(json.loads((root/'references.json').read_text()))
                checkpoint={'artifacts':result['artifacts'],'checksums':{path:checksum(contained(root,path)) for path in paths}}
                data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,**result,'preview_checkpoint':checkpoint})
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
    async def recover_late_result(self,e,n):
        if n!='metadata': raise ValueError('Saved-result recovery is supported for Metadata; multi-stage tasks require Retry.')
        task=self.store.task(e,n)
        if task['status']!='Failed' or (e,n) in self.running: raise ValueError('Only an inactive failed task can recover a saved result')
        root=self.directory(e);identity=task['data'].get('identity') or {}
        import re
        filename=identity.get('result','')
        if not re.fullmatch(r'metadata-[0-9a-f]{32}\.json',filename): raise ValueError('This task has no recorded result filename')
        path=contained(root,filename)
        if not path.is_file(): raise ValueError('The recorded result file has not arrived yet')
        if path.stat().st_size>4*1024*1024: raise ValueError('Saved result exceeds 4 MB')
        if not task['started'] or path.stat().st_mtime<task['started']: raise ValueError('Saved result predates this task')
        if identity.get('transport')!='herdr-core-existing-session': raise ValueError('Unsupported saved-result origin')
        session=self.client_session()
        terminal=await session.command('get',identity.get('pane',''),'--json')
        fp=session.fingerprint(terminal)
        if any(fp[k]!=identity.get(k if k!='address' else 'pane') for k in fp): raise ValueError('Original CLI process cannot be verified; inspect the saved result manually')
        if session.word(terminal) not in {'idle','done'}: raise ValueError('Wait for the original CLI turn to finish before recovering its result')
        if 'before_turn' in identity and terminal.get('turn',0)<=identity['before_turn']: raise ValueError('Original CLI turn has not completed')
        for dependency in DAG[n]:
            if self.store.task(e,dependency)['status'] not in SUCCESS: raise ValueError('Complete dependencies before recovery')
            self.verify_artifacts(e,dependency)
        for filename,digest in identity.get('input_checksums',{}).items():
            if checksum(contained(root,filename))!=digest: raise ValueError('Task inputs changed since the prompt was sent')
        current_task=self.store.task(e,n)
        if current_task['status']!='Failed' or current_task['data'].get('identity')!=identity or (e,n) in self.running:
            raise ValueError('Task changed during recovery; reload its state')
        checked=Metadata.model_validate_json(path.read_text()).model_dump()
        originals={s.casefold() for s in json.loads((root/'channel_titles.json').read_text())}
        if any(title.casefold() in originals for title in checked['titles']): raise ValueError('Generated title duplicates a channel reference')
        temp=root/('metadata-recovered-'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(checked,indent=2));temp.replace(root/'metadata.json')
        self.store.update(e,n,'Completed',error='',data={**task['data'],'result':checked,'artifacts':['metadata.json'],'artifact_checksums':{'metadata.json':checksum(root/'metadata.json')},'recovered_from':str(path.relative_to(root))})
        self.store.log(e,n,'Recovered late structured result after schema, original CLI and dependency validation. No new model prompt was sent.')
        self.wake.set();return {'recovered':True}
    async def retry(self,e,n):
        if n not in DAG: raise ValueError('Unknown task')
        if self.store.task(e,n)['status'] not in {'Failed','Cancelled'}: raise ValueError('Only failed/cancelled tasks can be retried')
        if any(self.store.task(e,d)['status'] not in SUCCESS for d in DAG[n]): raise ValueError('Complete dependencies first')
        old=self.store.task(e,n)['data']
        preserved={'preview_checkpoint':old['preview_checkpoint']} if n=='unity_preview' and old.get('preview_checkpoint') else {}
        self.store.update(e,n,'Pending',error='',data=preserved); self.wake.set()
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

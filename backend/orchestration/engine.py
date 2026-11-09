import asyncio,json,uuid,time,shutil
from pathlib import Path
from backend.orchestration.workflow import DAG,GATES,AGENT_TASKS,workflow
from backend.orchestration.herdr_adapter import HerdrAdapter
from backend.integrations.antigravity import AntigravitySession,AntigravityAdapter
from backend.integrations.kimi import KimiSession
from backend.integrations.codex_core import CodexCoreAdapter
from backend.orchestration.revisions import Revisions
from backend.orchestration.versions import Versions
from backend.orchestration.presentation import Presentation
from backend.orchestration.channel_review import ChannelReview
from backend.orchestration.scene_planning import ScenePlanning,CAPABILITIES
from backend.integrations.quota import QuotaRouter,eligible
from backend.models.schema import MusicBrief,SunoMusicBrief,VisualBrief,Metadata,SceneSpec,SceneDesign,RecordingPlan,StepPreparation,step_preparation_schema
from backend.integrations.process import checksum,contained,PROCESS_OBSERVER
from backend.integrations.unity import Unity
from backend.integrations.youtube import channel_titles
from backend.agents.providers import REFERENCE_POLICY
from backend.agents.context import episode_context
from backend.audio.reference import analyze
from backend.audio.engineer import process_audio
from backend.audio.settings import extension_settings
from backend.media.ffmpeg import assemble

from backend.orchestration.priorities import PROVIDERS,LOCAL_TASKS,ACTIVE_STATUSES,validate_order,order_for

class PriorityLockedError(ValueError):pass

SUCCESS={'Completed','Approved'}

class Engine:
    def __init__(self,store,root,settings,adapter=None,handlers=None):
        self.store=store; self.root=Path(root); self.settings=settings; self.adapter=adapter
        self.semaphore=asyncio.Semaphore(settings.max_concurrent_agents); self.running={}; self.wake=asyncio.Event(); self.stopping=False
        self.handlers=handlers or {}; self.scheduler=None; self._client_session=None; self._kimi_session=None; self.quota=QuotaRouter(self.manual_quota); self.quota_poll_interval=10; self.revisions=Revisions(self); self.presentation=Presentation(self); self.channel_review=ChannelReview(self); self.scene_planning=ScenePlanning(self)
    def workflow(self,e):return workflow(self.store.config(e))
    def directory(self,e): return contained(self.root,e)
    def tool(self,name):
        value=self.settings.tools.get(name) or shutil.which(name)
        if not value: raise RuntimeError(f'{name} missing. Install it and set the executable path in Settings.')
        return value
    def client_session(self):
        if self._client_session is None:
            self._client_session=AntigravitySession(self.tool('hc'),self.settings.tools.get('agy'),self.settings.antigravity_port,self.settings.antigravity_wait_seconds,expected_cwd=self.root)
        return self._client_session
    def kimi_session(self):
        if self._kimi_session is None:
            self._kimi_session=KimiSession(self.tool('hc'),self.settings.tools.get('kimi'),self.settings.antigravity_wait_seconds,self.root)
        return self._kimi_session
    def herdr(self,task='',provider=None,model=None,effort='medium'):
        if self.adapter:return self.adapter
        provider=provider or self.settings.agent_kind
        if provider=='kimi':return AntigravityAdapter(self.kimi_session())
        if provider in {'gemini','antigravity'}:return AntigravityAdapter(self.client_session())
        return CodexCoreAdapter(self.tool('hc'),self.tool('codex'),model or self.settings.agent_models.get(task,self.settings.model) or 'gpt-6.1-sol',effort)
    def manual_quota(self,provider):
        rows=self.store.rows('SELECT data FROM cache WHERE key=?',('agent-quota:'+provider,))
        return json.loads(rows[0]['data']) if rows else None
    def set_manual_quota(self,provider,value,minutes=15):
        if provider not in PROVIDERS:raise ValueError('Unknown agent')
        if value is None:self.store.execute('DELETE FROM cache WHERE key=?',('agent-quota:'+provider,))
        else:
            import math
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:raise ValueError('Remaining quota must be a percentage from 0 to 100')
            if isinstance(minutes,bool) or not isinstance(minutes,(int,float)) or not math.isfinite(minutes) or not 1<=minutes<=60:raise ValueError('Manual quota validity must be 1–60 minutes')
            now=time.time();data={'remaining_percent':value,'reported_at':now,'expires_at':now+minutes*60}
            self.store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',('agent-quota:'+provider,json.dumps(data),now))
        self.quota.latest.pop(provider,None);self.wake.set()
    def priorities_locked(self,e,n):
        return (e,n) in self.running or self.store.task(e,n)['status'] in ACTIVE_STATUSES
    def set_priorities(self,e,n,order):
        if n not in self.workflow(e) or n in GATES:raise ValueError('Choose an executable step; approval belongs to you')
        order=validate_order(order);config=self.store.config(e)
        if self.priorities_locked(e,n):raise PriorityLockedError('Stop the active step before changing its agent priorities')
        config['agent_priorities']={**config.get('agent_priorities',{}),n:order}
        self.store.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(config),e))
        self.store.log(e,n,'Agent priority saved for the next run: '+' → '.join(order));self.wake.set()
        return order
    async def select_provider(self,e,n,order):
        waiting=False
        while True:
            provider=await self.quota.choose(order,self.settings.tools.get('codex') or shutil.which('codex'))
            if provider:
                self.store.update(e,n,'Running');return provider
            self.store.update(e,n,'Waiting for quota')
            if not waiting:
                self.store.log(e,n,'No agent in this step priority has a verified remaining quota of at least 5%. No prompt sent. Refresh quota or enter a recent measured value in Agent balances; cancel the step to edit its priority.')
                waiting=True
            await asyncio.sleep(self.quota_poll_interval)
    def create(self,config):
        e=uuid.uuid4().hex; self.directory(e).mkdir(parents=True)
        self.store.execute('INSERT INTO episodes VALUES(?,?,?)',(e,json.dumps(config),time.time()))
        for n in workflow(config): self.store.execute('INSERT INTO tasks(episode,name) VALUES(?,?)',(e,n))
        self.store.log(e,'system','Episode created. Import visual references, then Start Production.'); return e
    async def start(self,e):
        config=self.store.config(e)
        if not config['permission']: raise ValueError('Audio download permission is required')
        if not list((self.directory(e)/'references').glob('*')): raise ValueError('Add at least one visual reference')
        # Starting does not hide missing dependencies behind successful mock results.
        for tool in ('ffmpeg','ffprobe','yt-dlp','unity'): self.tool(tool)
        if self.adapter:await self.adapter.check()
        if not self.settings.vision_enabled: raise ValueError('Enable image-capable agent support in Settings after verifying your model can inspect local images')
        self.store.log(e,'system','Production started')
        self.store.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)",('started:'+e,'true',time.time()))
        self.wake.set()
    def enabled(self,e): return bool(self.store.rows('SELECT key FROM cache WHERE key=?',('started:'+e,)))
    async def recover(self):
        for row in self.store.rows('SELECT id FROM episodes'):
            for name in self.workflow(row['id']):self.store.execute('INSERT OR IGNORE INTO tasks(episode,name) VALUES(?,?)',(row['id'],name))
        for row in self.store.rows("SELECT id FROM revisions WHERE status IN ('Planning','Waiting for quota','Waiting for CLI','Waiting for Permission','Applying')"):
            identity=self.revisions.get(row['id'])['data'].get('identity')
            if identity and identity.get('transport')=='herdr-core-codex-exec':
                try:
                    adapter=CodexCoreAdapter(self.tool('hc'),identity['executable'],identity.get('model','gpt-6.1-sol'),identity.get('effort','medium'))
                    await adapter.cancel(identity)
                except (OSError,RuntimeError,ValueError,KeyError):pass
            self.revisions.update(row['id'],'Failed',error='Revision analysis interrupted by application restart. No partial plan was applied; submit a new request.')
        # Never kill or trust a saved PID. Reconcile only the persisted Herdr identity.
        for t in self.store.rows("SELECT * FROM tasks WHERE status IN ('Running','Waiting for Client','Waiting for CLI','Waiting for Permission','Waiting for quota')"):
            e,n=t['episode'],t['name']; data=json.loads(t['data']); identity=data.get('identity')
            if identity and identity.get('owned') is False:
                message='Client task interrupted by restart. Its user-owned pane was left untouched; reconnect the Client-launched session and retry.'
            elif identity:
                try:
                    if identity.get('transport')=='herdr-core-codex-exec':
                        adapter=CodexCoreAdapter(self.tool('hc'),identity['executable'],identity.get('model','gpt-6.1-sol'),identity.get('effort','medium'))
                        await adapter.cancel(identity)
                        self.store.update(e,n,'Failed','Owned Codex task interrupted by restart; retry explicitly.');continue
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
                if not self.enabled(e) or e in self.revisions.applying: continue
                for n,deps in self.workflow(e).items():
                    key=(e,n); t=self.store.task(e,n)
                    if key in self.running or t['status']!='Pending': continue
                    if not all(self.store.task(e,d)['status'] in SUCCESS for d in deps): continue
                    if n=='recording_setup' and not self.store.config(e).get('recording_minutes'): continue
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
                for dependency in self.workflow(e)[n]: self.verify_artifacts(e,dependency)
                preparation=None
                if n in LOCAL_TASKS and n not in self.handlers:
                    c=self.store.config(e)
                    if n=='audio_engineer':
                        minutes,mode=extension_settings(c);c={**c,'duration_minutes':minutes,'audio_mode':mode}
                    preparation=await self.ask(e,n,'Prepare a brief execution/check plan for the local pipeline step '+n+'. The task field MUST equal '+json.dumps(n)+' exactly; it is an identifier, not a description. Episode parameters: '+json.dumps({key:c.get(key) for key in ('style','duration_minutes','recording_minutes','resolution','fps','audio_mode')})+'. The application runs the fixed local tools after your response. Do not execute tools, download, render, launch agents, alter files other than the required JSON, change settings or approve anything. Propose checks without claiming they already passed or that you inspected audio/images.',step_preparation_schema(n))
                    if preparation['result']['task']!=n:raise ValueError('Agent preparation references another step')
                data=await self.dispatch_with_budget(e,n)
                if preparation:
                    data={**(data or {}),'assistant_plan':preparation['result'],'artifacts':list(dict.fromkeys(preparation['artifacts']+(data or {}).get('artifacts',[])))}
                data=data or {}
                data['artifact_checksums']={name:checksum(contained(self.directory(e),name)) for name in data.get('artifacts',[]) if contained(self.directory(e),name).is_file()}
                t=self.store.task(e,n); self.store.update(e,n,'Completed',data={**t['data'],**(data or {})})
                self.store.log(e,n,'Task completed; artifacts validated')
                if n=='final_assembly' and t['data'].get('revision_id'):
                    self.revisions.update(t['data']['revision_id'],'Completed')
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
        paused={'Waiting for Client','Waiting for CLI','Waiting for Permission','Waiting for quota'}
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
    async def ask(self,e,n,prompt,schema,output_name=None):
        root=self.directory(e); result=f'{n}-{uuid.uuid4().hex}.json'
        def save(identity):
            snapshot={}
            for dependency in self.workflow(e)[n]:
                for path in self.store.task(e,dependency)['data'].get('artifacts',[]): snapshot[path]=checksum(contained(root,path))
            identity={**identity,'input_checksums':snapshot,'result_schema':schema.__name__}
            data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,'identity':identity})
        revision_agent=self.store.task(e,n)['data'].get('revision_agent')
        order=[revision_agent['provider']] if revision_agent else order_for(self.store.config(e),self.settings.agent_kind,n)
        routing=self.store.task(e,n)['data']
        self.store.update(e,n,data={**routing,'priority_snapshot':order,'selected_provider':None,'identity':None,'previous_identities':[*routing.get('previous_identities',[]),*([routing['identity']] if routing.get('identity') else [])][-20:]})
        provider=None if self.adapter else await self.select_provider(e,n,order)
        adapter=self.adapter or (self.herdr(n,provider,model=revision_agent.get('model'),effort=revision_agent.get('effort','medium')) if revision_agent else self.herdr(n,provider))
        if provider:
            routing=self.store.task(e,n)['data'];history=list(routing.get('agent_selections',[]))
            history.append({'provider':provider,'time':time.time(),'quota':dict(self.quota.latest.get(provider,{}))})
            self.store.update(e,n,data={**routing,'selected_provider':provider,'agent_selections':history})
            self.store.log(e,n,'Selected '+provider+' by step priority: '+('unknown Argon quota allowed by policy' if self.quota.latest.get(provider,{}).get('remaining_percent') is None and provider=='antigravity' else 'verified quota ≥5%'))
        def connect_callbacks(adapter):
            if isinstance(adapter,CodexCoreAdapter):
                adapter.on_state=lambda value:self.store.update(e,n,'Waiting for Permission' if value=='blocked' else 'Running')
                return
            if not isinstance(adapter,AntigravityAdapter):return
            def waiting():
                self.store.update(e,n,'Waiting for CLI' if isinstance(adapter.session,KimiSession) else 'Waiting for Client')
                self.store.log(e,n,'Waiting for the dedicated Kimi Herdr pane.' if isinstance(adapter.session,KimiSession) else 'Waiting for Antigravity Client → CLI → your confirmed idle Herdr pane. No direct Gemini/agy launch.')
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
        connect_callbacks(adapter)
        feedback=self.store.task(e,n)['data'].get('feedback','')
        if feedback:
            prompt+='\nUser requested changes (creative guidance only): '+feedback
            if n in {'metadata','music_brief','visual_reference'}:prompt+=' Read the existing '+n+'.json and preserve all fields not explicitly requested. This is a targeted edit, not a new draft.'
            if n=='unity_preview':prompt+=' Read the current scene_spec.json first and retain every supported value not changed by this request. Do not reset the camera, seat layout or palette unnecessarily.'
        operation=None
        try:
            full_prompt=REFERENCE_POLICY+episode_context(self.store.config(e))+'\n'+prompt+'\nRequired JSON schema: '+json.dumps(schema.model_json_schema())
            operation=asyncio.create_task(adapter.launch(root,full_prompt,result,save,**({'schema':schema.model_json_schema()} if isinstance(adapter,CodexCoreAdapter) else {})))
            while True:
                done,_=await asyncio.wait({operation},timeout=self.quota_poll_interval)
                if done:
                    data=await operation;break
                if not self.adapter and provider:
                    remaining=await self.quota.read(provider,self.settings.tools.get('codex') or shutil.which('codex'))
                    if eligible(provider,remaining):continue
                    # Do not send to a second agent until the first task has verifiably stopped.
                    if operation.done():data=await operation;break
                    identity=self.store.task(e,n)['data'].get('identity')
                    if identity and await adapter.cancel(identity) is not True:raise RuntimeError('Cannot verify active CLI stopped; no fallback prompt was sent. Inspect its pane and retry after stopping it.')
                    operation.cancel();await asyncio.gather(operation,return_exceptions=True)
                    self.store.log(e,n,'Active agent quota is below 5% or unknown. Its prompt was stopped; selecting the first eligible agent in this step priority.')
                    provider=await self.select_provider(e,n,order)
                    adapter=self.herdr(n,provider,model=revision_agent.get('model'),effort=revision_agent.get('effort','medium')) if revision_agent else self.herdr(n,provider)
                    connect_callbacks(adapter)
                    routing=self.store.task(e,n)['data'];history=list(routing.get('agent_selections',[]))
                    history.append({'provider':provider,'time':time.time(),'quota':dict(self.quota.latest.get(provider,{}))})
                    self.store.update(e,n,data={**routing,'selected_provider':provider,'agent_selections':history})
                    result=f'{n}-{uuid.uuid4().hex}.json'
                    operation=asyncio.create_task(adapter.launch(root,full_prompt,result,save,**({'schema':schema.model_json_schema()} if isinstance(adapter,CodexCoreAdapter) else {})))
            checked=schema.model_validate(data).model_dump()
            fields=self.store.task(e,n)['data'].get('revision_fields',[])
            old_path=root/('scene_spec.json' if issubclass(schema,SceneSpec) else n+'.json')
            if fields and old_path.is_file() and (issubclass(schema,SceneSpec) or n in {'metadata','music_brief','visual_reference'}):
                old=json.loads(old_path.read_text());allowed=set(fields)
                if issubclass(schema,SceneSpec):allowed.add('explanation')
                if n=='metadata' and 'titles' in allowed:allowed.add('recommended')
                for key,value in old.items():
                    if key in checked and key not in allowed:checked[key]=value
                checked=schema.model_validate(checked).model_dump()
            destination=contained(root,output_name or f'{n}.json');destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(checked,indent=2))
            return {'artifacts':[str(destination.relative_to(root))],'result':checked}
        finally:
            if operation and not operation.done():
                operation.cancel();await asyncio.gather(operation,return_exceptions=True)
            identity=self.store.task(e,n)['data'].get('identity')
            if identity:
                try:
                    text=await adapter.logs(identity); (root/f'{n}-agent.log').write_text(text)
                except Exception: pass
                await adapter.cancel(identity)
    async def dispatch(self,e,n):
        if n in self.handlers: return await self.handlers[n](e,n)
        if n in {'image_edit','visual_extend'}:return await self.presentation.dispatch(e,n)
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
            if c.get('channel_review_enabled'):return await self.channel_review.generate(e)
            result=await self.ask(e,n,'Read channel_titles.json, music_brief.json and visual_reference.json. Analyze title patterns and create 5 original titles, recommended title, description and hashtags as #tag, #tag. Do not copy source titles or make performance claims.',Metadata)
            originals=json.loads((root/'channel_titles.json').read_text())
            if any(t.casefold() in {s.casefold() for s in originals} for t in result['result']['titles']): raise ValueError('Generated title duplicates a channel reference')
            return result
        if n=='audio_engineer':
            data=self.verify_approval(e,'music_approval'); paths=[contained(root,p) for p in data['music']]
            minutes,mode=extension_settings(c)
            await process_audio(paths,root/'final.wav',minutes*60,mode,self.tool('ffmpeg'),self.tool('ffprobe'),gain_db=c.get('audio_gain_db',0),fade_seconds=c.get('audio_fade_seconds',0))
            return {'artifacts':['final.wav','final.report.json']}
        if n=='unity_blueprint':return await self.scene_planning.generate(e)
        if n=='unity_preview':
            blueprint=None
            if c.get('unity_planning_enabled'):
                from backend.models.schema import UnityBlueprint
                self.verify_artifacts(e,'unity_blueprint')
                blueprint=UnityBlueprint.model_validate_json((root/'unity_blueprint.json').read_text())
                if blueprint.scene_type=='unsupported':raise ValueError('Unity blueprint requires unsupported geometry: '+'; '.join(blueprint.limitations))
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
                instruction='Inspect the actual images in references/ and read visual_reference.json. '+CAPABILITIES+' Choose scene category from observed geometry, not style labels. Use the reference camera height, composition, light and palette. For custom_scene return custom_materials, custom_objects and custom_lights that implement the observed scene: meaningful geometry groups, repeated structural detail, believable proportions and materials, light distribution, environment colors and weather. Do not return a few placeholder cubes. The sky/ambient/fog colors must follow the reference. Use exterior-scale positions and appropriate camera height when observed. For interiors preserve appropriate camera bounds and include a figure only when observed/requested. Explain approximation limits honestly.'
                if c.get('unity_reference_image'):instruction+=' The authoritative reference is '+c['unity_reference_image']+'. Inspect its pixels and read the existing scene_spec.json; modify the existing scene design to match it, preserving compatible scene details. Original references are historical if they differ.'
                if blueprint:instruction+=' Read unity_blueprint.json and unity_blueprint.md in full. Implement their scene-building prompt and all fidelity checks. The scene_type MUST equal '+blueprint.scene_type+'. Do not substitute another scene category or ignore the prompt. Later scoped user feedback overrides only conflicting details.'
                spec=await self.ask(e,n,instruction,SceneDesign)
                if blueprint and spec['result']['scene_type']!=blueprint.scene_type:raise ValueError('Scene design changed the reference category; Unity was not started')
                (root/'scene_spec.json').write_text(json.dumps(spec['result'],indent=2))
                result=await Unity(self.tool('unity'),self.tool('ffmpeg'),self.tool('ffprobe')).render(root,c,True)
                paths=set(result['artifacts']+['scene_spec.json','visual_reference.json','references.json','preview-frames/frame-00000.png','preview-frames/complete.json'])
                if blueprint:paths.update(['unity_blueprint.json','unity_blueprint.md'])
                if c.get('unity_reference_image'):paths.add(c['unity_reference_image'])
                paths.update(json.loads((root/'references.json').read_text()))
                checkpoint={'artifacts':result['artifacts'],'checksums':{path:checksum(contained(root,path)) for path in paths}}
                data=self.store.task(e,n)['data']; self.store.update(e,n,data={**data,**result,'preview_checkpoint':checkpoint})
            if blueprint:
                from backend.models.schema import UnityFidelityReport
                qa_reference=('the selected edited image '+c['unity_reference_image']+' as the authoritative reference' if c.get('unity_reference_image') else 'every actual reference listed in references.json')
                qa=await self.ask(e,n,'Inspect the pixels of preview-frames/frame-00000.png and '+qa_reference+'. Read unity_blueprint.json. Compare the requested scene category and each fidelity check with what is actually visible. At least six concrete observations must cover architecture/objects, framing, proportions, surface detail, lighting and atmosphere. If an exterior became an interior (or any essential scene category changed), category_matches MUST be false. Describe missing detail and approximation limits honestly; do not claim photorealism or exact correspondence. Do not change the scene or files other than the required JSON.',UnityFidelityReport)
                if not qa['result']['category_matches']:raise ValueError('Unity preview does not match the reference scene category. Regenerate the detailed Unity prompt with the reported differences. '+qa['result']['summary'])
            else:
                qa=await self.ask(e,n,'Inspect preview-frames/frame-00000.png and the actual images in references/. Compare architecture, palette, framing and atmosphere. Describe discrepancies and suggestions truthfully, using the VisualBrief fields. Do not claim a match without inspecting both.',VisualBrief)
            return {'artifacts':result['artifacts']+qa['artifacts'],'qa':qa['result']}
        if n=='recording_setup':
            minutes=c.get('recording_minutes')
            if not minutes: raise ValueError('Enter recording duration in minutes before recording')
            data=await self.ask(e,n,'Prepare the Unity recording of the approved scene. Read scene_spec.json and unity_preview.json. Return the exact user duration '+str(minutes)+' minutes, fps '+str(c['fps'])+', resolution '+c['resolution']+'. camera must be approved_scene_camera. Explain the setup; do not change the scene, create agents or start recording yourself. The application performs the validated capture after this plan.',RecordingPlan)
            plan=data['result']
            if (plan['duration_minutes'],plan['fps'],plan['resolution'])!=(minutes,c['fps'],c['resolution']): raise ValueError('Agent recording plan changed user duration or output settings')
            return data
        if n=='visual_render':
            self.verify_approval(e,'visual_approval')
            return await Unity(self.tool('unity'),self.tool('ffmpeg'),self.tool('ffprobe')).render(root,c,False)
        if n=='final_assembly':
            self.verify_approval(e,'music_approval'); self.verify_approval(e,'visual_approval')
            if c.get('channel_review_enabled'):self.verify_approval(e,'metadata_approval')
            out=root/'output'; out.mkdir(exist_ok=True)
            if c.get('postproduction_enabled'):self.verify_approval(e,'image_approval')
            video=root/('extended-visual.mp4' if c.get('postproduction_enabled') else 'visual-recording.mp4' if c.get('recording_minutes') else 'visual-loop.mp4')
            await assemble(root/'final.wav',video,out/'final.mp4',c,self.tool('ffmpeg'),self.tool('ffprobe'))
            shutil.copy2(root/'metadata.json',out/'metadata.json')
            if c.get('output_directory'):
                revision_id=self.store.task(e,n)['data'].get('revision_id')
                suffix='-extended-'+uuid.uuid4().hex[:12] if c.get('postproduction_enabled') else '-r-'+revision_id[:8] if revision_id else ''
                destination=Path(c['output_directory']).expanduser().resolve()/('liminal-'+e+suffix)
                destination.mkdir(parents=True,exist_ok=False)
                shutil.copy2(out/'final.mp4',destination/'final.mp4'); shutil.copy2(out/'metadata.json',destination/'metadata.json')
            return {'artifacts':['output/final.mp4','output/metadata.json']}
        raise ValueError('Unknown task '+n)
    async def set_recording_duration(self,e,minutes):
        if not isinstance(minutes,(int,float)) or isinstance(minutes,bool) or not 0<minutes<=180:raise ValueError('Enter a duration above 0 and at most 180 minutes')
        config=self.store.config(e)
        affected={'recording_setup','visual_render','final_assembly'}
        affected.update({'visual_choice','image_edit','image_approval','visual_extend'} if config.get('postproduction_enabled') else {'audio_engineer'})
        if any(key[0]==e and (not config.get('postproduction_enabled') or key[1] in affected) for key in self.running):raise ValueError('Wait for active affected recording tasks before changing recording duration')
        version=Versions(self.store,self.root).archive(e,affected)
        if version:
            Versions(self.store,self.root).insert(version);self.store.db.commit()
        config['recording_minutes']=minutes
        if not config.get('postproduction_enabled'):config['duration_minutes']=minutes
        self.store.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(config),e))
        for name in affected:
            self.store.execute('INSERT OR IGNORE INTO tasks(episode,name) VALUES(?,?)',(e,name))
            self.store.update(e,name,'Pending',error='',data={})
        self.store.log(e,'recording_setup',f'User set Unity recording duration to {minutes} minutes; Kimi will prepare the approved camera capture.')
        self.wake.set()
    async def cancel(self,e,n):
        if n not in self.workflow(e): raise ValueError('Unknown task')
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
        session=self.kimi_session() if identity.get('agent')=='kimi' else self.client_session()
        terminal=await session.command('get',identity.get('pane',''),'--json')
        fp=session.fingerprint(terminal)
        if any(fp[k]!=identity.get(k if k!='address' else 'pane') for k in fp): raise ValueError('Original CLI process cannot be verified; inspect the saved result manually')
        if session.word(terminal) not in {'idle','done'}: raise ValueError('Wait for the original CLI turn to finish before recovering its result')
        if 'before_turn' in identity and terminal.get('turn',0)<=identity['before_turn']: raise ValueError('Original CLI turn has not completed')
        for dependency in self.workflow(e)[n]:
            if self.store.task(e,dependency)['status'] not in SUCCESS: raise ValueError('Complete dependencies before recovery')
            self.verify_artifacts(e,dependency)
        for filename,digest in identity.get('input_checksums',{}).items():
            if checksum(contained(root,filename))!=digest: raise ValueError('Task inputs changed since the prompt was sent')
        current_task=self.store.task(e,n)
        if current_task['status']!='Failed' or current_task['data'].get('identity')!=identity or (e,n) in self.running:
            raise ValueError('Task changed during recovery; reload its state')
        if self.store.config(e).get('channel_review_enabled'):return await self.channel_review.recover(e,path)
        checked=Metadata.model_validate_json(path.read_text()).model_dump()
        originals={s.casefold() for s in json.loads((root/'channel_titles.json').read_text())}
        if any(title.casefold() in originals for title in checked['titles']): raise ValueError('Generated title duplicates a channel reference')
        temp=root/('metadata-recovered-'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(checked,indent=2));temp.replace(root/'metadata.json')
        self.store.update(e,n,'Completed',error='',data={**task['data'],'result':checked,'artifacts':['metadata.json'],'artifact_checksums':{'metadata.json':checksum(root/'metadata.json')},'recovered_from':str(path.relative_to(root))})
        self.store.log(e,n,'Recovered late structured result after schema, original CLI and dependency validation. No new model prompt was sent.')
        self.wake.set();return {'recovered':True}
    async def retry(self,e,n):
        if n not in self.workflow(e): raise ValueError('Unknown task')
        if self.store.task(e,n)['status'] not in {'Failed','Cancelled'}: raise ValueError('Only failed/cancelled tasks can be retried')
        if any(self.store.task(e,d)['status'] not in SUCCESS for d in self.workflow(e)[n]): raise ValueError('Complete dependencies first')
        old=self.store.task(e,n)['data']
        preserved={key:old[key] for key in ('revision_id','revision_agent','revision_fields','feedback','source_image','channel_round_id') if key in old}
        if n=='unity_preview' and old.get('preview_checkpoint'):preserved['preview_checkpoint']=old['preview_checkpoint']
        self.store.update(e,n,'Pending',error='',data=preserved); self.wake.set()
    async def request_changes(self,e,n,reason):
        if n=='metadata_approval':return await self.channel_review.request_changes(e,reason)
        if n=='image_approval':return await self.presentation.change_image(e,reason)
        if n=='visual_choice':raise ValueError('Choose the source and duration in Extended release')
        if n not in GATES: raise ValueError('Changes require an approval gate')
        reason=reason.strip()
        if len(reason)<3 or len(reason)>8000: raise ValueError('Describe the requested changes in 3–8000 characters')
        # Invalidate all transitive downstream consumers before rerunning upstream work.
        source='music_brief' if n=='music_approval' else 'unity_blueprint' if self.store.config(e).get('unity_planning_enabled') else 'unity_preview'
        affected={source,n}; changed=True
        while changed:
            new={task for task,deps in self.workflow(e).items() if any(d in affected for d in deps)}-affected
            changed=bool(new); affected|=new
        for task in affected:
            if (e,task) in self.running:await self.cancel(e,task)
        version=Versions(self.store,self.root).archive(e,affected)
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            Versions(self.store,self.root).insert(version)
            for task in affected:
                old=self.store.task(e,task)['data'];state={key:old[key] for key in ('revision_id','revision_agent','revision_fields') if key in old}
                if task==source:
                    state['feedback']=reason;state.pop('revision_fields',None)
                self.store.db.execute("UPDATE tasks SET status='Pending',error='',data=?,started=NULL,finished=NULL WHERE episode=? AND name=?",(json.dumps(state),e,task))
            self.store.db.commit()
        except BaseException:self.store.db.rollback();raise
        self.store.log(e,n,'Requested changes: '+reason); self.wake.set()
    async def approve(self,e,n):
        if n=='metadata_approval':raise ValueError('Choose a title in Channel titles and hashtags, then approve it')
        if n=='image_approval':return self.presentation.approve_image(e)
        if n=='visual_choice':raise ValueError('Choose the source and duration in Extended release')
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
            if self.store.config(e).get('unity_planning_enabled'):names+=['unity_blueprint.json','unity_blueprint.md']
        data={'checksums':{name:checksum(contained(root,name)) for name in names}}
        if n=='music_approval': data['music']=[name for name in names if name.startswith('music/')]
        self.store.update(e,n,'Approved',data=data); self.store.log(e,n,'Approved with SHA-256 checksums'); self.wake.set()
    async def close(self):
        self.stopping=True
        await self.revisions.close()
        if self.scheduler: self.scheduler.cancel()
        tasks=list(self.running.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

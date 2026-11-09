"""Plan a bounded edit, archive the delivered output, and invalidate only dependencies."""
import asyncio,json,time,uuid
from backend.models.schema import RevisionPlan,SceneSpec,VisualBrief,MusicBrief,Metadata
from backend.orchestration.workflow import DAG,GATES
from backend.orchestration.priorities import ACTIVE_STATUSES
from backend.orchestration.versions import Versions
from backend.integrations.process import checksum,contained
from backend.integrations.codex_core import CodexCoreAdapter
from backend.agents.providers import REFERENCE_POLICY

SOURCES={'unity_scene':'unity_preview','visual_analysis':'visual_reference','recording':'recording_setup','music_brief':'music_brief','audio_processing':'audio_engineer','metadata':'metadata'}
ACTIVE={'Planning','Waiting for quota','Waiting for CLI','Waiting for Permission','Applying'}

def conversation(row):
    """Expose old unanswered questions too, without rewriting existing history."""
    messages=list(row['data'].get('messages',[]))
    if not messages:
        messages=[{'id':row['id']+'-request','role':'user','content':row['prompt'],'created':row['created']}]
        plan=row['data'].get('plan') or {}
        if plan.get('needs_clarification'):
            messages.append({'id':row['id']+'-legacy-question','role':'assistant','kind':'question','content':plan.get('clarification') or row.get('error',''),'created':row['created']})
    return messages

def impact(plan,requested_scope='auto',dag=None):
    dag=dag or DAG
    scopes={change['scope'] for change in plan['changes']}
    if requested_scope!='auto' and scopes!={requested_scope}:raise ValueError('The agent selected changes outside your chosen scope')
    patch={key:value for key,value in plan['config_updates'].items() if value is not None}
    for key in patch:
        required='recording' if key in {'resolution','fps','recording_minutes'} else 'audio_processing'
        if required not in scopes:raise ValueError('Configuration change has no matching requested scope: '+key)
    field_sets={'unity_scene':set(SceneSpec.model_fields),'visual_analysis':set(VisualBrief.model_fields),'metadata':set(Metadata.model_fields),'music_brief':set(MusicBrief.model_fields),'recording':set(),'audio_processing':set()}
    for change in plan['changes']:
        if set(change.get('allowed_fields',[]))-field_sets[change['scope']]:raise ValueError('Unsupported field constraint for '+change['scope'])
    roots={SOURCES[scope] for scope in scopes}
    if 'recording_minutes' in patch and 'visual_choice' not in dag:roots.add('audio_engineer')
    affected=set(roots)
    while True:
        extra={name for name,deps in dag.items() if set(deps)&affected}-affected
        if not extra:break
        affected|=extra
    return roots,affected,patch

class Revisions:
    def __init__(self,engine):self.engine=engine;self.jobs={};self.applying=set()
    def rows(self,e):
        output=self.engine.store.rows('SELECT * FROM revisions WHERE episode=? ORDER BY created DESC',(e,))
        for row in output:
            row['data']=json.loads(row['data']);row['data']['messages']=conversation(row)
        return output
    def get(self,revision):
        rows=self.engine.store.rows('SELECT * FROM revisions WHERE id=?',(revision,))
        if not rows:raise ValueError('Unknown revision')
        row=rows[0];row['data']=json.loads(row['data']);row['data']['messages']=conversation(row);return row
    def update(self,revision,status=None,data=None,error=None):
        row=self.get(revision)
        self.engine.store.execute('UPDATE revisions SET status=?,data=?,error=? WHERE id=?',(status or row['status'],json.dumps(data if data is not None else row['data']),row['error'] if error is None else error,revision))
    def assert_editable(self,e):
        if e in self.applying:raise ValueError('A revision is being applied; wait for the version snapshot to finish')
    def schedule(self,identifier):
        task=asyncio.create_task(self.run(identifier));self.jobs[identifier]=task
        def finished(done):
            if self.jobs.get(identifier) is done:self.jobs.pop(identifier,None)
        task.add_done_callback(finished)
    async def reply(self,e,identifier,request):
        self.assert_editable(e)
        row=self.get(identifier)
        if row['episode']!=e:raise ValueError('Revision belongs to another episode')
        if row['status']!='Needs clarification':raise ValueError('This revision is not waiting for an answer; refresh its conversation')
        previous=self.jobs.get(identifier)
        if previous:await asyncio.shield(previous)
        # Re-read after yielding: two clients must not answer the same question twice.
        row=self.get(identifier);messages=conversation(row)
        if row['status']!='Needs clarification' or not messages or messages[-1].get('kind')!='question' or messages[-1]['id']!=request.question_id:
            raise ValueError('This question has already been answered or changed; refresh its conversation')
        if any(other['id']!=identifier and other['status'] in ACTIVE for other in self.rows(e)):
            raise ValueError('Wait for the other revision analysis or cancel it first')
        root=self.engine.directory(e)
        if self.engine.store.task(e,'final_assembly')['status']!='Completed' or checksum(root/'output/final.mp4')!=row['data']['base_final_sha256']:
            raise ValueError('The final changed since this question. Submit a new revision against the current video.')
        if len(messages)>=65 or sum(len(item['content']) for item in messages)+len(request.answer)>128000:
            raise ValueError('This conversation is full. Start a new revision with a summary; this history will remain available.')
        messages.append({'id':uuid.uuid4().hex,'role':'user','content':request.answer,'created':time.time(),'reply_to':request.question_id})
        self.update(identifier,'Planning',data={**row['data'],'messages':messages,'identity':None},error='')
        self.schedule(identifier)
        self.engine.store.log(e,'revision','Clarification answer saved; continuing the same revision with its conversation history.')
        return identifier
    def create(self,e,request):
        engine=self.engine;engine.store.config(e);self.assert_editable(e)
        if any(row['status'] in ACTIVE for row in self.rows(e)):raise ValueError('Wait for the current revision analysis or cancel it first')
        final=engine.store.task(e,'final_assembly');root=engine.directory(e)
        if final['status']!='Completed' or not (root/'output/final.mp4').is_file():raise ValueError('Finish the current version before requesting a final-video revision; use Request Changes on an intermediate approval step')
        identifier=uuid.uuid4().hex
        model='gpt-6.1-sol' if request.provider=='codex' else None;effort='medium' if request.provider=='codex' else None
        data={'base_final_sha256':checksum(root/'output/final.mp4')}
        engine.store.execute('INSERT INTO revisions(id,episode,created,status,prompt,provider,model,effort,scope,data) VALUES(?,?,?,?,?,?,?,?,?,?)',(identifier,e,time.time(),'Planning',request.prompt.strip(),request.provider,model,effort,request.scope,json.dumps(data)))
        self.schedule(identifier)
        engine.store.log(e,'revision','Analyzing requested final-video changes with '+request.provider+' '+(model or '')+' '+(effort or ''))
        return identifier
    async def run(self,identifier):
        engine=self.engine;row=self.get(identifier);e=row['episode'];root=engine.directory(e);adapter=None;identity=None
        try:
            while True:
                selected=await engine.quota.choose([row['provider']],engine.settings.tools.get('codex'))
                if selected:break
                self.update(identifier,'Waiting for quota');await asyncio.sleep(engine.quota_poll_interval)
            self.update(identifier,'Planning')
            adapter=engine.herdr('revision',row['provider'],model=row['model'],effort=row['effort'] or 'medium')
            def state(value):self.update(identifier,'Waiting for Permission' if value in {'blocked','waiting_blocked'} else 'Planning')
            adapter.on_state=state
            if hasattr(adapter,'on_wait'):adapter.on_wait=lambda:self.update(identifier,'Waiting for CLI')
            if hasattr(adapter,'on_ready'):adapter.on_ready=lambda:self.update(identifier,'Planning')
            def save(value):
                nonlocal identity
                identity=value;data=self.get(identifier)['data'];self.update(identifier,data={**data,'identity':value})
            config=engine.store.config(e)
            prompt=(REFERENCE_POLICY+'\nClassify the user\'s requested corrections to a completed video. Return a minimal, bounded revision plan, not commands. Do not change files or publish anything. '
                    'Scopes: unity_scene changes geometry, fog, materials, camera and lighting through the existing scene parameters; visual_analysis re-analyzes the original images only if explicitly requested; '
                    'recording changes resolution/FPS/duration only; music_brief changes generated music instructions and requires music import/approval; audio_processing changes mix level/fades/mode; metadata changes titles/description/hashtags only. '
                    'Use allowed_fields for narrow edits: e.g. metadata description only must allow description only; changing titles also allows recommended. Unity fields use exact scene_spec.json keys: '+', '.join(SceneSpec.model_fields)+'. An empty list allows the whole chosen scope. Never reset independent scopes just because they were earlier in the pipeline. Scene changes alone do not require re-downloading, re-analyzing music or regenerating metadata. '
                    'Use config_updates only for explicitly requested supported settings; all other entries must be null. For unsupported or ambiguous requests set needs_clarification and explain; do not invent capability. '
                    'The Unity scene builder supports enclosed subway/corridor, seat layout, camera pose/FOV, fog density, tint, and inclusion of a stylized seated figure; it does not support arbitrary mesh/character reconstruction. '
                    'Read the entire conversation below and incorporate every clarification answer. Do not repeat an already answered question. You cannot extend the scene builder in this planning operation; user permission alone does not add unsupported rendering capabilities. Explain that limitation rather than asking permission for implementation you cannot perform. '
                    'Requested scope: '+row['scope']+'. Current output settings: '+json.dumps({key:config.get(key) for key in ('style','fps','resolution','recording_minutes','duration_minutes','audio_mode','audio_gain_db','audio_fade_seconds')})+
                    '\nOriginal user request: '+row['prompt']+'\nConversation (ordered user messages and agent questions): '+json.dumps(conversation(row),ensure_ascii=False)+'\nJSON schema: '+json.dumps(RevisionPlan.model_json_schema()))
            result='revision-plan-'+identifier+'-'+uuid.uuid4().hex+'.json'
            if isinstance(adapter,CodexCoreAdapter):value=await adapter.launch(root,prompt,result,save,schema=RevisionPlan.model_json_schema())
            else:value=await adapter.launch(root,prompt,result,save)
            plan=RevisionPlan.model_validate(value).model_dump()
            data=self.get(identifier)['data'];messages=list(data['messages'])
            messages.append({'id':uuid.uuid4().hex,'role':'assistant','kind':'question' if plan['needs_clarification'] else 'plan','content':plan['clarification'] if plan['needs_clarification'] else plan['explanation'],'created':time.time()})
            self.update(identifier,data={**data,'plan':plan,'messages':messages})
            if plan['needs_clarification']:
                self.update(identifier,'Needs clarification',error=plan['clarification']);return
            await self.apply(identifier,plan)
        except asyncio.CancelledError:
            self.update(identifier,'Cancelled',error='Revision analysis cancelled. No new revision was applied.');raise
        except Exception as exc:self.update(identifier,'Failed',error=str(exc) or type(exc).__name__)
        finally:
            if adapter and identity:await adapter.cancel(identity)
    async def apply(self,identifier,plan):
        engine=self.engine;store=engine.store;row=self.get(identifier);e=row['episode'];root=engine.directory(e)
        roots,affected,patch=impact(plan,row['scope'],engine.workflow(e));self.applying.add(e);self.update(identifier,'Applying')
        try:
            if store.task(e,'final_assembly')['status']!='Completed' or checksum(root/'output/final.mp4')!=row['data']['base_final_sha256']:raise ValueError('The current final changed during analysis. Submit the request again against the latest version.')
            # Claim the episode for the short snapshot/reset phase. Independent running tasks are untouched.
            for name in affected:
                if (e,name) in engine.running:await engine.cancel(e,name)
            snapshot=asyncio.create_task(asyncio.to_thread(Versions(store,engine.root).archive,e,affected,identifier))
            try:version=await asyncio.shield(snapshot)
            except asyncio.CancelledError:
                await snapshot
                raise
            config=store.config(e);config.update(patch)
            if 'recording_minutes' in patch and not config.get('postproduction_enabled'):config['duration_minutes']=patch['recording_minutes']
            context={'provider':row['provider'],'model':row['model'],'effort':row['effort'] or 'medium'}
            feedback={};fields={}
            for change in plan['changes']:
                name=SOURCES[change['scope']];feedback[name]=feedback.get(name,'')+'\n'+change['instruction']
                fields[name]=list(dict.fromkeys(fields.get(name,[])+change.get('allowed_fields',[])))
            messages=conversation(row)
            if any(message.get('reply_to') for message in messages):
                for name in feedback:feedback[name]+='\nClarification context (apply only this step-specific instruction and allowed fields): '+json.dumps(messages,ensure_ascii=False)
            data={**row['data'],'plan':plan,'affected':[name for name in engine.workflow(e) if name in affected],'roots':[name for name in engine.workflow(e) if name in roots],'previous_version':version['id'] if version else None}
            try:
                store.db.execute('BEGIN IMMEDIATE')
                Versions(store,engine.root).insert(version)
                store.db.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(config),e))
                for name in affected:
                    state={'revision_id':identifier,'revision_agent':context}
                    if name in feedback:state.update(feedback=feedback[name],revision_fields=fields.get(name,[]))
                    store.db.execute("UPDATE tasks SET status='Pending',error='',data=?,started=NULL,finished=NULL WHERE episode=? AND name=?",(json.dumps(state),e,name))
                store.db.execute('UPDATE revisions SET status=?,data=? WHERE id=?',('Applied',json.dumps(data),identifier))
                store.db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',('started:'+e,'true',time.time()));store.db.commit()
            except BaseException:store.db.rollback();raise
            store.log(e,'revision','Previous final preserved as superseded. Restarting only: '+', '.join(data['affected']));engine.wake.set()
        finally:self.applying.discard(e)
    async def cancel(self,e,identifier):
        row=self.get(identifier)
        if row['episode']!=e:raise ValueError('Revision belongs to another episode')
        if row['status']=='Applying':raise ValueError('Wait for the atomic snapshot/reset to finish')
        task=self.jobs.get(identifier)
        if task:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
    async def close(self):
        tasks=list(self.jobs.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

"""Source-verified channel titles, generated hashtags, and a human metadata gate."""
import asyncio,json,re,time,uuid
from backend.integrations.youtube import channel_videos
from backend.integrations.process import checksum,contained
from backend.models.schema import ChannelMetadataPlan,ChannelReviewRequest
from backend.orchestration.versions import Versions

class ChannelReview:
    def __init__(self,engine):self.engine=engine
    def rows(self,e):
        rows=self.engine.store.rows('SELECT * FROM metadata_rounds WHERE episode=? ORDER BY created DESC',(e,))
        for row in rows:row['request']=json.loads(row['request']);row['data']=json.loads(row['data'])
        return rows
    def state(self,e):
        task=self.engine.store.task(e,'metadata');current=task['data'].get('channel_round_id')
        return {'enabled':bool(self.engine.store.config(e).get('channel_review_enabled')),'current_round_id':current,'task_status':task['status'],'rounds':self.rows(e)}
    def row(self,e,identifier):
        for row in self.rows(e):
            if row['id']==identifier:return row
        raise ValueError('Unknown channel-search round')
    def update(self,identifier,status,data=None,error=''):
        if data is None:self.engine.store.execute('UPDATE metadata_rounds SET status=?,error=? WHERE id=?',(status,error,identifier))
        else:self.engine.store.execute('UPDATE metadata_rounds SET status=?,data=?,error=? WHERE id=?',(status,json.dumps(data),error,identifier))
    def archive(self,e):
        names={'metadata','metadata_approval','final_assembly'};existing={r['name'] for r in self.engine.store.rows('SELECT name FROM tasks WHERE episode=?',(e,))}
        return Versions(self.engine.store,self.engine.root).archive(e,names&existing)
    def assert_idle(self,e):
        self.engine.revisions.assert_editable(e)
        if any((e,n) in self.engine.running for n in ('metadata','final_assembly')):raise ValueError('Stop the active metadata/final task before changing the title search')
        if any(r['status'] in {'Planning','Applying','Waiting for quota','Waiting for CLI','Waiting for Permission'} for r in self.engine.revisions.rows(e)):raise ValueError('Finish or cancel the revision analysis first')
    def new_row(self,e,request):
        identifier=uuid.uuid4().hex
        self.engine.store.execute('INSERT INTO metadata_rounds(id,episode,created,request,status) VALUES(?,?,?,?,?)',(identifier,e,time.time(),json.dumps(request),'Pending'))
        return identifier
    async def begin(self,e,request):
        engine=self.engine;store=engine.store;config=store.config(e);self.assert_idle(e)
        for dependency in ('channel_reference','music_brief','visual_reference'):
            if store.task(e,dependency)['status']!='Completed':raise ValueError('Complete channel, music and visual analysis before searching titles')
        current=store.task(e,'metadata')['data'].get('channel_round_id')
        if current!=request.expected_round_id:raise ValueError('The title-search round changed. Refresh before continuing.')
        if request.action=='refine':
            if not current:raise ValueError('Find channel titles first')
            candidates=self.row(e,current)['data'].get('candidates',[])
            if request.video_id and request.video_id not in {c['video_id'] for c in candidates}:raise ValueError('Select a candidate from the current round')
        if len(self.rows(e))>=64:raise ValueError('This title-search history is full; previous rounds remain available')
        version=self.archive(e);identifier=uuid.uuid4().hex;config['channel_review_enabled']=True
        try:
            store.db.execute('BEGIN IMMEDIATE');Versions(store,engine.root).insert(version)
            store.db.execute('INSERT INTO metadata_rounds(id,episode,created,request,status) VALUES(?,?,?,?,?)',(identifier,e,time.time(),json.dumps(request.model_dump()),'Pending'))
            store.db.execute('INSERT OR IGNORE INTO tasks(episode,name) VALUES(?,?)',(e,'metadata_approval'))
            for name in ('metadata','metadata_approval','final_assembly'):
                data={'channel_round_id':identifier} if name=='metadata' else {}
                store.db.execute("UPDATE tasks SET status='Pending',data=?,error='',started=NULL,finished=NULL WHERE episode=? AND name=?",(json.dumps(data),e,name))
            store.db.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(config),e))
            store.db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',('started:'+e,'true',time.time()));store.db.commit()
        except BaseException:store.db.rollback();raise
        store.log(e,'metadata','Channel title search requested; only metadata and final assembly were reset.');engine.wake.set();return identifier
    async def request_changes(self,e,reason):
        current=self.state(e)['current_round_id']
        return await self.begin(e,ChannelReviewRequest(action='refine',feedback=reason,expected_round_id=current))
    async def generate(self,e):
        engine=self.engine;store=engine.store;root=engine.directory(e);config=store.config(e);task=store.task(e,'metadata');identifier=task['data'].get('channel_round_id')
        if not identifier:
            history=self.rows(e);previous=next((r for r in history if r['data'].get('candidates')),None)
            canonical=root/'metadata.json'
            if canonical.is_file() and task['data'].get('revision_fields'):
                saved=json.loads(canonical.read_text())
                previous=next((r for r in history if any(c['video_id']==saved.get('source_video_id') and c['title']==saved.get('recommended') for c in r['data'].get('candidates',[]))),previous)
            request={'action':'refine' if previous and task['data'].get('feedback') else 'search','feedback':task['data'].get('feedback',''),'video_id':None,'expected_round_id':previous['id'] if previous else None}
            identifier=self.new_row(e,request);store.update(e,'metadata',data={**task['data'],'channel_round_id':identifier})
        row=self.row(e,identifier);request=row['request'];self.update(identifier,'Searching')
        try:
            previous=self.row(e,request['expected_round_id']) if request.get('expected_round_id') else next((r for r in self.rows(e) if r['id']!=identifier and r['data'].get('candidates')),None)
            if request['action']=='refine' and previous:
                videos=[{'video_id':c['video_id'],'title':c['original_title'],'url':c['source_url']} for c in previous['data']['candidates'] if not request.get('video_id') or c['video_id']==request['video_id']]
            else:
                all_videos=await channel_videos(config['channel_url'],engine.tool('yt-dlp'),store,engine.settings.cache_hours,engine.settings.yt_dlp_use_chrome_cookies,engine.settings.yt_dlp_chrome_profile)
                seen={c['video_id'] for r in self.rows(e) if r['id']!=identifier for c in r['data'].get('candidates',[])}
                videos=[v for v in all_videos if v['video_id'] not in seen]
                context=config.get('style','')+' '+config.get('agent_guidance','')+' '+request.get('feedback','')
                for name in ('visual_reference.json','scene_spec.json','music_brief.json'):
                    path=root/name
                    if path.is_file():context+=' '+path.read_text()[:32000]
                words=set(re.findall(r'\w+',context.lower(),flags=re.UNICODE))
                videos.sort(key=lambda v:-len(words & set(re.findall(r'\w+',v['title'].lower()))));videos=videos[:150]
            if not videos:raise ValueError('No unseen channel titles remain. Choose an earlier candidate from history or refine one.')
            directory='channel-review/'+identifier;folder=contained(root,directory);folder.mkdir(parents=True,exist_ok=True)
            records=folder/'source-videos.json';records.write_text(json.dumps({'channel_url':config['channel_url'],'videos':videos},ensure_ascii=False,indent=2))
            history=[{'action':r['request'].get('action'),'feedback':r['request'].get('feedback','')} for r in reversed(self.rows(e))]
            prompt=('Read music_brief.json and visual_reference.json, and scene_spec.json / image-edit artifacts if available, to understand this episode atmosphere. Do not claim you watched or listened without actually doing so. The user explicitly requests quoting an existing short source title; the originality requirement applies to generated creative content, not this source-title selection. Use unique source IDs and displayed titles; return fewer than five if needed. Rank up to five suitable source videos from '+directory+'/source-videos.json. Every video_id must come from this file. '+
                    ('Return the EXACT original title, character for character; do not invent or rewrite any title.' if request['action']=='search' else 'The user explicitly requests a corrected/adapted title. Keep its source video_id and satisfy their correction; its original title will be shown separately.')+
                    ' Explain each atmosphere match. Generate relevant YouTube hashtags as ONE comma-space-separated line like #ambient, #darkambient, #coldcore; no whitespace inside each tag, no duplicates. These are recommendations, not claims that tags were extracted from the source or guarantee performance. Include a suitable description. Later user requirements override conflicting earlier ones; retain unaffected requirements. Conversation requirements, oldest first: '+json.dumps(history,ensure_ascii=False))
            result=await engine.ask(e,'metadata',prompt,ChannelMetadataPlan,output_name=directory+'/plan-'+uuid.uuid4().hex+'.json')
            return self.finish(e,identifier,request,previous,task,videos,result,records,folder)
        except asyncio.CancelledError:self.update(identifier,'Cancelled',error='Search cancelled; previous rounds remain available.');raise
        except Exception as exc:self.update(identifier,'Failed',error=str(exc));raise
    def finish(self,e,identifier,request,previous,task,videos,result,records,folder):
        root=self.engine.directory(e);config=self.engine.store.config(e)
        plan=result['result'];lookup={v['video_id']:v for v in videos};candidates=[]
        fields=task['data'].get('revision_fields',[])
        if fields and previous and not {'titles','recommended'}&set(fields):
            candidates=previous['data']['candidates']
        else:
            for candidate in plan['candidates']:
                source=lookup.get(candidate['video_id'])
                if not source:raise ValueError('Agent selected a video outside the verified channel candidate set')
                if request['action']=='search' and candidate['title']!=source['title']:raise ValueError('Search must return an existing channel title exactly; use Refine to adapt it')
                candidates.append({**candidate,'original_title':source['title'],'source_url':source['url'],'adapted':candidate['title']!=source['title']})
        data={'candidates':candidates,'hashtags':plan['hashtags'],'description':plan['description'],'channel_url':config['channel_url'],'files':[str(records.relative_to(root)),*result['artifacts']]}
        canonical=root/'metadata.json'
        if canonical.is_file() and 'description' not in fields:
            existing=json.loads(canonical.read_text())
            if isinstance(existing.get('description'),str):data['description']=existing['description']
        if fields and previous:
            for field in ('hashtags','description'):
                if field not in fields:data[field]=previous['data'][field]
        candidate_file=folder/'candidates.json';candidate_file.write_text(json.dumps(data,ensure_ascii=False,indent=2));data['files'].append(str(candidate_file.relative_to(root)))
        selected=previous['data'].get('selected_video_id') if fields and previous and not {'titles','recommended'}&set(fields) else None
        if selected not in {c['video_id'] for c in candidates}:selected=candidates[0]['video_id']
        if fields:data['selected_video_id']=selected
        data['file_checksums']={name:checksum(contained(root,name)) for name in data['files']}
        self.write_metadata(e,data,selected);self.update(identifier,'Ready',data)
        return {'artifacts':['metadata.json',*data['files']],'result':json.loads((root/'metadata.json').read_text()),'channel_round_id':identifier}
    async def recover(self,e,path):
        engine=self.engine;store=engine.store;task=store.task(e,'metadata');identifier=task['data'].get('channel_round_id')
        if not identifier:raise ValueError('No channel review round belongs to this saved result')
        row=self.row(e,identifier);request=row['request'];root=engine.directory(e);folder=contained(root,'channel-review/'+identifier);records=folder/'source-videos.json'
        videos=json.loads(records.read_text())['videos'];config=store.config(e)
        verified=await channel_videos(config['channel_url'],engine.tool('yt-dlp'),store,engine.settings.cache_hours,engine.settings.yt_dlp_use_chrome_cookies,engine.settings.yt_dlp_chrome_profile)
        lookup={v['video_id']:v for v in verified}
        if not videos or any(lookup.get(v['video_id'])!=v for v in videos):raise ValueError('Saved source pool no longer matches verified channel videos')
        current=store.task(e,'metadata')
        if current['status']!='Failed' or current['data']!=task['data'] or (e,'metadata') in engine.running:raise ValueError('Task changed during recovery; reload its state')
        plan=ChannelMetadataPlan.model_validate_json(path.read_text()).model_dump()
        previous=self.row(e,request['expected_round_id']) if request.get('expected_round_id') else None
        result={'result':plan,'artifacts':[str(path.relative_to(root))]}
        output=self.finish(e,identifier,request,previous,task,videos,result,records,folder)
        store.update(e,'metadata','Completed',error='',data={**task['data'],**output,'artifact_checksums':{p:checksum(contained(root,p)) for p in output['artifacts']},'recovered_from':str(path.relative_to(root))})
        store.log(e,'metadata','Recovered saved channel result after original CLI, schema, input and channel-source validation. No model prompt sent.');engine.wake.set();return {'recovered':True}
    def write_metadata(self,e,data,video_id):
        selected=next(c for c in data['candidates'] if c['video_id']==video_id)
        metadata={'titles':[c['title'] for c in data['candidates']],'recommended':selected['title'],'description':data['description'],'hashtags':data['hashtags'],'source_video_id':video_id,'source_title':selected['original_title'],'source_url':selected['source_url'],'title_adapted':selected['adapted']}
        root=self.engine.directory(e);temp=root/('metadata-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(metadata,ensure_ascii=False,indent=2));temp.replace(root/'metadata.json');return metadata
    def approve(self,e,request):
        engine=self.engine;store=engine.store;self.assert_idle(e);task=store.task(e,'metadata');current=task['data'].get('channel_round_id')
        if current!=request.expected_round_id:raise ValueError('The title-search round changed. Refresh before approving.')
        source=self.row(e,request.round_id)
        if source['status'] not in {'Ready','Approved'}:raise ValueError('This search round has no validated candidates')
        if request.video_id not in {c['video_id'] for c in source['data']['candidates']}:raise ValueError('Choose a title from this round')
        if not store.config(e).get('channel_review_enabled'):raise ValueError('Enable channel title review first')
        for name,digest in source['data'].get('file_checksums',{}).items():
            if checksum(contained(engine.directory(e),name))!=digest:raise ValueError('Channel search source artifact changed; repeat the search')
        gate=store.task(e,'metadata_approval')
        if gate['status']=='Approved' and gate['data'].get('round_id')==source['id'] and gate['data'].get('video_id')==request.video_id:
            engine.verify_approval(e,'metadata_approval');return task['data']['result']
        version=self.archive(e);metadata=self.write_metadata(e,source['data'],request.video_id);root=engine.directory(e)
        paths=['metadata.json',*source['data']['files']];checks={p:checksum(contained(root,p)) for p in paths}
        try:
            store.db.execute('BEGIN IMMEDIATE');Versions(store,engine.root).insert(version)
            state={**task['data'],'channel_round_id':source['id'],'artifacts':paths,'artifact_checksums':checks,'result':metadata}
            store.db.execute("UPDATE tasks SET status='Completed',error='',data=?,finished=? WHERE episode=? AND name='metadata'",(json.dumps(state),time.time(),e))
            approval={'round_id':source['id'],'video_id':request.video_id,'title':metadata['recommended'],'checksums':{'metadata.json':checks['metadata.json']},'artifacts':['metadata.json'],'artifact_checksums':{'metadata.json':checks['metadata.json']}}
            store.db.execute("UPDATE tasks SET status='Approved',error='',data=?,finished=? WHERE episode=? AND name='metadata_approval'",(json.dumps(approval),time.time(),e))
            store.db.execute("UPDATE tasks SET status='Pending',error='',data=?,started=NULL,finished=NULL WHERE episode=? AND name='final_assembly'",(json.dumps({k:v for k,v in store.task(e,'final_assembly')['data'].items() if k in ('revision_id','revision_agent')}),e))
            data={**source['data'],'selected_video_id':request.video_id};store.db.execute("UPDATE metadata_rounds SET status='Approved',data=? WHERE id=?",(json.dumps(data),source['id']));store.db.commit()
        except BaseException:store.db.rollback();raise
        store.log(e,'metadata_approval','User approved title: '+metadata['recommended']);engine.wake.set();return metadata

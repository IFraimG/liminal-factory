"""User-selected post-production. Capture minutes and release minutes are independent."""
import json,time,uuid
from pathlib import Path
from PIL import Image,ImageStat
from backend.integrations.process import checksum,contained,run
from backend.media.ffmpeg import probe
from backend.media.extend import extend_visual
from backend.models.schema import ImageEditResult
from backend.audio.settings import extension_settings
from backend.orchestration.workflow import EXTENDED_DAG
from backend.orchestration.versions import Versions

class Presentation:
    def __init__(self,engine):self.engine=engine
    def state(self,e):
        rows=self.engine.store.rows('SELECT data FROM cache WHERE key=?',('presentation:'+e,))
        data=json.loads(rows[0]['data']) if rows else {}
        return {**data,'enabled':bool(self.engine.store.config(e).get('postproduction_enabled'))}
    def save(self,e,**values):
        data={**self.state(e),**values};self.engine.store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',('presentation:'+e,json.dumps(data),time.time()))
    def archive(self,e,names):
        existing={row['name'] for row in self.engine.store.rows('SELECT name FROM tasks WHERE episode=?',(e,))}
        return Versions(self.engine.store,self.engine.root).archive(e,names&existing)
    async def choose(self,e,request):
        engine=self.engine;store=engine.store;root=engine.directory(e);config=store.config(e)
        if store.task(e,'visual_render')['status']!='Completed':raise ValueError('Finish the Unity recording first')
        names={'visual_choice','image_edit','image_approval','visual_extend','final_assembly'}
        audio_changed=extension_settings(config)!=(request.minutes,'Variational Extend')
        if audio_changed:names.add('audio_engineer')
        if any((e,n) in engine.running for n in names):raise ValueError('Stop the affected post-production tasks before changing the release')
        if any(r['status'] in {'Planning','Waiting for quota','Waiting for CLI','Waiting for Permission','Applying'} for r in engine.revisions.rows(e)):raise ValueError('Finish or cancel the revision analysis first')
        engine.revisions.assert_editable(e);engine.revisions.applying.add(e)
        try:
            engine.verify_artifacts(e,'visual_render')
            clip='visual-recording.mp4' if config.get('recording_minutes') else 'visual-loop.mp4';path=contained(root,clip)
            if not path.is_file():raise ValueError('The Unity recording is missing')
            source=None
            if request.mode=='image':
                report=await probe(path,engine.tool('ffprobe'));seconds=float(report['format']['duration'])
                source='image-edits/'+uuid.uuid4().hex+'/unity-source.png';dest=contained(root,source);dest.parent.mkdir(parents=True)
                await run([engine.tool('ffmpeg'),'-y','-v','error','-ss',str(min(1,seconds/2)),'-i',str(path),'-frames:v','1',str(dest)],timeout=60)
            version=self.archive(e,names)
            config.update(postproduction_enabled=True,presentation_mode=request.mode,presentation_minutes=request.minutes,duration_minutes=request.minutes,audio_mode='Variational Extend')
            checks={clip:checksum(path)}
            if source:checks[source]=checksum(root/source)
            try:
                store.db.execute('BEGIN IMMEDIATE');Versions(store,engine.root).insert(version)
                for n in EXTENDED_DAG:store.db.execute('INSERT OR IGNORE INTO tasks(episode,name) VALUES(?,?)',(e,n))
                for n in names:store.db.execute("UPDATE tasks SET status='Pending',data='{}',error='',started=NULL,finished=NULL WHERE episode=? AND name=?",(e,n))
                store.db.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(config),e))
                choice={'checksums':checks,'clip':clip,'source_image':source,'mode':request.mode,'minutes':request.minutes}
                store.db.execute("UPDATE tasks SET status='Approved',data=?,finished=? WHERE episode=? AND name='visual_choice'",(json.dumps(choice),time.time(),e))
                edit={'feedback':request.prompt,'source_image':source}
                store.db.execute("UPDATE tasks SET data=? WHERE episode=? AND name='image_edit'",(json.dumps(edit),e))
                if request.mode=='video':
                    store.db.execute("UPDATE tasks SET status='Completed',data=?,finished=? WHERE episode=? AND name='image_edit'",(json.dumps({'skipped':'User selected the Unity video'}),time.time(),e))
                    store.db.execute("UPDATE tasks SET status='Approved',data=?,finished=? WHERE episode=? AND name='image_approval'",(json.dumps({'checksums':checks,'clip':clip,'mode':'video'}),time.time(),e))
                store.db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',('started:'+e,'true',time.time()));store.db.commit()
            except BaseException:store.db.rollback();raise
            self.save(e,mode=request.mode,minutes=request.minutes)
            store.log(e,'visual_choice',f'User selected {request.mode}; release {request.minutes} minutes. Unity capture duration unchanged.');engine.wake.set()
        finally:engine.revisions.applying.discard(e)
    async def change_image(self,e,prompt):
        engine=self.engine;store=engine.store;prompt=prompt.strip()
        if not 3<=len(prompt)<=8000:raise ValueError('Describe the image edit in 3–8000 characters')
        if store.config(e).get('presentation_mode')!='image':raise ValueError('Select the image path first')
        names={'image_edit','image_approval','visual_extend','final_assembly'}
        if any((e,n) in engine.running for n in names):raise ValueError('Stop the active image/release task before requesting another edit')
        old=store.task(e,'image_edit')['data'];source=old.get('image') or old.get('source_image')
        if not source or not contained(engine.directory(e),source).is_file():raise ValueError('No saved image to edit')
        version=self.archive(e,names)
        try:
            store.db.execute('BEGIN IMMEDIATE');Versions(store,engine.root).insert(version)
            for n in names:
                data={'source_image':source,'feedback':prompt} if n=='image_edit' else {}
                store.db.execute("UPDATE tasks SET status='Pending',data=?,error='',started=NULL,finished=NULL WHERE episode=? AND name=?",(json.dumps(data),e,n))
            store.db.commit()
        except BaseException:store.db.rollback();raise
        store.log(e,'image_edit','Image changes requested: '+prompt);engine.wake.set()
    def approve_image(self,e):
        engine=self.engine;task=engine.store.task(e,'image_approval')
        if task['status']!='Waiting for Approval':raise ValueError('The image is not awaiting approval')
        engine.verify_artifacts(e,'image_edit');image=engine.store.task(e,'image_edit')['data'].get('image')
        if not image:raise ValueError('No generated image is ready')
        engine.store.update(e,'image_approval','Approved',data={'image':image,'mode':'image','checksums':{image:checksum(contained(engine.directory(e),image))}});engine.wake.set()
    async def dispatch(self,e,n):
        engine=self.engine;root=engine.directory(e);config=engine.store.config(e)
        if n=='image_edit':
            choice=engine.verify_approval(e,'visual_choice');data=engine.store.task(e,n)['data'];source=data.get('source_image') or choice['source_image']
            original=contained(root,source);before=checksum(original)
            output='image-edits/'+uuid.uuid4().hex+'/edited.png';contained(root,output).parent.mkdir(parents=True)
            dimensions=config.get('image_resolution')
            size_instruction=(' Export the image at exactly '+dimensions+' pixels. Do not silently substitute another size.') if dimensions else ''
            prompt=('Use your actual image generation/editing tool to edit '+source+' using these original reference images: references/. Save the generated pixels as '+output+'.'+size_instruction+' Preserve composition and change only what the user requests. Do not replace generation with a copied image, a blank image, or a text-only description. If your current model/tools cannot generate and save an image, fail explicitly. Do not run arbitrary code, start agents, download unlicensed assets, or change the scene/project. Return the exact image_path and a truthful description. User edit: '+data.get('feedback',''))
            result=await engine.ask(e,n,prompt,ImageEditResult)
            if result['result']['image_path']!=output:raise ValueError('Agent returned an unexpected image destination')
            path=contained(root,output)
            if not path.is_file() or path.stat().st_size>70*1024*1024:raise ValueError('No bounded generated image was saved; inspect the Argon pane for missing image tools')
            if checksum(original)!=before:raise ValueError('The agent changed the input image')
            with Image.open(path) as image:
                image.load()
                if image.format!='PNG' or min(image.size)<256:raise ValueError('Expected a generated PNG of at least 256 pixels per side')
                if dimensions and image.size!=tuple(map(int,dimensions.split('x'))):raise ValueError('Generated image resolution must be '+dimensions+'; got '+str(image.size))
                small=image.convert('RGB').resize((128,128));pixels=small.tobytes()
                if max(ImageStat.Stat(small).stddev)<2:raise ValueError('Generated image appears blank')
            with Image.open(original) as image:
                if image.convert('RGB').resize((128,128)).tobytes()==pixels:raise ValueError('The agent returned the unchanged source image')
            state=self.state(e);history=state.get('image_history',[])
            history.append({'image':output,'source':source,'prompt':data.get('feedback',''),'description':result['result']['description'],'created':time.time()});self.save(e,image_history=history)
            return {**result,'image':output,'source_image':source,'artifacts':result['artifacts']+[output]}
        approval=engine.verify_approval(e,'image_approval');choice=engine.verify_approval(e,'visual_choice')
        source=approval.get('image') if config['presentation_mode']=='image' else choice['clip']
        return await extend_visual(contained(root,source),root/'extended-visual.mp4',config,engine.tool('ffmpeg'),engine.tool('ffprobe'))

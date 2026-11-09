"""Immutable delivered-output snapshots. Copies are published only after validation."""
import json,uuid,time,shutil
from pathlib import Path
from backend.integrations.process import contained,checksum

class Versions:
    def __init__(self,store,root):self.store=store;self.root=Path(root)
    def list(self,e):
        output=[]
        for row in self.store.rows('SELECT id,episode,created,status,revision_id,video,manifest FROM versions WHERE episode=? ORDER BY created DESC',(e,)):
            manifest=json.loads(row.pop('manifest'));output.append({**row,'integrity_warnings':manifest.get('integrity_warnings',[]),'manifest_path':'versions/'+row['id']+'/manifest.json'})
        return output
    def archive(self,e,affected,revision_id=None):
        root=contained(self.root,e);final=self.store.task(e,'final_assembly')
        if final['status']!='Completed':return None
        final_paths=final['data'].get('artifacts',[])
        if not final_paths and not (root/'output/final.mp4').exists():return None
        if 'output/final.mp4' not in final_paths:raise ValueError('Completed final has no video artifact')
        for name,digest in final['data'].get('artifact_checksums',{}).items():
            if checksum(contained(root,name))!=digest:raise ValueError('Final output changed externally; cannot archive it as the completed version')
        version=uuid.uuid4().hex;folder=root/'versions'/version;files=folder/'files';files.mkdir(parents=True)
        tasks={name:self.store.task(e,name) for name in affected};names=set(final_paths)
        for task in tasks.values():names.update(task['data'].get('artifacts',[]))
        if 'unity_preview' in affected:
            names.update(name for name in ('scene_spec.json','visual_reference.json','references.json','unity-project/Assets/Editor/LiminalScene.cs') if (root/name).is_file())
        archived={};warnings=[]
        try:
            for name in sorted(names):
                source=contained(root,name)
                if not source.is_file():warnings.append(name+': missing at archival');continue
                destination=contained(files,name);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
                digest=checksum(destination)
                if digest!=checksum(source):raise ValueError('Artifact changed while archiving: '+name)
                archived[name]={'path':str(destination.relative_to(root)),'sha256':digest,'size':destination.stat().st_size}
                for task in tasks.values():
                    expected=task['data'].get('artifact_checksums',{}).get(name)
                    if expected and expected!=digest:warnings.append(name+': differs from an older task checksum')
            manifest={'files':archived,'tasks':tasks,'config':self.store.config(e),'integrity_warnings':list(dict.fromkeys(warnings))}
            (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
            if 'output/final.mp4' not in archived:raise ValueError('Could not archive the final video')
            return {'id':version,'episode':e,'created':final['finished'] or time.time(),'revision_id':revision_id,'video':archived['output/final.mp4']['path'],'manifest':manifest}
        except BaseException:
            shutil.rmtree(folder,ignore_errors=True);raise
    def insert(self,version):
        if version:self.store.db.execute('INSERT INTO versions(id,episode,created,status,revision_id,video,manifest) VALUES(?,?,?,?,?,?,?)',(version['id'],version['episode'],version['created'],'superseded',version['revision_id'],version['video'],json.dumps(version['manifest'])))

import os
from pathlib import Path
os.environ['LIMINAL_DATA']=str(Path(__file__).resolve().parents[1]/'work/test-api')
os.environ['LIMINAL_TOKEN']='unit-test-token'
from fastapi.testclient import TestClient
import backend.main as main

def test_auth_creation_persistence_and_errors(tmp_path,monkeypatch):
    from backend.storage.db import Store
    from backend.orchestration.engine import Engine
    from backend.models.schema import Settings
    store=Store(tmp_path/'db');s=Settings(working_directory=str(tmp_path/'episodes'))
    engine=Engine(store,s.working_directory,s)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'engine',engine)
    with TestClient(main.app) as client:
        assert client.get('/episodes').status_code==401
        client.headers['Authorization']='Bearer unit-test-token'
        response=client.post('/episodes',json={'name':'API test','audio_url':'https://youtu.be/dQw4w9WgXcQ','channel_url':'https://youtube.com/@ambient'})
        assert response.status_code==200
        eid=response.json()['id'];assert client.get('/episodes/'+eid).json()['config']['name']=='API test'
        assert client.post('/episodes/'+eid+'/start').status_code==400
        assert client.get('/episodes/'+eid+'/file/missing.mp4').status_code==404
        assert client.post('/episodes/'+eid+'/tasks/unknown/retry').status_code==400
        assert client.post('/episodes',json={'name':'bad','audio_url':'https://evil.com','channel_url':'https://youtube.com/@ambient'}).status_code==422
        assert len(client.get('/episodes').json())==1

def test_revision_reply_api_resumes_existing_question_and_preserves_history(tmp_path,monkeypatch):
    import json
    from backend.storage.db import Store
    from backend.orchestration.engine import Engine
    from backend.models.schema import Settings,RevisionInput
    from backend.integrations.process import checksum
    from backend.orchestration.revisions import conversation
    store=Store(tmp_path/'db');s=Settings(working_directory=str(tmp_path/'episodes'));engine=Engine(store,s.working_directory,s)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'engine',engine)
    async def unavailable(*args):return None
    monkeypatch.setattr(engine.quota,'choose',unavailable)
    eid=engine.create({'name':'Reply API test'});root=engine.directory(eid);(root/'output').mkdir();(root/'output/final.mp4').write_bytes(b'current final')
    store.update(eid,'final_assembly','Completed')
    data={'base_final_sha256':checksum(root/'output/final.mp4'),'plan':{'needs_clarification':True,'clarification':'Keep the current camera?','explanation':'Need a camera choice'}}
    store.execute('INSERT INTO revisions(id,episode,created,status,prompt,provider,model,effort,scope,data,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('r1',eid,100,'Needs clarification','Improve the scene','codex','gpt-6.1-sol','medium','auto',json.dumps(data),'Keep the current camera?'))
    with TestClient(main.app) as client:
        url=f'/episodes/{eid}/revisions/r1/reply'
        assert client.post(url,json={'question_id':'r1-legacy-question','answer':'Да'}).status_code==401
        client.headers['Authorization']='Bearer unit-test-token'
        detail=client.get('/episodes/'+eid).json();messages=detail['revisions'][0]['data']['messages']
        assert len(messages)==2 and messages[-1]['content']=='Keep the current camera?'
        assert client.post(url,json={'question_id':messages[-1]['id'],'answer':'   '}).status_code==422
        assert client.post(url,json={'question_id':'stale-question','answer':'Да'}).status_code==400
        assert client.post(url,json={'question_id':messages[-1]['id'],'answer':'Да'}).status_code==200
        assert client.post(url,json={'question_id':messages[-1]['id'],'answer':'Нет'}).status_code==400
        result=client.get('/episodes/'+eid).json()
        assert result['final_current'] is True and len(result['revisions'])==1
        assert result['revisions'][0]['data']['messages'][-1]['content']=='Да'

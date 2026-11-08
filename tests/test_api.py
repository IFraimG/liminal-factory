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

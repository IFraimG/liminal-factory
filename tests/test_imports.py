import os,base64,io
from pathlib import Path
os.environ['LIMINAL_DATA']=str(Path(__file__).resolve().parents[1]/'work/test-api')
os.environ['LIMINAL_TOKEN']='unit-test-token'
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import numpy as np
import soundfile as sf
import backend.main as main
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.models.schema import Settings

@pytest.fixture
def client(tmp_path,monkeypatch):
    store=Store(tmp_path/'db');s=Settings(working_directory=str(tmp_path/'episodes'))
    engine=Engine(store,s.working_directory,s)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'engine',engine)
    with TestClient(main.app) as c:
        c.headers['Authorization']='Bearer unit-test-token'
        yield c,store,engine

def test_reference_content_order_and_media_range(client):
    c,store,engine=client
    e=c.post('/episodes',json={'name':'Imports','audio_url':'https://youtu.be/dQw4w9WgXcQ','channel_url':'https://youtube.com/@ambient'}).json()['id']
    blob=io.BytesIO();Image.new('RGB',(32,32),'gray').save(blob,'PNG')
    data={'name':'../../test.png','base64':base64.b64encode(blob.getvalue()).decode()}
    path=c.post(f'/episodes/{e}/imports/references',json=data).json()['name']
    assert path.startswith('references/') and '..' not in path
    assert c.get(f'/episodes/{e}/file/{path}',headers={'Range':'bytes=0-9'}).status_code==206
    data['base64']=base64.b64encode(b'fake pixels').decode()
    response=c.post(f'/episodes/{e}/imports/references',json=data)
    assert response.status_code==400
    assert c.get('/episodes/'+e).json()['references']==[path]
    assert c.put(f'/episodes/{e}/references',json={'names':['../../escape']}).status_code==400
    assert c.put(f'/episodes/{e}/references',json={'names':[]}).status_code==200
    assert not (engine.directory(e)/path).exists()

def test_music_import_approval_and_locked_mutation(client):
    c,store,engine=client
    e=c.post('/episodes',json={'name':'Music','audio_url':'https://youtu.be/dQw4w9WgXcQ','channel_url':'https://youtube.com/@ambient'}).json()['id']
    root=engine.directory(e);(root/'music_brief.json').write_text('{}')
    blob=io.BytesIO();sf.write(blob,np.sin(np.arange(48000)*2*np.pi*220/48000)*.1,48000,format='WAV')
    data={'name':'music.wav','base64':base64.b64encode(blob.getvalue()).decode()}
    name=c.post(f'/episodes/{e}/imports/music',json=data).json()['name']
    store.update(e,'music_approval','Waiting for Approval')
    assert c.post(f'/episodes/{e}/tasks/music_approval/approve').status_code==200
    assert c.post(f'/episodes/{e}/imports/music',json=data).status_code==400
    assert c.delete(f'/episodes/{e}/music/{Path(name).name}').status_code==400
    # Workflow was not enabled; approval alone cannot secretly start unrelated downloads.
    assert not engine.enabled(e)

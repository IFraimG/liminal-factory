import os,sys
from pathlib import Path
os.environ.setdefault('LIMINAL_DATA',str(Path(__file__).resolve().parents[1]/'work/test-api'))
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
import backend.main as main
import backend.audio.reference as reference
from backend.models.schema import Settings
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.integrations.download import chrome_cookie_args,redact_download_output
from backend.integrations.process import run

@pytest.fixture
def client(tmp_path,monkeypatch):
    store=Store(tmp_path/'db');settings=Settings(working_directory=str(tmp_path/'episodes'))
    engine=Engine(store,settings.working_directory,settings)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'engine',engine)
    with TestClient(main.app,raise_server_exceptions=False) as c:
        c.headers.update({'Authorization':'Bearer '+main.TOKEN,'Origin':'tauri://localhost'})
        yield c,store,engine

def new_episode(client):
    c,_,_=client
    return c.post('/episodes',json={'name':'CORS regression','audio_url':'https://youtu.be/dQw4w9WgXcQ','channel_url':'https://youtube.com/@ambient'}).json()['id']

def test_start_validation_is_readable_by_webkit_and_persisted(client,monkeypatch):
    c,store,engine=client;eid=new_episode(client)
    message='Enable image-capable agent support in Settings after verifying your model can inspect local images'
    async def blocked(_): raise ValueError(message)
    monkeypatch.setattr(engine,'start',blocked)
    result=c.post('/episodes/'+eid+'/start')
    assert result.status_code==400
    assert result.headers['access-control-allow-origin']=='tauri://localhost'
    assert result.json()['detail']==message
    assert 'Start blocked:' in store.rows('SELECT message FROM logs ORDER BY id DESC LIMIT 1')[0]['message']
    assert not engine.enabled(eid)
    assert all(t['status']=='Pending' for t in store.rows('SELECT status FROM tasks'))

def test_auth_and_middleware_validation_errors_have_cors(client):
    c,_,_=client;eid=new_episode(client)
    response=c.post('/episodes/'+eid+'/tasks/missing/retry')
    assert response.status_code==400 and response.headers['access-control-allow-origin']=='tauri://localhost'
    response=c.get('/episodes',headers={'Authorization':'Bearer invalid'})
    assert response.status_code==401 and response.headers['access-control-allow-origin']=='tauri://localhost'
    response=c.get('/episodes',headers={'Origin':'https://untrusted.invalid'})
    assert 'access-control-allow-origin' not in response.headers

def test_unhandled_error_has_cors_and_does_not_leak_exception(client,monkeypatch):
    c,_,_=client
    def failure(): raise TypeError('must-not-leak-test-secret')
    monkeypatch.setattr(main,'get_settings',failure)
    response=c.get('/settings')
    assert response.status_code==500 and response.headers['access-control-allow-origin']=='tauri://localhost'
    assert 'must-not-leak' not in response.text
    assert 'Local backend error' in response.json()['detail']

@pytest.mark.parametrize('profile',['../Default','/tmp/cookies','chrome:Default','Default::other','x+keyring'])
def test_cookie_profile_cannot_inject_options_or_paths(profile):
    with pytest.raises(ValueError): chrome_cookie_args(True,profile)
    with pytest.raises(ValidationError): Settings(yt_dlp_chrome_profile=profile)

def test_chrome_cookie_flag_has_no_export_file():
    assert chrome_cookie_args()==[]
    assert chrome_cookie_args(True)==['--cookies-from-browser','chrome']
    assert chrome_cookie_args(True,'Profile 1')==['--cookies-from-browser','chrome:Profile 1']

async def test_download_argv_is_explicit_and_honors_cookie_choice(tmp_path,monkeypatch):
    recorded=[]
    async def capture(args,**kwargs):
        recorded.append((args,kwargs));raise RuntimeError('captured-before-download')
    monkeypatch.setattr(reference,'run',capture)
    config={'audio_url':'https://youtu.be/dQw4w9WgXcQ','permission':True,'start_seconds':10,'analysis_minutes':3}
    with pytest.raises(RuntimeError,match='captured-before-download'):
        await reference.analyze(tmp_path,config,lambda name:'/tools/'+name,True,'Profile 1')
    args,kwargs=recorded[0]
    assert args[args.index('--cookies-from-browser')+1]=='chrome:Profile 1'
    assert '--ignore-config' in args and '--no-cache-dir' in args
    assert '--cookies' not in args
    assert args[-2:]==['--',config['audio_url']]
    assert kwargs['sanitize'] is redact_download_output

async def test_download_consent_is_checked_before_accessing_browser(tmp_path,monkeypatch):
    async def forbidden(*args,**kwargs): raise AssertionError('Browser/tool access without permission')
    monkeypatch.setattr(reference,'run',forbidden)
    with pytest.raises(ValueError,match='Permission'):
        await reference.analyze(tmp_path,{'audio_url':'https://youtu.be/dQw4w9WgXcQ','permission':False},lambda n:n,True)

async def test_process_logs_and_error_redact_cookie_and_signed_url(tmp_path):
    log=tmp_path/'download.log'
    script='import sys; print("Cookie: SID=fake-cookie-secret"); print("Authorization: Bearer fake-auth-secret"); print("https://media.example/video?token=fake-url-secret"); sys.exit(1)'
    with pytest.raises(RuntimeError) as error: await run([sys.executable,'-c',script],log=log,sanitize=redact_download_output)
    for text in (str(error.value),log.read_text()):
        assert 'fake-cookie-secret' not in text and 'fake-auth-secret' not in text and 'fake-url-secret' not in text
        assert '[redacted]' in text

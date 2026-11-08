import base64,json,time
import pytest
from pydantic import ValidationError
from backend.integrations.suno import SunoDraftRequest,prepare_draft
from backend.models.schema import SunoOptions,SunoMusicBrief

OPTIONS=dict(exclude_styles="vocals, drums",weirdness=25,style_influence=80,variety="off",duration_seconds=180,max_mode=False,personalize="off",vocal_gender="none",rationale="Low variation and strong style adherence fit the original steady beatless ambient brief.")

def test_suno_handoff_is_prepare_only_and_keeps_unicode(tmp_path):
    (tmp_path/'music_brief.json').write_text(json.dumps({'suno_options':OPTIONS,'brief':'An original ambient atmosphere','prompts':['Warm ambient pads','Slow distant drones']}))
    result=prepare_draft(tmp_path,{'name':'Ночной поезд'},SunoDraftRequest(account_email='User@example.com',prompt_index=1))
    encoded=result['url'].split('=',1)[1]
    payload=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
    assert payload['more_options']==OPTIONS and payload['version']==2
    assert payload['mode']=='prepare_only' and payload['instrumental'] is True
    assert payload['title']=='Ночной поезд' and payload['account_email']=='user@example.com'
    assert payload['styles']=='Instrumental only, no vocals. Slow distant drones'
    assert abs(payload['created']-time.time())<5
    assert json.loads((tmp_path/'suno_draft.json').read_text())==payload

@pytest.mark.parametrize('email',['bad','user@','x@example.com\nmalicious','https://example.com'])
def test_suno_requires_account_email(email):
    with pytest.raises(ValidationError): SunoDraftRequest(account_email=email)

def test_suno_rejects_invalid_prompt_or_oversize_without_writing(tmp_path):
    (tmp_path/'music_brief.json').write_text(json.dumps({'suno_options':OPTIONS,'brief':'A valid music brief','prompts':['a'*1000,'Short prompt']}))
    for index in (0,7):
        with pytest.raises(ValueError): prepare_draft(tmp_path,{'name':'Track'},SunoDraftRequest(account_email='user@example.com',prompt_index=index))
    assert not (tmp_path/'suno_draft.json').exists()

def test_suno_endpoint_requires_music_review_and_auth(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import backend.main as main
    from backend.storage.db import Store
    from backend.models.schema import Settings,EpisodeInput
    from backend.orchestration.engine import Engine
    from backend.integrations.process import checksum
    store=Store(tmp_path/'db');settings=Settings(working_directory=str(tmp_path/'episodes'))
    engine=Engine(store,settings.working_directory,settings)
    eid=engine.create(EpisodeInput(name='Suno test',audio_url='https://youtu.be/dQw4w9WgXcQ',channel_url='https://youtube.com/@ambient').model_dump())
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'engine',engine)
    with TestClient(main.app) as c:
        path=f'/episodes/{eid}/suno/prepare';body={'account_email':'user@example.com'}
        assert c.post(path,json=body).status_code==401
        c.headers['Authorization']='Bearer '+main.TOKEN
        assert c.post(path,json=body).status_code==400
        file=engine.directory(eid)/'music_brief.json';file.write_text(json.dumps({'suno_options':OPTIONS,'brief':'Original ambient music','prompts':['Soft drones','Gentle pads']}))
        store.update(eid,'music_brief','Completed',data={'artifact_checksums':{'music_brief.json':checksum(file)}})
        store.update(eid,'music_approval','Waiting for Approval')
        response=c.post(path,json=body)
        assert response.status_code==200 and response.json()['draft']['mode']=='prepare_only'
        assert store.task(eid,'music_approval')['status']=='Waiting for Approval'
        assert not list(engine.directory(eid).glob('*.mp3'))
        file.write_text('changed')
        assert c.post(path,json=body).status_code==400

def test_legacy_brief_cannot_silently_skip_more_options(tmp_path):
    (tmp_path/'music_brief.json').write_text(json.dumps({'brief':'Original ambient soundscape','prompts':['Warm pads','Slow drones']}))
    with pytest.raises(ValueError,match='More Options are required'):
        prepare_draft(tmp_path,{'name':'Track'},SunoDraftRequest(account_email='user@example.com'))
    assert not (tmp_path/'suno_draft.json').exists()
    with pytest.raises(ValidationError): SunoMusicBrief(brief='Original ambient soundscape',prompts=['Warm pads','Slow drones'])

@pytest.mark.parametrize('field,value',[('weirdness',101),('style_influence',-1),('variety','random'),('duration_seconds',0),('vocal_gender','male'),('personalize','on')])
def test_invalid_more_options_are_rejected(field,value):
    with pytest.raises(ValidationError): SunoOptions(**{**OPTIONS,field:value})

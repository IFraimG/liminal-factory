import asyncio,json
from pathlib import Path
import pytest
from backend.models.schema import Settings,ChannelMetadataPlan,ChannelReviewRequest,ChannelTitleApproval
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.orchestration.workflow import DAG
from backend.orchestration.versions import Versions
from backend.integrations.process import checksum

VIDEOS=[{'video_id':f'vid{i:08d}','title':f'Empty train at night {i}','url':f'https://www.youtube.com/watch?v=vid{i:08d}'} for i in range(12)]
@pytest.fixture
def setup(tmp_path,monkeypatch):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings());e=engine.create({'name':'review','channel_url':'https://youtube.com/@ambient','style':'Liminal Space'});root=engine.directory(e)
    for n in DAG:store.update(e,n,'Approved' if n.endswith('_approval') else 'Completed',data={'kept':n})
    for name in ('music_brief','visual_reference'):(root/(name+'.json')).write_text('{}')
    async def videos(*args):return VIDEOS
    monkeypatch.setattr('backend.orchestration.channel_review.channel_videos',videos);monkeypatch.setattr(engine,'tool',lambda name:name)
    return engine,store,e,root

async def round_result(engine,store,e,request,monkeypatch):
    identifier=await engine.channel_review.begin(e,request);seen=[]
    async def ask(e,n,prompt,schema,**kwargs):
        source=json.loads((engine.directory(e)/('channel-review/'+identifier+'/source-videos.json')).read_text())['videos'];seen.extend(source)
        candidates=[{'video_id':v['video_id'],'title':v['title']+(' · colder' if request.action=='refine' else ''),'reason':'Fits the deserted train atmosphere'} for v in source[:5]]
        return {'result':{'candidates':candidates,'hashtags':'#ambient, #darkambient, #coldcore','description':'An empty train atmosphere'},'artifacts':[]}
    monkeypatch.setattr(engine,'ask',ask)
    result=await engine.channel_review.generate(e)
    store.update(e,'metadata','Completed',data={**store.task(e,'metadata')['data'],**result,'artifact_checksums':{name:checksum(engine.directory(e)/name) for name in result['artifacts']}})
    store.update(e,'metadata_approval','Waiting for Approval')
    return identifier,result,seen

@pytest.mark.asyncio
async def test_existing_channel_title_requires_human_approval_and_preserves_other_branches(setup,monkeypatch):
    engine,store,e,root=setup;before={n:store.task(e,n) for n in DAG}
    identifier,result,seen=await round_result(engine,store,e,ChannelReviewRequest(),monkeypatch)
    assert engine.workflow(e)['final_assembly'][-1]=='metadata_approval'
    assert store.task(e,'metadata_approval')['status']=='Waiting for Approval'
    data=engine.channel_review.row(e,identifier)['data'];candidate=data['candidates'][1]
    assert candidate['title']==candidate['original_title'] and not candidate['adapted']
    meta=engine.channel_review.approve(e,ChannelTitleApproval(round_id=identifier,expected_round_id=identifier,video_id=candidate['video_id']))
    assert meta['recommended']==candidate['title'] and meta['source_url']==candidate['source_url']
    assert meta['hashtags']=='#ambient, #darkambient, #coldcore'
    engine.verify_approval(e,'metadata_approval');engine.verify_artifacts(e,'metadata')
    for n in set(DAG)-{'metadata','final_assembly'}:assert store.task(e,n)==before[n]
    # Repeated approval is idempotent and must not reset an already completed final.
    store.update(e,'final_assembly','Completed');before_final=store.task(e,'final_assembly')
    engine.channel_review.approve(e,ChannelTitleApproval(round_id=identifier,expected_round_id=identifier,video_id=candidate['video_id']))
    assert store.task(e,'final_assembly')==before_final

@pytest.mark.asyncio
async def test_search_more_excludes_shown_videos_and_refine_preserves_provenance_and_history(setup,monkeypatch):
    engine,store,e,root=setup
    first,_,_=await round_result(engine,store,e,ChannelReviewRequest(),monkeypatch);old=engine.channel_review.row(e,first)['data']['candidates']
    second,_,pool=await round_result(engine,store,e,ChannelReviewRequest(expected_round_id=first,feedback='Prefer a colder atmosphere'),monkeypatch)
    assert not {v['video_id'] for v in pool}&{v['video_id'] for v in old}
    candidate=engine.channel_review.row(e,second)['data']['candidates'][0]
    third,_,_=await round_result(engine,store,e,ChannelReviewRequest(action='refine',expected_round_id=second,feedback='Add a colder ending',video_id=candidate['video_id']),monkeypatch)
    new=engine.channel_review.row(e,third)['data']['candidates'][0]
    assert new['adapted'] and new['title'].endswith(' · colder') and new['original_title']==candidate['original_title'] and new['source_url']==candidate['source_url']
    assert len(engine.channel_review.rows(e))==3
    reloaded=Engine(Store(Path(store.rows('PRAGMA database_list')[0]['file'])),engine.root,engine.settings)
    assert reloaded.channel_review.row(e,third)['data']['candidates']==[new]
    # The user can explicitly choose a title from an earlier round.
    restored=engine.channel_review.approve(e,ChannelTitleApproval(round_id=first,expected_round_id=third,video_id=old[0]['video_id']))
    assert restored['recommended']==old[0]['title']
    with pytest.raises(ValueError,match='round changed'):await engine.channel_review.begin(e,ChannelReviewRequest(expected_round_id=third))

@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['invented_title','unknown_video'])
async def test_agent_cannot_invent_a_title_or_a_source_video(setup,monkeypatch,bad):
    engine,store,e,root=setup;identifier=await engine.channel_review.begin(e,ChannelReviewRequest())
    async def ask(*args,**kwargs):return {'result':{'candidates':[{'video_id':VIDEOS[0]['video_id'] if bad=='invented_title' else 'notachannel','title':'Invented' if bad=='invented_title' else VIDEOS[0]['title'],'reason':'Fits'}],'hashtags':'#ambient','description':''},'artifacts':[]}
    monkeypatch.setattr(engine,'ask',ask)
    with pytest.raises(ValueError):await engine.channel_review.generate(e)
    assert engine.channel_review.row(e,identifier)['status']=='Failed'
    assert store.task(e,'metadata_approval')['status']=='Pending'

def test_hashtags_are_single_line_joined_tokens():
    base={'candidates':[{'video_id':VIDEOS[0]['video_id'],'title':'Title','reason':'Fits'}],'description':''}
    assert ChannelMetadataPlan(**base,hashtags='#ambient, #darkambient, #coldcore').hashtags.count(', ')==2
    for value in ('#dark ambient','#ambient\n#coldcore','#ambient, #Ambient','#ambient,#coldcore'):
        with pytest.raises(ValueError):ChannelMetadataPlan(**base,hashtags=value)

@pytest.mark.asyncio
async def test_search_archives_a_completed_final_before_metadata_reset(setup):
    engine,store,e,root=setup;(root/'output').mkdir();(root/'output/final.mp4').write_bytes(b'old final');(root/'output/metadata.json').write_text('{}')
    paths=['output/final.mp4','output/metadata.json'];store.update(e,'final_assembly','Completed',data={'artifacts':paths,'artifact_checksums':{p:checksum(root/p) for p in paths}})
    await engine.channel_review.begin(e,ChannelReviewRequest())
    version=Versions(store,engine.root).list(e)[0];assert (root/version['video']).read_bytes()==b'old final'
    assert store.task(e,'final_assembly')['status']=='Pending'

@pytest.mark.asyncio
async def test_channel_video_extraction_has_verified_links_pagination_cache_and_cookies(tmp_path,monkeypatch):
    import backend.integrations.youtube as yt
    calls=[]
    async def extract(args,**kw):calls.append(args);return json.dumps({'entries':[{'entries':[{'id':VIDEOS[0]['video_id'],'title':'First title'}]},{'entries':[{'id':VIDEOS[1]['video_id'],'title':'Second title'},{'id':VIDEOS[0]['video_id'],'title':'Duplicate'},{'id':'private-id','title':'Private video'}]}]})
    monkeypatch.setattr(yt,'run',extract);store=Store(tmp_path/'db')
    result=await yt.channel_videos('https://youtube.com/@ambient','yt-dlp',store,chrome_cookies=True,chrome_profile='Profile 1')
    assert len(result)==2 and result[0]['url']=='https://www.youtube.com/watch?v='+VIDEOS[0]['video_id']
    assert '--playlist-end' not in calls[0] and 'chrome:Profile 1' in calls[0]
    assert await yt.channel_videos('https://youtube.com/@ambient','yt-dlp',store)==result and len(calls)==1

@pytest.mark.asyncio
async def test_changed_source_artifact_cannot_be_reapproved(setup,monkeypatch):
    engine,store,e,root=setup;identifier,_,_=await round_result(engine,store,e,ChannelReviewRequest(),monkeypatch)
    data=engine.channel_review.row(e,identifier)['data'];path=data['files'][0];(root/path).write_text('changed externally')
    with pytest.raises(ValueError,match='source artifact changed'):engine.channel_review.approve(e,ChannelTitleApproval(round_id=identifier,expected_round_id=identifier,video_id=data['candidates'][0]['video_id']))
    assert store.task(e,'metadata_approval')['status']=='Waiting for Approval'

@pytest.mark.asyncio
async def test_description_only_revision_keeps_title_selected_from_older_history(setup,monkeypatch):
    engine,store,e,root=setup;first,_,_=await round_result(engine,store,e,ChannelReviewRequest(),monkeypatch);chosen=engine.channel_review.row(e,first)['data']['candidates'][1]
    second,_,_=await round_result(engine,store,e,ChannelReviewRequest(expected_round_id=first),monkeypatch)
    old=engine.channel_review.approve(e,ChannelTitleApproval(round_id=first,expected_round_id=second,video_id=chosen['video_id']))
    store.update(e,'metadata','Pending',data={'revision_fields':['description'],'feedback':'Change the description only'})
    async def ask(e,n,prompt,schema,**kwargs):
        return {'result':{'candidates':[{'video_id':chosen['video_id'],'title':'A changed title that must be ignored','reason':'A test recommendation'}],'hashtags':'#changed','description':'New description only'},'artifacts':[]}
    monkeypatch.setattr(engine,'ask',ask)
    result=await engine.channel_review.generate(e)
    assert result['result']['recommended']==old['recommended']
    assert result['result']['source_video_id']==chosen['video_id']
    assert result['result']['hashtags']==old['hashtags'] and result['result']['description']=='New description only'

def test_search_and_selection_api_are_authenticated_and_require_explicit_approval(setup,monkeypatch,tmp_path):
    import time
    monkeypatch.setenv('LIMINAL_DATA',str(tmp_path/'api-data'));monkeypatch.setenv('LIMINAL_TOKEN','test-token')
    import backend.main as main
    from fastapi.testclient import TestClient
    engine,store,e,root=setup;monkeypatch.setattr(main,'engine',engine);monkeypatch.setattr(main,'store',store)
    async def ask(*args,**kwargs):return {'result':{'candidates':[{'video_id':VIDEOS[0]['video_id'],'title':VIDEOS[0]['title'],'reason':'Fits the empty train'}],'hashtags':'#ambient, #coldcore','description':'A train atmosphere'},'artifacts':[]}
    async def final(*args):return {'artifacts':[]}
    monkeypatch.setattr(engine,'ask',ask);engine.handlers['final_assembly']=final
    with TestClient(main.app) as client:
        url=f'/episodes/{e}/channel-review/search'
        assert client.post(url,json={}).status_code==401
        client.headers['Authorization']='Bearer '+main.TOKEN
        response=client.post(url,json={});assert response.status_code==200;identifier=response.json()['id']
        for _ in range(100):
            detail=client.get('/episodes/'+e).json()
            if next(t['status'] for t in detail['tasks'] if t['name']=='metadata_approval')=='Waiting for Approval':break
            time.sleep(.01)
        assert detail['channel_review']['current_round_id']==identifier
        assert next(t['status'] for t in detail['tasks'] if t['name']=='metadata_approval')=='Waiting for Approval'
        assert client.post(f'/episodes/{e}/channel-review/approve',json={'round_id':identifier,'expected_round_id':'stale','video_id':VIDEOS[0]['video_id']}).status_code==400
        result=client.post(f'/episodes/{e}/channel-review/approve',json={'round_id':identifier,'expected_round_id':identifier,'video_id':VIDEOS[0]['video_id']})
        assert result.status_code==200 and result.json()['recommended']==VIDEOS[0]['title']

@pytest.mark.asyncio
async def test_title_and_hashtag_search_preserves_existing_description(setup,monkeypatch):
    engine,store,e,root=setup;(root/'metadata.json').write_text(json.dumps({'description':'Keep this existing description'}))
    identifier,result,_=await round_result(engine,store,e,ChannelReviewRequest(),monkeypatch)
    assert result['result']['description']=='Keep this existing description'

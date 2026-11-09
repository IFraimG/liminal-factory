import asyncio,json,time
import pytest
from pydantic import ValidationError
from backend.orchestration.engine import Engine,PriorityLockedError
from backend.orchestration.priorities import ACTIVE_STATUSES,LOCAL_TASKS
from backend.integrations.quota import QuotaRouter
from backend.models.schema import Settings,EpisodeInput,StepPreparation
from backend.storage.db import Store

ORDER=['antigravity','kimi','codex']
@pytest.fixture
def configured(tmp_path):
    store=Store(tmp_path/'factory.db');engine=Engine(store,tmp_path/'episodes',Settings(agent_kind='codex'))
    eid=engine.create({'name':'priority test','permission':True});return engine,store,eid

@pytest.mark.parametrize('status',sorted(ACTIVE_STATUSES))
def test_active_step_locks_order_without_changing_config(configured,status):
    engine,store,eid=configured;before=store.config(eid)
    store.update(eid,'music_brief',status)
    with pytest.raises(PriorityLockedError):engine.set_priorities(eid,'music_brief',ORDER)
    assert store.config(eid)==before

def test_runtime_claim_locks_even_when_status_lags(configured):
    engine,store,eid=configured;engine.running[(eid,'music_brief')]=object()
    with pytest.raises(PriorityLockedError):engine.set_priorities(eid,'music_brief',ORDER)

@pytest.mark.parametrize('status',['Pending','Failed','Cancelled','Completed'])
def test_saved_order_is_per_step_durable_and_keeps_outputs(configured,status):
    engine,store,eid=configured
    store.update(eid,'music_brief',status,data={'artifacts':['music_brief.json'],'artifact_checksums':{'music_brief.json':'existing'}})
    before=store.task(eid,'music_brief');engine.set_priorities(eid,'music_brief',ORDER)
    engine.set_priorities(eid,'metadata',['kimi','codex','antigravity'])
    assert store.task(eid,'music_brief')==before
    assert store.config(eid)['agent_priorities']['music_brief']==ORDER
    other=Engine(store,engine.root,engine.settings)
    assert other.store.config(eid)['agent_priorities']['metadata']==['kimi','codex','antigravity']
    assert 'unity_preview' not in store.config(eid)['agent_priorities']

@pytest.mark.parametrize('order',[None,[],['codex'],['codex','codex','kimi'],['codex','kimi','unknown'],[{},'kimi','antigravity']])
def test_invalid_priority_not_persisted(configured,order):
    engine,store,eid=configured
    with pytest.raises(ValueError):engine.set_priorities(eid,'music_brief',order)
    assert not store.config(eid).get('agent_priorities')

def test_approval_stays_human(configured):
    engine,_,eid=configured
    for name in ('music_approval','visual_approval','unknown'):
        with pytest.raises(ValueError):engine.set_priorities(eid,name,ORDER)

@pytest.mark.asyncio
@pytest.mark.parametrize('balances,expected',[({'antigravity':4.9,'kimi':5,'codex':95},'kimi'),({'antigravity':5,'kimi':90,'codex':100},'antigravity'),({'antigravity':None,'kimi':4,'codex':20},'antigravity'),({'antigravity':4,'kimi':4,'codex':20},'codex'),({'antigravity':4,'kimi':None,'codex':4.9},None)])
async def test_first_eligible_not_richest_agent(balances,expected,monkeypatch):
    router=QuotaRouter();seen=[]
    async def read(provider,executable):seen.append(provider);return balances[provider]
    monkeypatch.setattr(router,'read',read)
    assert await router.choose(ORDER,'codex')==expected
    assert seen==ORDER[:ORDER.index(expected)+1] if expected else seen==ORDER

@pytest.mark.asyncio
async def test_expired_manual_balances_are_not_eligible(configured,monkeypatch):
    engine,store,eid=configured
    async def unavailable(_):return None
    monkeypatch.setattr('backend.integrations.quota.codex_limits',unavailable)
    engine.set_manual_quota('kimi',5,15)
    assert await engine.quota.choose(['kimi'])=='kimi'
    reported=engine.manual_quota('kimi');reported['expires_at']=time.time()-1
    store.execute('UPDATE cache SET data=? WHERE key=?',(json.dumps(reported),'agent-quota:kimi'));engine.quota.latest.clear()
    assert await engine.quota.choose(['kimi']) is None
    engine.set_manual_quota('kimi',80);new=Engine(store,engine.root,engine.settings)
    assert await new.quota.choose(['kimi'])=='kimi'
    engine.set_manual_quota('kimi',None)
    assert await engine.quota.choose(['kimi']) is None

@pytest.mark.asyncio
async def test_waiting_quota_sends_nothing_and_resumes_on_fresh_report(configured,monkeypatch):
    engine,store,eid=configured;engine.quota_poll_interval=.005
    async def unavailable(_):return None
    monkeypatch.setattr('backend.integrations.quota.codex_limits',unavailable)
    engine.set_manual_quota('antigravity',4)
    pending=asyncio.create_task(engine.select_provider(eid,'metadata',ORDER))
    try:
        for _ in range(100):
            if store.task(eid,'metadata')['status']=='Waiting for quota':break
            await asyncio.sleep(.001)
        assert not pending.done() and engine.priorities_locked(eid,'metadata')
        engine.set_manual_quota('kimi',5)
        assert await asyncio.wait_for(pending,1)=='kimi'
    finally:
        if not pending.done():pending.cancel();await asyncio.gather(pending,return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('name',sorted(LOCAL_TASKS & set(__import__('backend.orchestration.workflow',fromlist=['DAG']).DAG)))
async def test_local_steps_prepare_with_selected_agent_before_tools(configured,monkeypatch,name):
    engine,store,eid=configured;order=[]
    for dependency in __import__('backend.orchestration.workflow',fromlist=['DAG']).DAG[name]:store.update(eid,dependency,'Completed')
    async def ask(e,n,prompt,schema):
        assert issubclass(schema,StepPreparation) and schema.model_json_schema()['properties']['task']['const']==n;order.append('agent');return {'result':{'task':n,'summary':'Prepare a concrete local execution plan','checks':['Verify output']},'artifacts':[]}
    async def dispatch(e,n):order.append('tool');return {'artifacts':[]}
    monkeypatch.setattr(engine,'ask',ask);monkeypatch.setattr(engine,'dispatch',dispatch)
    await engine.execute(eid,name)
    assert order==['agent','tool'] and store.task(eid,name)['status']=='Completed'
    assert store.task(eid,name)['data']['assistant_plan']['task']==name

@pytest.mark.asyncio
async def test_wrong_local_plan_never_launches_tools(configured,monkeypatch):
    engine,store,eid=configured
    async def ask(*args):return {'result':{'task':'other'},'artifacts':[]}
    async def forbidden(*args):raise AssertionError('Tools must not start')
    monkeypatch.setattr(engine,'ask',ask);monkeypatch.setattr(engine,'dispatch',forbidden)
    await engine.execute(eid,'audio_reference')
    assert store.task(eid,'audio_reference')['status']=='Failed'
    assert 'another step' in store.task(eid,'audio_reference')['error']

@pytest.mark.asyncio
async def test_api_lock_and_workflow_metadata(configured,monkeypatch):
    from fastapi.testclient import TestClient
    import backend.main as module
    engine,store,eid=configured;monkeypatch.setattr(module,'engine',engine);monkeypatch.setattr(module,'store',store)
    client=TestClient(module.app);headers={'Authorization':'Bearer '+module.TOKEN}
    url=f'/episodes/{eid}/tasks/music_brief/priorities'
    assert client.put(url,headers=headers,json={'order':ORDER}).status_code==200
    store.update(eid,'music_brief','Waiting for Permission')
    assert client.put(url,headers=headers,json={'order':list(reversed(ORDER))}).status_code==409
    detail=client.get(f'/episodes/{eid}',headers=headers).json()
    task=next(t for t in detail['tasks'] if t['name']=='music_brief')
    assert task['priority_locked'] and task['agent_priorities']==ORDER
    assert detail['workflow']['final_assembly']==['audio_engineer','visual_render','metadata']
    await engine.cancel(eid,'music_brief')
    assert client.put(url,headers=headers,json={'order':list(reversed(ORDER))}).status_code==200

@pytest.mark.asyncio
async def test_cancel_waiting_task_unlocks_only_after_it_stops(configured,monkeypatch):
    engine,store,eid=configured;engine.quota_poll_interval=.005
    async def insufficient(*args):return 4
    monkeypatch.setattr(engine.quota,'read',insufficient)
    for name in __import__('backend.orchestration.workflow',fromlist=['DAG']).DAG:store.update(eid,name,'Completed')
    store.update(eid,'metadata','Pending')
    store.execute('INSERT INTO cache VALUES(?,?,?)',('started:'+eid,'true',time.time()))
    engine.scheduler=asyncio.create_task(engine.serve())
    try:
        for _ in range(200):
            if store.task(eid,'metadata')['status']=='Waiting for quota':break
            await asyncio.sleep(.002)
        with pytest.raises(PriorityLockedError):engine.set_priorities(eid,'metadata',ORDER)
        await engine.cancel(eid,'metadata');await asyncio.sleep(0)
        engine.set_priorities(eid,'metadata',ORDER)
        assert store.task(eid,'metadata')['status']=='Cancelled'
    finally:await engine.close()

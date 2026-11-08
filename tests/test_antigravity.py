import asyncio,json,re,os
from pathlib import Path
import pytest
os.environ.setdefault('LIMINAL_DATA',str(Path(__file__).resolve().parents[1]/'work/test-api'))
from backend.integrations.antigravity import AntigravitySession,AntigravityAdapter,ClientSessionError
from backend.orchestration.herdr_adapter import HerdrAdapter
from backend.models.schema import Settings,EpisodeInput
from backend.orchestration.engine import Engine
from backend.storage.db import Store

class ClientFixture(AntigravitySession):
    def __init__(self,root,wait_seconds=.2):
        super().__init__('fake-hc',root/'agy',wait_seconds=wait_seconds)
        self.proxy=True;self.calls=[];self.opened=0;self.sent=asyncio.Event();self.complete=True;self.active_sends=0;self.peak=0
        self.terminal={'address':'t7','created_ms':100,'state':'live','turn':0,'cwd':str(root),'status':{'state':'idle'},'foreground':{'pid':123,'argv':[str(self.agy)],'name':'agy'}}
    async def health(self): return self.proxy
    async def open_client(self): self.opened+=1
    async def command(self,*args,raw=False):
        self.calls.append(args)
        if args[0]=='--version': return 'hc test'
        if args[0]=='schema': return {'methods':[{'name':n} for n in ('terminal.get','terminal.list','terminal.send','terminal.read','terminal.interrupt')]}
        if args[0]=='ls': return {'terminals':[{'address':'t7'}]}
        if args[0]=='get': return json.loads(json.dumps(self.terminal))
        if args[0]=='send':
            assert args[-3:]==('--if','idle','--json')
            self.sent.set();self.terminal['status']['state']='working'
            if self.complete:
                self.active_sends+=1;self.peak=max(self.peak,self.active_sends)
                await asyncio.sleep(.01)
                path=Path(re.search(r'JSON only to (.*?), using',args[2]).group(1))
                path.write_text('{"brief":"A quiet atmosphere","prompts":["One","Two"]}')
                self.active_sends-=1;self.terminal['turn']+=1;self.terminal['status']['state']='idle'
            return {'turn':self.terminal['turn']}
        if args[0]=='interrupt': self.terminal['status']['state']='idle';return {}
        if args[0]=='read': return 'current task output'
        raise AssertionError('Forbidden/unknown operation: '+str(args))

async def test_requires_explicit_origin_and_idle(tmp_path):
    session=ClientFixture(tmp_path)
    with pytest.raises(ClientSessionError,match='Confirm'): await session.bind('t7',False)
    with pytest.raises(ClientSessionError,match='local'): await session.bind('remote/t7',True)
    session.terminal['status']['state']='blocked'
    with pytest.raises(ClientSessionError,match='idle'): await session.bind('t7',True)
    assert not session.binding

async def test_rejects_shell_or_other_cli(tmp_path):
    session=ClientFixture(tmp_path)
    for name in ('zsh','gemini','fake-agy'):
        session.terminal['foreground']['argv']=[str(tmp_path/name)]
        with pytest.raises(ClientSessionError,match='actual running agy'): await session.bind('t7',True)

async def test_opens_client_waits_and_sends_nothing_before_confirmation(tmp_path):
    session=ClientFixture(tmp_path,wait_seconds=.04);adapter=AntigravityAdapter(session)
    with pytest.raises(ClientSessionError,match='Timed out'):
        await adapter.launch(tmp_path,'Task','result.json',lambda _:None)
    assert session.opened==1
    assert not any(c[0] in ('send','run','kill','interrupt','agent','pane') for c in session.calls)

async def test_existing_session_tasks_are_serialized_and_not_closed(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True)
    identities=[]
    async def task(i): return await AntigravityAdapter(session).launch(tmp_path,'Task',f'result-{i}.json',identities.append)
    values=await asyncio.gather(task(1),task(2))
    assert len(values)==2 and session.peak==1
    assert all(i['owned'] is False and i['transport']=='herdr-core-existing-session' for i in identities)
    assert sum(c[0]=='send' for c in session.calls)==2
    assert not any(c[0] in ('run','kill','rm','interrupt','agent','pane') for c in session.calls)

async def test_wait_resumes_only_after_manual_binding(tmp_path):
    session=ClientFixture(tmp_path,wait_seconds=2);adapter=AntigravityAdapter(session)
    task=asyncio.create_task(adapter.launch(tmp_path,'Task','manual.json',lambda _:None))
    await asyncio.sleep(.02)
    assert session.opened==1 and not session.sent.is_set()
    await session.bind('t7',True)
    result=await task
    assert result['brief']=='A quiet atmosphere'

async def test_proxy_loss_and_process_replacement_require_reconfirmation(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True)
    nonce=session.binding['nonce'];session.proxy=False
    with pytest.raises(ClientSessionError,match='disappeared'): await session.verify()
    assert session.binding is None
    session.proxy=True;await session.bind('t7',True)
    assert session.binding['nonce']!=nonce
    session.terminal['foreground']['pid']+=1
    with pytest.raises(ClientSessionError,match='another process'): await session.verify()
    assert session.binding is None

async def test_idle_without_result_does_not_complete(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True);session.complete=False
    async def idle_without_file():
        await session.sent.wait();session.terminal['turn']+=1;session.terminal['status']['state']='idle'
    idle=asyncio.create_task(idle_without_file())
    with pytest.raises(TimeoutError): await AntigravityAdapter(session).launch(tmp_path,'Task','missing.json',lambda _:None,timeout=.02)
    await idle
    assert not any(c[0]=='interrupt' for c in session.calls)

async def test_cancel_interrupts_only_current_prompt_and_never_closes_pane(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True);session.complete=False
    adapter=AntigravityAdapter(session);identities=[]
    task=asyncio.create_task(adapter.launch(tmp_path,'Task','cancel.json',identities.append))
    await session.sent.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert sum(c[0]=='interrupt' for c in session.calls)==1
    await AntigravityAdapter(session).cancel(identities[0])
    assert sum(c[0]=='interrupt' for c in session.calls)==1
    assert not any(c[0] in ('kill','rm','run') for c in session.calls)

async def test_legacy_gemini_cannot_start_directly(tmp_path):
    settings=Settings(agent_kind='gemini',tools={'hc':'fake-hc'})
    engine=Engine(Store(tmp_path/'db'),tmp_path/'episodes',settings)
    assert isinstance(engine.herdr(),AntigravityAdapter)
    for kind in ('gemini','agy','antigravity'):
        with pytest.raises(RuntimeError,match='Direct'):
            await HerdrAdapter('never-executed',kind).launch(tmp_path,'Task','x.json',lambda _:None)

async def test_restart_leaves_user_pane_untouched(tmp_path):
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings())
    config=EpisodeInput(name='Client recovery',audio_url='https://youtu.be/dQw4w9WgXcQ',channel_url='https://youtube.com/@ambient').model_dump()
    eid=engine.create(config)
    store.update(eid,'visual_reference','Waiting for Client',data={'identity':{'owned':False,'pane':'t7','pid':1}})
    await engine.recover()
    assert store.task(eid,'visual_reference')['status']=='Failed'
    assert 'untouched' in store.task(eid,'visual_reference')['error']

async def test_cannot_rebind_an_active_task(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True);session.complete=False
    adapter=AntigravityAdapter(session)
    task=asyncio.create_task(adapter.launch(tmp_path,'Task','active.json',lambda _:None))
    await session.sent.wait()
    with pytest.raises(ClientSessionError,match='current Client task'): await session.bind('t7',True)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert not session.in_flight

async def test_old_identity_cannot_control_rebound_cli(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True)
    old={'session_nonce':session.binding['nonce']}
    session.unbind();await session.bind('t7',True)
    with pytest.raises(ClientSessionError,match='changed'): await session.verify(old)

def test_client_api_requires_origin_confirmation_and_never_executes_gemini(tmp_path,monkeypatch):
    import backend.main as main
    from fastapi.testclient import TestClient
    store=Store(tmp_path/'api.sqlite');settings=Settings(working_directory=str(tmp_path/'episodes'),agent_kind='antigravity')
    engine=Engine(store,settings.working_directory,settings);engine._client_session=ClientFixture(tmp_path)
    monkeypatch.setattr(main,'store',store);monkeypatch.setattr(main,'engine',engine)
    async def forbidden(*args,**kwargs): raise AssertionError('Direct process launch attempted')
    monkeypatch.setattr(main,'run',forbidden)
    with TestClient(main.app) as client:
        client.headers['Authorization']='Bearer '+main.TOKEN
        assert client.post('/antigravity/bind',json={'target':'t7','launched_via_client':False}).status_code==409
        response=client.post('/antigravity/bind',json={'target':'t7','launched_via_client':True})
        assert response.status_code==200
        assert client.get('/antigravity/status').json()['bound_target']=='t7'
        assert client.post('/diagnostics/gemini').json()['ok'] is True
        assert client.post('/antigravity/unbind').status_code==200
        assert client.get('/antigravity/status').json()['bound_target'] is None

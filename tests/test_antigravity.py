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
            assert args[-3:]==('--if','idle','--json') or (args[-1]=='--json' and self.terminal['status']['state']=='done')
            assert '--force' not in args
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
    with pytest.raises(ClientSessionError,match='No CLI connection'):
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

async def test_permission_pause_waits_for_user_without_failing_or_approving(tmp_path):
    session=ClientFixture(tmp_path);await session.bind('t7',True);session.complete=False
    states=[];adapter=AntigravityAdapter(session,on_state=states.append)
    task=asyncio.create_task(adapter.launch(tmp_path,'Task','permission.json',lambda _:None,timeout=3))
    await session.sent.wait();session.terminal['status']['state']='blocked'
    await asyncio.sleep(.6)
    assert not task.done()
    assert 'blocked' in states
    assert not any(c[0] in ('keys','interrupt','kill','run') for c in session.calls)
    # Simulate the user resolving the CLI's permission dialog and the agent finishing its own work.
    (tmp_path/'permission.json').write_text('{"complete":true}')
    session.terminal['turn']+=1;session.terminal['status']['state']='done'
    assert await task=={'complete':True}
    assert 'done' in states

async def test_completed_cli_can_accept_next_task_without_forcing_a_dialog(tmp_path):
    session=ClientFixture(tmp_path);session.terminal['status']['state']='done';session.terminal['turn']=4
    await session.bind('t7',True)
    value=await AntigravityAdapter(session).launch(tmp_path,'Next task','after-done.json',lambda _:None)
    assert value['brief']=='A quiet atmosphere'
    sends=[c for c in session.calls if c[0]=='send']
    assert len(sends)==1 and '--force' not in sends[0]
    assert '--if' not in sends[0]  # Core supports no --if done flag.

def mark_client_launcher(session,root):
    session.expected_cwd=root.resolve()
    session.terminal['argv']=[str(session.agy)]
    session.terminal['pid']=session.terminal['foreground']['pid']
    session.terminal['labels']={'liminal_factory':'antigravity-client-launch','launch_id':'a'*32}

async def test_launcher_pane_reconnects_after_app_restart(tmp_path):
    first=ClientFixture(tmp_path);mark_client_launcher(first,tmp_path)
    assert (await first.status())['bound_target']=='t7'
    assert first.binding['origin']=='client-launcher'
    nonce=first.binding['nonce']
    restarted=ClientFixture(tmp_path);mark_client_launcher(restarted,tmp_path)
    value=await AntigravityAdapter(restarted).launch(tmp_path,'Task','auto.json',lambda _:None)
    assert value['brief']=='A quiet atmosphere'
    assert restarted.binding['nonce']!=nonce
    assert not any(c[0] in ('run','kill','agent','pane') for c in restarted.calls)

@pytest.mark.parametrize('change',['unmarked','wrong-cwd','shell','bad-id','blocked'])
async def test_auto_connection_rejects_unproven_or_unready_panes(tmp_path,change):
    s=ClientFixture(tmp_path);mark_client_launcher(s,tmp_path)
    if change=='unmarked': s.terminal['labels']={}
    if change=='wrong-cwd': s.terminal['cwd']=str(tmp_path/'other')
    if change=='shell': s.terminal['foreground']['argv']=['/bin/zsh']
    if change=='bad-id': s.terminal['labels']['launch_id']='not-a-launch-id'
    if change=='blocked': s.terminal['status']['state']='blocked'
    assert not await s.auto_connect()
    assert not s.binding and not s.sent.is_set()

async def test_auto_connection_never_guesses_between_launches(tmp_path):
    s=ClientFixture(tmp_path);mark_client_launcher(s,tmp_path)
    original=s.command
    async def command(*args,**kwargs):
        if args[0]=='ls': return {'terminals':[{'address':'t7'},{'address':'t8'}]}
        t=await original(*args,**kwargs)
        if args[0]=='get': t['address']=args[1]
        return t
    s.command=command
    assert not await s.auto_connect() and not s.binding

async def test_manual_disconnect_is_respected_until_prepare(tmp_path):
    s=ClientFixture(tmp_path);mark_client_launcher(s,tmp_path)
    assert await s.auto_connect()
    s.unbind(manual=True)
    assert not await s.auto_connect()
    assert (await s.status())['bound_target'] is None
    assert (await s.prepare())['bound_target']=='t7'

async def test_replacement_launcher_gets_new_identity_before_next_prompt(tmp_path):
    s=ClientFixture(tmp_path);mark_client_launcher(s,tmp_path)
    await s.auto_connect();old=s.binding.copy()
    s.terminal['foreground']['pid']+=1;s.terminal['created_ms']+=1
    with pytest.raises(ClientSessionError,match='another process'): await s.verify()
    # A shell child replacement isn't a new launcher grant. Require the root
    # terminal pid to agree with the actual foreground CLI as well.
    assert not await s.auto_connect()
    s.terminal['pid']=s.terminal['foreground']['pid']
    s.terminal['labels']['launch_id']='b'*32
    assert await s.auto_connect()
    assert s.binding['pid']!=old['pid'] and s.binding['nonce']!=old['nonce']

async def test_permission_time_does_not_exhaust_active_budget(tmp_path):
    s=ClientFixture(tmp_path);await s.bind('t7',True);s.complete=False
    a=AntigravityAdapter(s);a.poll_interval=.003
    job=asyncio.create_task(a.launch(tmp_path,'Task','paused.json',lambda _:None,timeout=.04))
    await s.sent.wait();s.terminal['status']['state']='blocked'
    await asyncio.sleep(.1)
    assert not job.done()
    (tmp_path/'paused.json').write_text('{"ok":true}')
    s.terminal['turn']+=1;s.terminal['status']['state']='done'
    assert await job=={'ok':True}
    assert not any(c[0] in ('keys','interrupt') for c in s.calls)

async def test_busy_bound_cli_waits_without_failing_or_sending(tmp_path):
    s=ClientFixture(tmp_path,wait_seconds=.02);await s.bind('t7',True)
    s.terminal['status']['state']='blocked';states=[]
    a=AntigravityAdapter(s,on_state=states.append)
    job=asyncio.create_task(a.launch(tmp_path,'Task','queued.json',lambda _:None))
    await asyncio.sleep(.06)
    assert not job.done() and not s.sent.is_set() and 'waiting_blocked' in states
    s.terminal['status']['state']='idle'
    assert (await job)['brief']=='A quiet atmosphere'
    assert sum(c[0]=='send' for c in s.calls)==1

async def test_marked_busy_launcher_is_not_mistaken_for_missing_cli(tmp_path):
    s=ClientFixture(tmp_path,wait_seconds=.02);mark_client_launcher(s,tmp_path)
    s.terminal['status']['state']='blocked';states=[]
    a=AntigravityAdapter(s,on_state=states.append)
    job=asyncio.create_task(a.launch(tmp_path,'Task','found-busy.json',lambda _:None))
    await asyncio.sleep(.06)
    assert not job.done() and not s.sent.is_set() and 'waiting_blocked' in states
    s.terminal['status']['state']='idle'
    assert (await job)['brief']=='A quiet atmosphere'

async def test_queue_cancellation_never_interrupts_another_prompt(tmp_path):
    s=ClientFixture(tmp_path);await s.bind('t7',True);s.complete=False
    first=AntigravityAdapter(s);first.poll_interval=.005
    active=asyncio.create_task(first.launch(tmp_path,'First','active1.json',lambda _:None))
    await s.sent.wait();states=[]
    queued=asyncio.create_task(AntigravityAdapter(s,on_state=states.append).launch(tmp_path,'Next','active2.json',lambda _:None))
    await asyncio.sleep(.01);assert 'queued' in states
    queued.cancel()
    with pytest.raises(asyncio.CancelledError): await queued
    assert not any(c[0]=='interrupt' for c in s.calls)
    active.cancel()
    with pytest.raises(asyncio.CancelledError): await active

async def test_late_metadata_recovers_only_valid_original_result(tmp_path):
    from backend.integrations.process import checksum
    store=Store(tmp_path/'late.db');settings=Settings(working_directory=str(tmp_path/'episodes'),agent_kind='antigravity')
    engine=Engine(store,settings.working_directory,settings);s=ClientFixture(tmp_path);engine._client_session=s
    eid=engine.create(EpisodeInput(channel_review_enabled=False,name='Late metadata',audio_url='https://youtu.be/dQw4w9WgXcQ',channel_url='https://youtube.com/@ambient').model_dump())
    root=engine.directory(eid)
    for task,name,data in [('channel_reference','channel_titles.json',['source title']),('music_brief','music_brief.json',{'brief':'Original music'}),('visual_reference','visual_reference.json',{'scene':'corridor'})]:
        (root/name).write_text(json.dumps(data));store.update(eid,task,'Completed',data={'artifacts':[name],'artifact_checksums':{name:checksum(root/name)}})
    identity={'pane':'t7','pid':123,'created_ms':100,'executable':str(s.agy),'transport':'herdr-core-existing-session','result':'metadata-'+'a'*32+'.json','before_turn':0}
    store.update(eid,'metadata','Running');store.update(eid,'metadata','Failed',error='Timeout',data={'identity':identity})
    s.terminal['turn']=1;s.terminal['status']['state']='done'
    result=dict(titles=['one','two','three','four','five'],recommended='one',description='A quiet original atmosphere',hashtags='#ambient, #liminal')
    file=root/identity['result'];file.write_text(json.dumps(result))
    # Schema-valid output still cannot duplicate reference titles.
    bad={**result,'titles':['source title','two','three','four','five'],'recommended':'source title'}
    file.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='duplicates'): await engine.recover_late_result(eid,'metadata')
    assert store.task(eid,'metadata')['status']=='Failed' and not (root/'metadata.json').exists()
    file.write_text(json.dumps(result));s.terminal['foreground']['pid']=124
    with pytest.raises(ValueError,match='Original CLI'): await engine.recover_late_result(eid,'metadata')
    s.terminal['foreground']['pid']=123
    await engine.recover_late_result(eid,'metadata')
    task=store.task(eid,'metadata')
    assert task['status']=='Completed' and not task['error'] and task['data']['result']==result
    assert task['data']['artifact_checksums']['metadata.json']==checksum(root/'metadata.json')
    assert not any(c[0] in ('send','run','keys') for c in s.calls)
    with pytest.raises(ValueError,match='inactive failed'): await engine.recover_late_result(eid,'metadata')

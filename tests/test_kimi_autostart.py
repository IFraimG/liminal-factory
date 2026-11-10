import asyncio
import pytest
from backend.integrations.kimi import KimiSession
from backend.integrations.antigravity import ClientSessionError

@pytest.mark.asyncio
async def test_concurrent_requests_start_one_dedicated_kimi(tmp_path,monkeypatch):
    exe=tmp_path/'kimi';exe.touch();session=KimiSession(hc='hc',executable=exe,expected_cwd=tmp_path)
    started=[]; terminals={}
    async def check():return {}
    async def connect():return False
    async def command(*args,**kwargs):
        if args[0]=='ls':return {'terminals':[{'address':x} for x in terminals]}
        if args[0]=='get':return terminals[args[1]]
        if args[0]=='run':
            started.append(args);await asyncio.sleep(.01)
            terminals['t1']={'address':'t1','state':'live','labels':{'liminal_factory':'kimi-session'}}
            return {'address':'t1','state':'live'}
        raise AssertionError(args)
    monkeypatch.setattr(session,'check',check);monkeypatch.setattr(session,'auto_connect',connect);monkeypatch.setattr(session,'command',command)
    await asyncio.gather(session.ensure_started(),session.ensure_started())
    assert len(started)==1
    a=started[0];i=a.index('--');assert a[i+1:]==(str(exe),'--model','kimi-code/k3.1-pro')
    assert '--json' in a[:i] and '--no-parent' in a and '--outlive-parent' in a

@pytest.mark.asyncio
async def test_multiple_existing_sessions_are_not_duplicated(tmp_path,monkeypatch):
    exe=tmp_path/'kimi';exe.touch();session=KimiSession(executable=exe,expected_cwd=tmp_path)
    async def check():return {}
    async def connect():return False
    async def command(*args,**kwargs):
        if args[0]=='ls':return {'terminals':[{'address':'t1'},{'address':'t2'}]}
        if args[0]=='get':return {'state':'live','labels':{'liminal_factory':'kimi-session'}}
        raise AssertionError('Must not launch')
    monkeypatch.setattr(session,'check',check);monkeypatch.setattr(session,'auto_connect',connect);monkeypatch.setattr(session,'command',command)
    with pytest.raises(ClientSessionError,match='Multiple'):await session.ensure_started()

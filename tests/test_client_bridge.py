import json,os,shlex
from pathlib import Path
import pytest
from backend.integrations.client_bridge import launch,interactive_args,inherited_environment,write_launcher,BridgeError

@pytest.fixture
def paths(tmp_path):
    hc=tmp_path/'hc';agy=tmp_path/'original agy';hc.touch();agy.touch()
    return hc,agy,tmp_path

class FakeRPC:
    def __init__(self,_): self.calls=[];self.closed=False
    def call(self,method,params):
        self.calls.append((method,params))
        return {'methods':['terminal.run']} if method=='hello' else {'address':'t9','state':'live'}
    def close(self): self.closed=True

def test_client_environment_uses_rpc_memory_not_command_arguments(paths):
    hc,agy,cwd=paths;rpc=FakeRPC(hc)
    result=launch(hc,agy,cwd,8047,['--model','gemini-example'],environ={'GEMINI_API_KEY':'fake-test-secret','PATH':'/bin','LIMINAL_TOKEN':'do-not-forward','SSH_AUTH_SOCK':'unrelated'},rpc_factory=lambda _:rpc,health=lambda:True)
    assert result=='t9' and rpc.closed
    method,params=rpc.calls[-1]
    assert method=='terminal.run' and params['argv']==[str(agy),'--model','gemini-example']
    assert params['env']['GEMINI_API_KEY']=='fake-test-secret'
    assert 'fake-test-secret' not in json.dumps(params['argv'])
    assert 'LIMINAL_TOKEN' not in params['env'] and 'SSH_AUTH_SOCK' not in params['env']
    assert params['no_parent'] and params['outlive_parent'] and not params['keep'] and not params['wait']
    assert 'line' not in params

@pytest.mark.parametrize('args',[['--api-key','secret'],['--settings','{}'],['--print','Do a task'],['--dangerously-skip-permissions'],['--model','bad;command'],['--effort','unsupported']])
def test_secret_or_noninteractive_flags_are_not_forwarded(args):
    with pytest.raises(BridgeError): interactive_args(args)

def test_no_proxy_means_no_rpc_or_fallback(paths):
    hc,agy,cwd=paths
    def forbidden(_): raise AssertionError('No RPC should be created')
    with pytest.raises(BridgeError,match='proxy is not ready'): launch(hc,agy,cwd,8047,[],rpc_factory=forbidden,health=lambda:False)

def test_external_launcher_quotes_paths_and_contains_no_credentials(tmp_path):
    file=tmp_path/'external launcher';backend=tmp_path/"a ' quoted path/backend"
    result=write_launcher(file,backend,tmp_path/'hc',tmp_path/'agy',tmp_path/'projects')
    text=result.read_text()
    command=text.splitlines()[-1]
    argv=shlex.split(command[len('exec '):])
    assert argv[0]==str(backend.resolve()) and argv[-1]=='$@'
    assert argv[1]=='--antigravity-client-bridge'
    assert 'TOKEN' not in text and 'API_KEY' not in text
    assert file.stat().st_mode&0o777==0o700
    assert write_launcher(file,backend,tmp_path/'hc',tmp_path/'agy',tmp_path/'projects')==file
    with pytest.raises(BridgeError,match='different content'): write_launcher(file,tmp_path/'other',tmp_path/'hc',tmp_path/'agy',tmp_path/'projects')

def test_launcher_does_not_follow_output_symlinks(tmp_path):
    original=tmp_path/'original';original.write_text('unchanged')
    link=tmp_path/'link';link.symlink_to(original)
    with pytest.raises(BridgeError): write_launcher(link,tmp_path/'backend',tmp_path/'hc',tmp_path/'agy',tmp_path/'projects')
    assert original.read_text()=='unchanged'

def test_missing_rpc_capability_has_no_launch(paths):
    hc,agy,cwd=paths
    class Incompatible(FakeRPC):
        def call(self,method,params): self.calls.append((method,params));return {'methods':[]}
    rpc=Incompatible(hc)
    with pytest.raises(BridgeError,match='support'): launch(hc,agy,cwd,8047,[],rpc_factory=lambda _:rpc,health=lambda:True)
    assert rpc.closed and len(rpc.calls)==1

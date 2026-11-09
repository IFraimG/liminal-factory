import json
from pathlib import Path
import pytest
from backend.integrations.codex_core import CodexCoreAdapter,strict_schema
from backend.models.schema import RevisionPlan

def test_strict_schema_requires_nullable_fields_too():
    s=strict_schema(RevisionPlan.model_json_schema())
    config=s['$defs']['RevisionConfig'];assert set(config['required'])==set(config['properties'])
    assert config['additionalProperties'] is False

@pytest.mark.asyncio
async def test_pinned_model_and_readonly_owned_terminal(tmp_path):
    adapter=CodexCoreAdapter('hc','/codex','gpt-6.1-sol','medium');calls=[];terminal={};reads=0
    async def check():return {}
    async def command(*args):
        nonlocal reads
        calls.append(args)
        if args[0]=='run':
            job=next(x.split('=',1)[1] for x in args if x.startswith('job_id='));argv=list(args[args.index('--')+1:]);terminal.update(address='t9',created_ms=12,pid=34,cwd=str(tmp_path),argv=argv,labels={'job_id':job,'liminal_factory':'codex-task'},state='live')
            Path(argv[argv.index('--output-last-message')+1]).write_text('{"ok":true}')
            return {'address':'t9'}
        if args[0]=='get':
            reads+=1
            if reads>1:terminal.update(state='finished',exit_code=0)
            return dict(terminal)
        raise AssertionError(args)
    adapter.check=check;adapter.command=command;identities=[]
    result=await adapter.launch(tmp_path,'Classify request','result.json',identities.append,schema={'type':'object','properties':{'ok':{'type':'boolean'}}})
    assert result=={'ok':True}
    args=calls[0];assert args[args.index('--model')+1]=='gpt-6.1-sol'
    assert 'model_reasoning_effort="medium"' in args
    assert args[args.index('--sandbox')+1]=='read-only'
    assert not any('dangerously' in item for item in args)
    assert identities[0]['owned'] and identities[0]['model']=='gpt-6.1-sol'
    terminal['labels']={}
    assert await adapter.cancel(identities[0]) is False
    assert not any(call[0]=='kill' for call in calls)

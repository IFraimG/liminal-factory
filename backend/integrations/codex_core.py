"""Run a bounded, read-only Codex request in an application-owned Herdr Core terminal."""
import asyncio,json,uuid
from pathlib import Path
from backend.integrations.process import run,contained

def strict_schema(schema):
    value=json.loads(json.dumps(schema))
    def visit(node):
        if isinstance(node,dict):
            if node.get('type')=='object' and 'properties' in node:
                node['additionalProperties']=False;node['required']=list(node['properties'])
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    visit(value);return value

class CodexCoreAdapter:
    def __init__(self,hc,executable,model='gpt-6.1-sol',effort='medium'):
        self.hc=hc;self.executable=str(Path(executable).resolve());self.model=model or 'gpt-6.1-sol';self.effort=effort
        self.active=None;self.on_state=None
    async def command(self,*args):return json.loads(await run([self.hc,*args],timeout=30))
    async def check(self):
        version=await run([self.executable,'--version'],timeout=20)
        listing=await self.command('ls','--json')
        if listing.get('error'):raise RuntimeError('Herdr Core is unavailable. Open Herdr and retry.')
        return {'version':version.strip(),'transport':'herdr-core-codex-exec'}
    async def launch(self,root,prompt,result_file,save_identity,timeout=1800,schema=None):
        await self.check();root=Path(root).resolve();result=contained(root,result_file)
        if result.exists():raise ValueError('Result file already exists')
        schema_path=root/(result_file+'.schema.json')
        if schema is None:raise ValueError('Codex requires a structured response schema')
        schema_path.write_text(json.dumps(strict_schema(schema)))
        job=uuid.uuid4().hex
        args=[self.executable,'exec','--model',self.model,'-c','model_reasoning_effort='+json.dumps(self.effort),
              '--sandbox','read-only','--skip-git-repo-check','--cd',str(root),'--output-schema',str(schema_path),
              '--output-last-message',str(result),prompt+'\nReturn ONLY the structured JSON response. Do not modify any files; the application saves and applies the validated result.']
        created=await self.command('run','--json','--bg','--no-parent','--no-notify','--outlive-parent','--cwd',str(root),'--label','liminal_factory=codex-task','--label','job_id='+job,'--',*args)
        target=created.get('address')
        if not target:raise RuntimeError('Herdr did not create a Codex terminal')
        terminal=await self.command('get',target,'--json')
        identity={'agent':'codex','pane':target,'owned':True,'transport':'herdr-core-codex-exec','job_id':job,'created_ms':terminal.get('created_ms'),'pid':terminal.get('pid'),'cwd':str(root),'executable':self.executable,'result':result_file,'model':self.model,'effort':self.effort}
        self.active=identity;save_identity(identity);remaining=timeout;last=asyncio.get_running_loop().time()
        try:
            while True:
                t=await self.verify(identity)
                if t.get('state')=='finished':
                    if t.get('exit_code')!=0:raise RuntimeError('Codex stopped without a result. Review its Herdr terminal for account, model, workspace-trust or permission errors. '+(await self.logs(identity))[-1800:])
                    if not result.is_file() or result.stat().st_size>4*1024*1024:raise RuntimeError('Codex did not return a bounded structured result')
                    value=json.loads(result.read_text())
                    if not isinstance(value,dict):raise ValueError('Expected JSON object')
                    return value
                state=(t.get('status') or {}).get('state');now=asyncio.get_running_loop().time()
                if state!='blocked':remaining-=now-last
                last=now
                if self.on_state:self.on_state('blocked' if state=='blocked' else 'working')
                if remaining<=0:raise TimeoutError('Codex active-time limit exceeded')
                await asyncio.sleep(.5)
        except BaseException:
            await self.cancel(identity);raise
    async def verify(self,identity):
        t=await self.command('get',identity['pane'],'--json');labels=t.get('labels') or {};argv=t.get('argv') or []
        if (labels.get('job_id')!=identity['job_id'] or labels.get('liminal_factory')!='codex-task' or t.get('created_ms')!=identity['created_ms'] or t.get('pid')!=identity['pid'] or t.get('cwd')!=identity['cwd'] or not argv or str(Path(argv[0]).resolve())!=self.executable or argv[1:2]!=['exec']):raise RuntimeError('Codex terminal identity changed; no process was signalled')
        return t
    async def cancel(self,identity):
        if not identity or identity.get('transport')!='herdr-core-codex-exec':return False
        try:
            t=await self.verify(identity)
            if t.get('state')=='finished':return True
            await self.command('kill',identity['pane'],'--json')
            return (await self.verify(identity)).get('state')=='finished'
        except (ValueError,RuntimeError,OSError,KeyError):return False
    async def logs(self,identity):
        await self.verify(identity)
        return await run([self.hc,'read',identity['pane'],'--lines','100'],timeout=30)

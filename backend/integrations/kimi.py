"""Use a dedicated existing Kimi Herdr session without touching permission dialogs."""
import asyncio,re,uuid
from pathlib import Path
from backend.integrations.antigravity import AntigravitySession,ClientSessionError

class KimiSession(AntigravitySession):
    def __init__(self,hc='hc',executable=None,wait_seconds=300,expected_cwd=None):
        super().__init__(hc,executable or Path.home()/'.kimi-code/bin/kimi',wait_seconds=wait_seconds,expected_cwd=expected_cwd)
        self.launch_lock=asyncio.Lock()
    async def health(self): return self.agy.is_file()
    async def open_client(self): pass
    async def prepare(self):
        await self.check();await self.auto_connect();return await self.status()
    def fingerprint(self,terminal):
        fg=terminal.get('foreground') or {};argv=terminal.get('argv') or [];fgargv=fg.get('argv') or []
        if (terminal.get('state')!='live' or not argv or Path(argv[0]).expanduser().resolve()!=self.agy
            or terminal.get('pid')!=fg.get('pid') or not isinstance(fg.get('pid'),int)
            or not fgargv or Path(fgargv[0]).name not in {'kimi','kimi-code'}
            or not re.fullmatch(r't[0-9a-z]+',terminal.get('address',''))):
            raise ClientSessionError('Select a dedicated live Kimi CLI, not a shell or hc attach wrapper')
        return {'address':terminal['address'],'created_ms':terminal.get('created_ms'),'pid':fg['pid'],'executable':str(self.agy)}
    def launcher_origin(self,terminal):
        argv=terminal.get('argv') or []
        return (terminal.get('labels',{}).get('liminal_factory')=='kimi-session'
            and self.expected_cwd is not None and Path(terminal.get('cwd') or '/').resolve()==self.expected_cwd
            and '--model' in argv and argv[argv.index('--model')+1:argv.index('--model')+2]==['kimi-code/k3.1-pro'])
    async def auto_connect(self):
        async with self.discovery_lock:
            if self.binding or self.in_flight: return False
            matches=[]
            for row in (await self.command('ls','--json')).get('terminals',[]):
                try:
                    t=await self.command('get',row['address'],'--json');fp=self.fingerprint(t)
                    if self.launcher_origin(t):matches.append((t,fp))
                except (RuntimeError,ValueError,KeyError,OSError):continue
            if len(matches)!=1:return False
            t,fp=matches[0]
            # Binding a blocked pane is safe: await_ready pauses and never sends into its dialog.
            self.binding={**fp,'nonce':uuid.uuid4().hex,'origin':'kimi-session'};self.ready.set();return True

    async def await_ready(self,on_state=None):
        try:
            await self.ensure_started()
            return await super().await_ready(on_state)
        except ClientSessionError as exc:
            raise ClientSessionError('Kimi CLI is unavailable or changed. Open the dedicated K3.1 Pro Herdr session in the episodes directory; resolve its dialogs yourself. '+str(exc).replace('Launch CLI through Client','Open the Kimi session').replace('Client-launched','dedicated Kimi')) from None

    async def ensure_started(self):
        # Called only after the router selects Kimi, never by status or priority edits.
        async with self.launch_lock:
            await self.check()
            if self.binding:
                try:
                    await self.verify(require_proxy=False)
                    return
                except ClientSessionError:
                    self.unbind()
            await self.auto_connect()
            if self.binding:return
            listing=await self.command('ls','--json')
            matches=[]
            for row in listing.get('terminals',[]):
                address=row.get('address','')
                if not re.fullmatch(r't[0-9a-z]+',address):continue
                terminal=await self.command('get',address,'--json')
                if terminal.get('state')=='live' and (terminal.get('labels') or {}).get('liminal_factory')=='kimi-session':matches.append(address)
            if len(matches)>1:raise ClientSessionError('Multiple dedicated Kimi sessions exist; inspect Herdr before retrying.')
            if matches:return  # Already starting or requires user attention; never duplicate.
            if not self.agy.is_file() or not self.expected_cwd or not self.expected_cwd.is_dir():
                raise ClientSessionError('Kimi executable or episodes directory is missing; check Settings.')
            try:
                result=await self.command('run','--bg','--no-parent','--no-notify','--outlive-parent','--name','liminal-factory-kimi','--cwd',str(self.expected_cwd),'--label','liminal_factory=kimi-session','--json','--',str(self.agy),'--model','kimi-code/k3.1-pro')
            except (OSError,RuntimeError,ValueError) as exc:
                raise ClientSessionError('Could not confirm automatic Kimi launch. Check Herdr before retrying; no duplicate launch was attempted.') from exc
            if not re.fullmatch(r't[0-9a-z]+',result.get('address','')) or result.get('state')=='finished':
                raise ClientSessionError('Kimi launch did not produce a live Herdr session. Check Herdr before retrying.')
    async def status(self):
        data=await super().status()
        if not self.binding:data['state']='Waiting for CLI'
        data['note']='Dedicated existing Kimi K3.1 Pro Herdr session. Permission dialogs are never approved automatically.'
        return data

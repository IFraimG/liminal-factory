import asyncio,os,signal,time,uuid
from contextvars import ContextVar
from pathlib import Path

class ProcessFailure(RuntimeError):
    def __init__(self,executable,returncode,detail):
        self.returncode=returncode;self.executable=str(executable)
        super().__init__(f'{Path(str(executable)).name} exited {returncode}: {detail}')

PROCESS_OBSERVER=ContextVar('process_observer',default=None)

async def run(args:list[str],cwd=None,timeout=120,log:Path|None=None,sanitize=None,stdout_only=False):
    # Shell interpolation is unavailable. Process handles, never persisted PIDs, authorize cancellation.
    process=await asyncio.create_subprocess_exec(*map(str,args),cwd=cwd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE if stdout_only else asyncio.subprocess.STDOUT,start_new_session=True)
    observer=PROCESS_OBSERVER.get()
    identity={'pid':process.pid,'executable':str(args[0]),'instance':uuid.uuid4().hex,'started':time.time(),'active':True}
    if observer: observer(identity)
    try:
        try: output=await asyncio.wait_for(process.communicate(),timeout)
        except BaseException:
            try: os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError: pass
            try: await asyncio.wait_for(process.wait(),5)
            except asyncio.TimeoutError:
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                await process.wait()
            raise
        text=output[0].decode(errors='replace')
        diagnostics=(output[1] or b'').decode(errors='replace') if stdout_only else text
        if sanitize: diagnostics=sanitize(diagnostics)
        if log: log.write_text(diagnostics)
        if process.returncode: raise ProcessFailure(args[0],process.returncode,diagnostics[-2500:])
        if not stdout_only: text=diagnostics
        return text
    finally:
        if observer: observer({**identity,'active':False,'returncode':process.returncode})

def contained(root:Path,relative:str):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError('Path escapes episode directory')
    return path

def checksum(path:Path):
    import hashlib
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

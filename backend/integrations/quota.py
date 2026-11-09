"""Read account limits without an inference request; unknown is never reported as full."""
import asyncio,json,time,math

def remaining_percent(payload,now=None):
    now=time.time() if now is None else now
    values=[]
    for name in ('primary','secondary'):
        window=payload.get(name)
        if not isinstance(window,dict):continue
        reset=window.get('resetsAt')
        if isinstance(reset,(int,float)) and reset<=now:continue
        used=window.get('usedPercent')
        if isinstance(used,(int,float)) and not isinstance(used,bool) and math.isfinite(used) and 0<=used<=100:values.append(100-used)
    return min(values) if values else None

async def codex_limits(executable):
    proc=await asyncio.create_subprocess_exec(executable,'app-server',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    async def send(value):
        proc.stdin.write((json.dumps(value)+'\n').encode());await proc.stdin.drain()
    async def response(expected):
        while True:
            line=await proc.stdout.readline()
            if not line or len(line)>2*1024*1024:raise RuntimeError('No bounded quota response')
            value=json.loads(line)
            if value.get('id')==expected:
                if 'error' in value:raise RuntimeError('Quota unavailable from Codex')
                return value.get('result',{})
    try:
        async with asyncio.timeout(12):
            await send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'liminal_factory','title':'Liminal Factory','version':'0.1.0'}}})
            await response(1);await send({'method':'initialized'})
            await send({'id':2,'method':'account/rateLimits/read'})
            result=await response(2)
            limits=(result.get('rateLimitsByLimitId') or {}).get('codex') or result.get('rateLimits') or {}
            return remaining_percent(limits)
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:await asyncio.wait_for(proc.wait(),2)
            except asyncio.TimeoutError:proc.kill();await proc.wait()

class QuotaRouter:
    def __init__(self,manual_reader=None):
        self.latest={};self.manual_reader=manual_reader or (lambda provider:None);self.locks={}
    async def read(self,provider,executable=None):
        lock=self.locks.setdefault(provider,asyncio.Lock())
        async with lock:
            now=time.time();cached=self.latest.get(provider)
            if cached and now-cached['checked_at']<5 and (cached.get('expires_at') or now+1)>now:return cached['remaining_percent']
            try:remaining=await codex_limits(executable) if provider=='codex' and executable else None
            except (OSError,RuntimeError,ValueError,TimeoutError,ConnectionError):remaining=None
            source='codex-account-rate-limits' if remaining is not None else 'unavailable';expires=None
            if remaining is None:
                manual=self.manual_reader(provider)
                if manual and manual.get('expires_at',0)>time.time():
                    value=manual.get('remaining_percent')
                    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=100:
                        remaining=value;source='manual';expires=manual['expires_at']
            self.latest[provider]={'remaining_percent':remaining,'checked_at':time.time(),'source':source,'expires_at':expires}
            return remaining
    async def choose(self,order,executable=None):
        # Unknown balances and values below 5% are ineligible for every provider, including Kimi.
        for provider in order:
            remaining=await self.read(provider,executable)
            if remaining is not None and remaining>=5:return provider
        return None

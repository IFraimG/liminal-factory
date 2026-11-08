"""External launcher invoked by Antigravity Client's normal CLI button.

This is a separate entry point, never invoked by the production orchestrator. Provider
credentials inherited from Client are forwarded to local Herdr over JSON-RPC stdin,
not through command arguments, shell interpolation, files or printed logs.
"""
import argparse,json,os,re,select,shlex,subprocess,sys,time,uuid
from pathlib import Path
import httpx

class BridgeError(RuntimeError): pass

ENV_NAMES={'HOME','PATH','SHELL','USER','LOGNAME','LANG','LC_ALL','LC_CTYPE','TMPDIR','TERM','COLORTERM',
           'XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','NODE_EXTRA_CA_CERTS','SSL_CERT_FILE','SSL_CERT_DIR',
           'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy'}
ENV_PREFIXES=('AGY_','ANTIGRAVITY_','GEMINI_','GOOGLE_','ANTHROPIC_','OPENAI_')

def inherited_environment(environ):
    # Preserve Client's provider context but not unrelated credentials or Liminal API bearer tokens.
    return {k:v for k,v in environ.items() if k in ENV_NAMES or k.startswith(ENV_PREFIXES)}

def interactive_args(args):
    result=[];i=0
    while i<len(args):
        flag=args[i]
        if flag not in ('--model','--effort') or i+1>=len(args):
            raise BridgeError('Unsupported Client CLI argument. Only interactive model/effort selection is accepted; no secret-bearing settings, print prompts or permission bypasses are forwarded.')
        value=args[i+1]
        if not re.fullmatch(r'[A-Za-z0-9._:/-]{1,200}',value): raise BridgeError('Invalid CLI option value')
        if flag=='--effort' and value not in {'low','medium','high','xhigh','max'}: raise BridgeError('Invalid reasoning effort')
        result += [flag,value];i+=2
    return result

class CoreRPC:
    def __init__(self,executable):
        self.process=subprocess.Popen([str(executable),'connect'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.sequence=0
    def call(self,method,params,timeout=30):
        self.sequence+=1;sequence=self.sequence
        request={'jsonrpc':'2.0','id':sequence,'method':method,'params':params}
        self.process.stdin.write((json.dumps(request)+'\n').encode());self.process.stdin.flush()
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if not select.select([self.process.stdout],[],[],max(0,deadline-time.monotonic()))[0]: break
            line=self.process.stdout.readline(4*1024*1024+1)
            if not line or len(line)>4*1024*1024: raise BridgeError('Herdr bridge closed or returned an oversized response')
            try: response=json.loads(line)
            except ValueError: raise BridgeError('Herdr bridge returned invalid JSON') from None
            if response.get('id')!=sequence: continue
            if response.get('error'): raise BridgeError('Herdr rejected the Client launch. Inspect Herdr; no credential-bearing response was printed.')
            return response.get('result')
        raise BridgeError('Herdr bridge timed out. Check for a newly created pane before clicking CLI again; launch is never retried automatically.')
    def close(self):
        try: self.process.stdin.close()
        except OSError: pass
        try: self.process.wait(timeout=3)
        except subprocess.TimeoutExpired: self.process.kill();self.process.wait()
        self.process.stdout.close()


def launch(hc,agy,cwd,port,args,environ=None,rpc_factory=CoreRPC,health=None):
    hc=Path(hc).expanduser().resolve();agy=Path(agy).expanduser().resolve();cwd=Path(cwd).expanduser().resolve()
    if not hc.is_file() or not agy.is_file() or not cwd.is_dir(): raise BridgeError('Configured Herdr Core, original agy or project directory is missing')
    if not 1024<=port<=65535: raise BridgeError('Invalid local Client proxy port')
    forwarded=interactive_args(args)
    if health is None:
        try:
            response=httpx.get(f'http://127.0.0.1:{port}/health',timeout=3,follow_redirects=False,trust_env=False)
            value=response.json();healthy=response.status_code==200 and isinstance(value,dict) and value.get('status')=='ok'
        except (httpx.HTTPError,ValueError): healthy=False
    else: healthy=health()
    if not healthy: raise BridgeError('Client proxy is not ready. Use the CLI button in Antigravity Client; there is no direct fallback.')
    rpc=rpc_factory(hc)
    try:
        hello=rpc.call('hello',{})
        if not isinstance(hello,dict) or 'terminal.run' not in hello.get('methods',[]):
            raise BridgeError('Herdr Core does not support the required terminal.run RPC')
        result=rpc.call('terminal.run',{
            'argv':[str(agy),*forwarded], 'cwd':str(cwd),
            'env':inherited_environment(os.environ if environ is None else environ),
            'labels':{'liminal_factory':'antigravity-client-launch','launch_id':uuid.uuid4().hex},
            'no_parent':True,'no_notify':True,'outlive_parent':True,'keep':False,'wait':False,
        })
        address=result.get('address','') if isinstance(result,dict) else ''
        if not re.fullmatch(r't[0-9a-z]+',address): raise BridgeError('Herdr did not return a local pane address; inspect Herdr before retrying')
        if result.get('state')=='finished': raise BridgeError('Client CLI exited during startup; inspect its Herdr pane')
        return address
    finally: rpc.close()


def write_launcher(output,backend,hc,agy,cwd,port=8047):
    output=Path(output).expanduser().absolute()
    command=[str(Path(backend).expanduser().resolve()),'--antigravity-client-bridge','--hc',str(Path(hc).expanduser().resolve()),'--agy',str(Path(agy).expanduser().resolve()),'--cwd',str(Path(cwd).expanduser().resolve()),'--port',str(port),'--']
    body='#!/bin/sh\n# Launched by Antigravity Client; contains paths only, never credentials.\nexec '+' '.join(shlex.quote(x) for x in command)+' "$@"\n'
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() or output.is_symlink():
        if output.is_symlink() or output.read_text()!=body: raise BridgeError('Launcher destination already exists with different content; choose a new path')
    else:
        with output.open('x') as file: file.write(body)
    output.chmod(0o700)
    return output


def main(argv=None):
    parser=argparse.ArgumentParser(description='Antigravity Client → Herdr launcher; configure its external file path in Client Settings.')
    parser.add_argument('--hc',required=True);parser.add_argument('--agy',required=True);parser.add_argument('--cwd',required=True);parser.add_argument('--port',type=int,default=8047)
    parser.add_argument('client_args',nargs=argparse.REMAINDER)
    options=parser.parse_args(argv)
    extra=options.client_args
    if extra[:1]==['--']: extra=extra[1:]
    if extra in (['--version'],['--help']):
        print('Liminal Factory Client → Herdr launcher 0.1.0');return
    try:
        address=launch(options.hc,options.agy,options.cwd,options.port,extra)
        print(f'Client CLI is starting in Herdr pane {address}. Open Herdr, then connect this pane in Liminal Factory Settings. No model prompt was sent.')
    except (BridgeError,OSError,ValueError):
        # Never echo raw exception payloads: third-party errors may contain inherited credentials.
        print('Client → Herdr launch could not be confirmed. Check proxy, configured paths and the Herdr pane before retrying. No direct CLI fallback was started.',file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__': main()

"""Create an external launcher; never edits Antigravity Client or its preferences."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.integrations.client_bridge import write_launcher
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',required=True);parser.add_argument('--backend',required=True)
parser.add_argument('--hc',default=str(Path.home()/'.local/bin/hc'));parser.add_argument('--agy',default=str(Path.home()/'.local/bin/agy'))
parser.add_argument('--cwd',required=True);parser.add_argument('--port',type=int,default=8047)
args=parser.parse_args()
print(write_launcher(args.output,args.backend,args.hc,args.agy,args.cwd,args.port))

import subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
python=root/'.venv/bin/python'
if not python.exists(): subprocess.run([sys.executable,'-m','venv',str(root/'.venv')],check=True)
subprocess.run([str(python),'-m','pip','install','-e',str(root)+'[dev]'],check=True)

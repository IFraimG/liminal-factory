import os,subprocess,sys,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['PYINSTALLER_CONFIG_DIR']=str(root/'work/pyinstaller-cache')
# onedir avoids onefile extraction/semaphore requirements and retains all Python native libraries.
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','liminal-backend','--paths',str(root),'--collect-submodules','uvicorn','--collect-submodules','keyring.backends','--add-data',f'{root}/unity-template:unity-template','--distpath',str(root/'work/sidecar'),'--workpath',str(root/'work/pyinstaller'),str(root/'scripts/backend_entry.py')],check=True,cwd=root)
dest=root/'src-tauri/binaries/backend'
if dest.exists(): shutil.rmtree(dest)
shutil.copytree(root/'work/sidecar/liminal-backend',dest)

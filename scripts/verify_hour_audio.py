"""Explicit synthetic-tone stress test; never a production reference or generated music."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from backend.audio.engineer import process_audio
async def main():
    root=Path('work/hour-audio-test');root.mkdir(parents=True,exist_ok=True)
    t=np.arange(48000*5)/48000
    signal=.1*np.sin(2*np.pi*174*t)+.05*np.sin(2*np.pi*261*t)
    src=root/'synthetic.wav';sf.write(src,np.column_stack([signal,signal]),48000)
    report=await process_audio([src],root/'final.wav',3600)
    print(json.dumps(report,indent=2))
    (root/'final.wav').unlink();src.unlink()
asyncio.run(main())

import json
from pathlib import Path
import numpy as np
import soundfile as sf
from backend.models.schema import youtube_url
from backend.integrations.process import run
from backend.media.ffmpeg import probe

async def analyze(root:Path,config,tools):
    youtube_url(config['audio_url'])
    if not config['permission']: raise ValueError('Permission to obtain the audio excerpt is required')
    start=config['start_seconds']; end=start+config['analysis_minutes']*60
    await run([tools('yt-dlp'),'--no-playlist','--no-overwrites','--download-sections',f'*{start}-{end}','--force-keyframes-at-cuts','--socket-timeout','30','--retries','2','--ffmpeg-location',str(Path(tools('ffmpeg')).parent),'-f','bestaudio','-x','--audio-format','mp3','-o',str(root/'reference.%(ext)s'),'--',config['audio_url']],timeout=900,log=root/'download.log')
    path=root/'reference.mp3'
    await run([tools('ffmpeg'),'-y','-v','error','-i',str(path),'-ar','22050','-ac','1',str(root/'analysis.wav')])
    energies=[]; centroids=[]; flux=[]; previous=None
    with sf.SoundFile(root/'analysis.wav') as audio:
        for chunk in audio.blocks(blocksize=2048):
            energies.append(float(np.sqrt(np.mean(chunk**2))))
            spectrum=np.abs(np.fft.rfft(chunk*np.hanning(len(chunk))))
            frequencies=np.fft.rfftfreq(len(chunk),1/audio.samplerate)
            centroids.append(float(np.sum(frequencies*spectrum)/max(1e-12,np.sum(spectrum))))
            if previous is not None and len(previous)==len(spectrum): flux.append(float(np.mean(np.maximum(spectrum-previous,0))))
            previous=spectrum
    envelope=np.array(energies); bpm=None; confidence=0
    if len(envelope)>100:
        onset=np.maximum(np.diff(envelope),0); corr=np.correlate(onset,onset,'full')[len(onset)-1:]
        lo=int(22050/2048*60/180); hi=min(len(corr),int(22050/2048*60/40))
        if hi>lo and corr[0]>1e-12:
            lag=lo+int(np.argmax(corr[lo:hi])); confidence=float(corr[lag]/corr[0]); bpm=60*22050/2048/lag
    report={'methods':['FFprobe','block RMS','FFT spectral centroid','onset-envelope autocorrelation'], 'probe':await probe(path,tools('ffprobe')),'rms_mean':float(np.mean(energies)),'rms_dynamic_range_db':float(20*np.log10((np.percentile(energies,95)+1e-9)/(np.percentile(energies,5)+1e-9))), 'spectral_centroid_hz':float(np.mean(centroids)),'tempo_estimate_bpm':bpm,'tempo_confidence':confidence,'rms_sections':np.array_split(envelope,min(12,len(envelope))) and [float(np.mean(x)) for x in np.array_split(envelope,min(12,len(envelope)))], 'limitations':'Technical measurements only. Tempo may be unreliable for ambient music. No semantic audio or atmosphere recognition was performed.'}
    (root/'audio_analysis.json').write_text(json.dumps(report,indent=2)); return {'artifacts':['reference.mp3','audio_analysis.json']}

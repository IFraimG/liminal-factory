using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.Profiling;
using System;
using System.IO;
using System.Diagnostics;
using System.Threading.Tasks;

// Capture the saved approved scene. Never regenerate or resave its assets.
public static class LiminalRecording {
    [Serializable] class Config {public int width,height,fps;public float seconds;public string ffmpeg,video_path;}
    [Serializable] class Progress {public int frames,total_frames,fps;public double seconds;public long unity_memory_bytes;public string state;}
    static ParticleSystem[] weather;
    static Config config;static Camera camera;static Vector3 origin;static RenderTexture target;
    static Texture2D pixels;static byte[] buffer;static Process encoder;static Task<string> errors;
    static string output;static int frame,total;static bool ending;
    public static void Render() {
        try {
            var args=Environment.GetCommandLineArgs();string configPath=null;
            for(int i=0;i<args.Length-1;i++){if(args[i]=="-lfConfig")configPath=args[i+1];if(args[i]=="-lfOutput")output=args[i+1];}
            config=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
            if(config.width<=0||config.height<=0||config.fps<=0||config.seconds<=0)throw new Exception("Invalid capture dimensions, rate or duration");
            if(SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null)throw new Exception("No graphics device for approved-scene capture");
            Directory.CreateDirectory(output);EditorSceneManager.OpenScene("Assets/Liminal.unity",OpenSceneMode.Single);
            camera=Camera.main;if(!camera)throw new Exception("Approved scene has no MainCamera");origin=camera.transform.position;
            weather=UnityEngine.Object.FindObjectsByType<ParticleSystem>(FindObjectsSortMode.None);foreach(var system in weather)system.Simulate(10,true,true,true);
            total=Mathf.Max(1,Mathf.RoundToInt(config.seconds*config.fps));frame=0;ending=false;
            target=new RenderTexture(config.width,config.height,24,RenderTextureFormat.ARGB32);target.Create();camera.targetTexture=target;
            pixels=new Texture2D(config.width,config.height,TextureFormat.RGB24,false);buffer=new byte[checked(config.width*config.height*3)];
            var start=new ProcessStartInfo(config.ffmpeg){UseShellExecute=false,RedirectStandardInput=true,RedirectStandardError=true};
            foreach(var arg in new[]{"-y","-v","error","-filter_threads","1","-f","rawvideo","-pixel_format","rgb24","-video_size",$"{config.width}x{config.height}","-framerate",config.fps.ToString(),"-i","pipe:0","-vf","vflip","-frames:v",total.ToString(),"-c:v","libx264","-threads","2","-preset","fast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",config.video_path})start.ArgumentList.Add(arg);
            encoder=Process.Start(start);errors=encoder.StandardError.ReadToEndAsync();
            EditorApplication.quitting+=Cleanup;EditorApplication.update+=Tick;Report("recording");
        }catch(Exception exception){Fail(exception);}
    }
    static void Tick() {
        if(ending)return;
        try {
            if(encoder.HasExited)throw new Exception("Encoder exited early: "+errors.GetAwaiter().GetResult());
            // One capture per Editor update allows Unity/Metal to retire native frame resources.
            float phase=2*Mathf.PI*frame/(config.fps*12f);
            camera.transform.position=origin+new Vector3(.012f*Mathf.Sin(phase),.006f*Mathf.Cos(phase),0);
            var previous=RenderTexture.active;
            try {
                foreach(var system in weather)system.Simulate(1f/config.fps,true,false,true);
                camera.Render();RenderTexture.active=target;
                // ReadPixels already updates the CPU copy. Apply would upload it back to the GPU.
                pixels.ReadPixels(new Rect(0,0,config.width,config.height),0,0,false);
                pixels.GetRawTextureData<byte>().CopyTo(buffer);encoder.StandardInput.BaseStream.Write(buffer,0,buffer.Length);
                if(frame==0)File.WriteAllBytes(Path.Combine(output,"frame-00000.png"),pixels.EncodeToPNG());
            }finally{RenderTexture.active=previous;}
            frame++;
            if(frame%config.fps==0)Report("recording");
            if(frame>=total)Finish();
        }catch(Exception exception){Fail(exception);}
    }
    static void Report(string state) {
        var progress=new Progress{frames=frame,total_frames=total,fps=config.fps,seconds=frame/(double)config.fps,unity_memory_bytes=Profiler.GetTotalAllocatedMemoryLong(),state=state};
        string path=Path.Combine(output,"progress.json");File.WriteAllText(path+".tmp",JsonUtility.ToJson(progress));
        if(File.Exists(path))File.Delete(path);File.Move(path+".tmp",path);
        UnityEngine.Debug.Log($"Liminal recording {frame}/{total}; Unity memory {progress.unity_memory_bytes/1048576} MiB");
    }
    static void Finish() {
        ending=true;EditorApplication.update-=Tick;
        try {
            encoder.StandardInput.Close();if(!encoder.WaitForExit(120000))throw new Exception("Encoder did not finish within 120 seconds");
            if(encoder.ExitCode!=0)throw new Exception("Encoder failed: "+errors.GetAwaiter().GetResult());
            Report("completed");File.WriteAllText(Path.Combine(output,"complete.json"),JsonUtility.ToJson(new Progress{frames=frame,total_frames=total,fps=config.fps,seconds=frame/(double)config.fps,state="completed"}));
            Cleanup();EditorApplication.Exit(0);
        }catch(Exception exception){Fail(exception);}
    }
    static void Fail(Exception exception) {
        ending=true;UnityEngine.Debug.LogException(exception);
        try{if(!String.IsNullOrEmpty(output))File.WriteAllText(Path.Combine(output,"error.txt"),exception.ToString());}catch{}
        Cleanup();EditorApplication.Exit(1);
    }
    static void Cleanup() {
        EditorApplication.update-=Tick;EditorApplication.quitting-=Cleanup;
        if(encoder!=null){try{if(!encoder.HasExited)encoder.Kill();}catch{}encoder.Dispose();encoder=null;}
        if(camera)camera.targetTexture=null;
        if(target){target.Release();UnityEngine.Object.DestroyImmediate(target);target=null;}
        if(pixels){UnityEngine.Object.DestroyImmediate(pixels);pixels=null;}buffer=null;
    }
}

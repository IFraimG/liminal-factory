using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using System;
using System.IO;

public static class LiminalScene {
    [Serializable] public class Config { public int width=640,height=360,fps=12; public float seconds=3; public string style="Liminal Space"; public int seed=1701; public float fog_density=.027f,camera_fov=62,column_spacing=9,tint_r=.48f,tint_g=.48f,tint_b=.35f; }
    static Material Mat(Color color) { var m=new Material(Shader.Find("Standard")); m.color=color; m.SetFloat("_Glossiness",.12f); return m; }
    static GameObject Box(string name,Vector3 pos,Vector3 size,Material mat) { var o=GameObject.CreatePrimitive(PrimitiveType.Cube); o.name=name; o.transform.position=pos; o.transform.localScale=size; o.GetComponent<Renderer>().sharedMaterial=mat; return o; }
    public static void Render() {
        string[] args=Environment.GetCommandLineArgs();
        string output="",configPath="";
        for(int i=0;i<args.Length-1;i++) { if(args[i]=="-lfOutput") output=args[i+1]; if(args[i]=="-lfConfig") configPath=args[i+1]; }
        if(String.IsNullOrEmpty(output)) throw new Exception("Missing output directory");
        var c=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        if(SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null) throw new Exception("A working graphics device is required. Do not use -nographics.");
        Directory.CreateDirectory(output); UnityEngine.Random.InitState(c.seed);
        var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        bool cold=c.style=="Coldcore"; bool dream=c.style=="Dreamcore";
        Color tone=new Color(c.tint_r,c.tint_g,c.tint_b);
        RenderSettings.ambientLight=tone*.65f; RenderSettings.fog=true; RenderSettings.fogColor=tone*.8f; RenderSettings.fogDensity=c.fog_density;
        RenderSettings.fogMode=FogMode.ExponentialSquared;
        var wall=Mat(tone); var floor=Mat(tone*.65f);
        // Reproducible terrain without commercial assets.
        var data=new TerrainData(); data.heightmapResolution=33; data.size=new Vector3(180,5,180);
        float[,] heights=new float[33,33]; for(int z=0;z<33;z++) for(int x=0;x<33;x++) heights[z,x]=.02f*Mathf.PerlinNoise(x*.2f,z*.2f);
        data.SetHeights(0,0,heights); var terrain=Terrain.CreateTerrainGameObject(data); terrain.transform.position=new Vector3(-90,-.3f,-20);
        AssetDatabase.DeleteAsset("Assets/LiminalTerrain.asset"); AssetDatabase.CreateAsset(data,"Assets/LiminalTerrain.asset");
        Box("Endless floor",new Vector3(0,-.2f,30),new Vector3(44,.3f,120),floor);
        Box("Left wall",new Vector3(-14,4,30),new Vector3(.4f,8,120),wall);
        Box("Right wall",new Vector3(14,4,30),new Vector3(.4f,8,120),wall);
        for(int z=0;z<12;z++) for(int side=-1;side<=1;side+=2) {
            Box("Column",new Vector3(side*7,3,z*c.column_spacing),new Vector3(1,6,1),wall);
            Box("Lintel",new Vector3(0,6.2f,z*c.column_spacing),new Vector3(15,.4f,1),wall);
        }
        var light=new GameObject("Soft overhead light").AddComponent<Light>(); light.type=LightType.Directional; light.color=new Color(.78f,.85f,1); light.intensity=.8f; light.transform.rotation=Quaternion.Euler(55,-20,0);
        var orb=GameObject.CreatePrimitive(PrimitiveType.Sphere); orb.name="Drifting sphere"; orb.GetComponent<Renderer>().sharedMaterial=Mat(new Color(.7f,.72f,.62f));
        var pulse=new GameObject("Breathing light").AddComponent<Light>(); pulse.type=LightType.Point; pulse.range=25; pulse.color=tone; pulse.transform.position=new Vector3(0,4,15);
        var camera=new GameObject("Camera").AddComponent<Camera>(); camera.transform.position=new Vector3(0,2,-9); camera.transform.rotation=Quaternion.Euler(2,0,0); camera.fieldOfView=c.camera_fov; camera.farClipPlane=160;
        camera.clearFlags=CameraClearFlags.SolidColor; camera.backgroundColor=RenderSettings.fogColor;
        EditorSceneManager.SaveScene(scene,"Assets/Liminal.unity");
        var rt=new RenderTexture(c.width,c.height,24); camera.targetTexture=rt;
        var texture=new Texture2D(c.width,c.height,TextureFormat.RGB24,false);
        int frames=Mathf.Max(1,Mathf.RoundToInt(c.seconds*c.fps));
        for(int frame=0;frame<frames;frame++) {
            float phase=2*Mathf.PI*frame/frames;
            camera.transform.position=new Vector3(.12f*Mathf.Sin(phase),2+.04f*Mathf.Cos(phase),-9);
            orb.transform.position=new Vector3(2*Mathf.Sin(phase),3+.4f*Mathf.Cos(phase),22);
            pulse.intensity=1.6f+.2f*Mathf.Sin(phase); camera.Render(); RenderTexture.active=rt;
            texture.ReadPixels(new Rect(0,0,c.width,c.height),0,0); texture.Apply();
            File.WriteAllBytes(Path.Combine(output,$"frame-{frame:D05}.png"),texture.EncodeToPNG());
        }
        RenderTexture.active=null; camera.targetTexture=null; UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(texture);
        File.WriteAllText(Path.Combine(output,"complete.json"),"{\"frames\":"+frames+"}");
        AssetDatabase.SaveAssets();
    }
}

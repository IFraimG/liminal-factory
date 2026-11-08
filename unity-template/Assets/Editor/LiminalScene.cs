using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using System;
using System.IO;
using System.Diagnostics;

public static class LiminalScene {
    [Serializable] public class Config {
        public int width=640,height=360,fps=12,seed=1701;
        public float seconds=3,fog_density=.012f,camera_fov=62,column_spacing=9,tint_r=.48f,tint_g=.48f,tint_b=.35f;
        public string style="Liminal Space",scene_type="enclosed_corridor",seat_layout="transverse",ffmpeg="",video_path="";
        public float camera_x=.25f,camera_y=1.15f,camera_z=-3,camera_pitch=3,camera_yaw=35,camera_roll=-10;
        public bool include_figure=false;
    }
    static int materialId; static Transform shapeParent;
    static Material Mat(string name,Color color,float roughness=.85f,bool emissive=false) {
        // Generated assets must survive saving/reopening the scene. All surfaces are opaque.
        var shader=Shader.Find(UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline ? "Universal Render Pipeline/Lit" : "Standard");
        if(!shader) throw new Exception("No supported opaque material shader available");
        var m=new Material(shader); m.name=name; color.a=1; m.color=color;
        if(m.HasProperty("_BaseColor")) m.SetColor("_BaseColor",color);
        if(m.HasProperty("_Surface")) m.SetFloat("_Surface",0);
        if(m.HasProperty("_Mode")) m.SetFloat("_Mode",0);
        m.SetFloat("_ZWrite",1); m.SetFloat("_Glossiness",1-roughness); m.renderQueue=-1;
        if(emissive) { m.EnableKeyword("_EMISSION"); m.SetColor("_EmissionColor",color*1.6f); }
        else {
            var tex=new Texture2D(64,64,TextureFormat.RGB24,false); tex.name=name+" wear";
            for(int y=0;y<64;y++) for(int x=0;x<64;x++) {float noise=UnityEngine.Random.Range(.77f,1.06f);tex.SetPixel(x,y,new Color(noise,noise,noise));}
            tex.Apply(); AssetDatabase.CreateAsset(tex,$"Assets/LiminalGenerated/t{materialId}.asset");
            m.mainTexture=tex; m.mainTextureScale=new Vector2(3,3);
        }
        AssetDatabase.CreateAsset(m,$"Assets/LiminalGenerated/m{materialId++}.mat"); return m;
    }
    static GameObject Shape(PrimitiveType type,string name,Vector3 pos,Vector3 size,Material mat) {
        var o=GameObject.CreatePrimitive(type);o.name=name;o.transform.position=pos;o.transform.localScale=size;o.GetComponent<Renderer>().sharedMaterial=mat;if(shapeParent)o.transform.SetParent(shapeParent,true);return o;
    }
    static GameObject Box(string name,Vector3 pos,Vector3 size,Material mat) {return Shape(PrimitiveType.Cube,name,pos,size,mat);}
    static void Pole(string name,Vector3 a,Vector3 b,float radius,Material mat) {
        var o=Shape(PrimitiveType.Cylinder,name,(a+b)/2,new Vector3(radius*2,Vector3.Distance(a,b)/2,radius*2),mat);o.transform.up=(b-a).normalized;
    }
    static void Lamp(Vector3 pos,Material glow) {
        Box("Fluorescent diffuser",pos,new Vector3(.18f,.04f,1.35f),glow);
        var lamp=new GameObject("Ceiling fluorescent light").AddComponent<Light>(); lamp.type=LightType.Point;lamp.transform.position=pos+Vector3.down*.13f;lamp.range=5;lamp.intensity=1.1f;lamp.color=new Color(.9f,.93f,.76f);
    }
    static void Subway(Config c,Material wall,Material floor,Material metal,Material dark,Material seat,Material glow) {
        Box("Ribbed carriage floor",new Vector3(0,-.12f,0),new Vector3(3.3f,.2f,18),floor);
        for(int n=0;n<100;n++) Box("Floor grooves",new Vector3(0,-.012f,-8.9f+n*.18f),new Vector3(3.1f,.008f,.015f),dark);
        Box("Opaque ceiling",new Vector3(0,2.52f,0),new Vector3(3.5f,.18f,18),wall);
        for(int side=-1;side<=1;side+=2) {
            Box("Opaque carriage side",new Vector3(side*1.71f,1.25f,0),new Vector3(.14f,2.5f,18),wall);
            Pole("Ceiling hand rail",new Vector3(side*.8f,2.2f,-8),new Vector3(side*.8f,2.2f,8),.023f,metal);
            for(int n=0;n<6;n++) {
                float z=-7.1f+n*2.85f;
                Box("Window metal frame",new Vector3(side*1.61f,1.64f,z),new Vector3(.09f,1.02f,1.93f),metal);
                Box("Dark opaque window",new Vector3(side*1.55f,1.64f,z),new Vector3(.06f,.86f,1.76f),dark);
                Box("Window horizontal mullion",new Vector3(side*1.50f,1.71f,z),new Vector3(.04f,.025f,1.76f),metal);
                Box("Lower wall trim",new Vector3(side*1.53f,.96f,z),new Vector3(.05f,.06f,2.7f),metal);
                if(c.seat_layout=="longitudinal") {
                    Box("Brown bench cushion",new Vector3(side*1.23f,.49f,z),new Vector3(.69f,.16f,2.45f),seat);
                    Box("Bench backrest",new Vector3(side*1.49f,.78f,z),new Vector3(.15f,.53f,2.45f),seat);
                    Box("Bench base",new Vector3(side*1.23f,.23f,z),new Vector3(.52f,.45f,2.35f),dark);
                    for(int j=0;j<4;j++)Box("Seat seam",new Vector3(side*1.23f,.576f,z-.9f+j*.6f),new Vector3(.65f,.006f,.012f),dark);
                } else {
                    float row=-7.3f+n*2.65f;
                    var pedestal=Mat("Ochre seat pedestal "+side+" "+n,new Color(.34f,.28f,.12f));
                    Box("Transverse bench pedestal",new Vector3(side*1.04f,.25f,row),new Vector3(1.18f,.49f,.56f),pedestal);
                    Box("Transverse double cushion",new Vector3(side*1.04f,.53f,row),new Vector3(1.22f,.14f,.62f),seat);
                    Box("High transverse seat back",new Vector3(side*1.04f,.94f,row+.3f),new Vector3(1.22f,.78f,.12f),seat);
                    Box("Seat back vertical split",new Vector3(side*1.04f,.94f,row+.225f),new Vector3(.025f,.72f,.014f),metal);
                    Box("Seat back outer frame",new Vector3(side*.43f,.94f,row+.3f),new Vector3(.04f,.82f,.16f),metal);
                    Box("Cushion split",new Vector3(side*1.04f,.605f,row),new Vector3(.018f,.012f,.58f),dark);
                }
                Pole("Vertical grab pole",new Vector3(side*.83f,.03f,z+1.3f),new Vector3(side*.83f,2.35f,z+1.3f),.025f,metal);
                Pole("Hanging strap",new Vector3(side*.8f,2.18f,z),new Vector3(side*.8f,1.99f,z),.014f,metal);
                // Segmented closed ring, visible from inside the car.
                for(int j=0;j<12;j++) {
                    float a=j*Mathf.PI/6,b=(j+1)*Mathf.PI/6;
                    Pole("Hanging ring",new Vector3(side*.8f+.085f*Mathf.Cos(a),1.91f+.085f*Mathf.Sin(a),z),new Vector3(side*.8f+.085f*Mathf.Cos(b),1.91f+.085f*Mathf.Sin(b),z),.009f,metal);
                }
                Box("Route sign backing",new Vector3(side*1.57f,2.27f,z),new Vector3(.04f,.16f,1.85f),dark);
                for(int j=0;j<8;j++) Box("Route station marker",new Vector3(side*1.54f,2.27f,z-.7f+j*.2f),new Vector3(.015f,.035f,.055f),wall);
            }
        }
        for(int end=-1;end<=1;end+=2) {
            Box("Carriage end wall",new Vector3(0,1.2f,end*9),new Vector3(3.4f,2.6f,.15f),wall);
            Box("End door frame",new Vector3(0,1.05f,end*8.89f),new Vector3(.94f,2.1f,.08f),metal);
            Box("End door",new Vector3(0,1.05f,end*8.83f),new Vector3(.8f,2,.06f),wall);
            Box("End door dark glass",new Vector3(0,1.53f,end*8.78f),new Vector3(.56f,.69f,.04f),dark);
        }
        for(int n=0;n<7;n++) Lamp(new Vector3(0,2.39f,-7.5f+n*2.5f),glow);
        if(c.include_figure) {
            var figureRoot=new GameObject("Seated hooded figure");figureRoot.transform.position=new Vector3(1.08f,0,.7f);shapeParent=figureRoot.transform;
            var cloth=Mat("Worn olive hooded clothing",new Color(.28f,.29f,.22f));var pants=Mat("Dark worn trousers",new Color(.09f,.10f,.09f));
            var body=Shape(PrimitiveType.Capsule,"Hunched seated torso",new Vector3(1.08f,.98f,.7f),new Vector3(.43f,.39f,.45f),cloth);body.transform.rotation=Quaternion.Euler(-12,0,-15);
            Shape(PrimitiveType.Sphere,"Hood",new Vector3(.84f,1.29f,.7f),new Vector3(.34f,.39f,.34f),cloth);
            Pole("Bent thigh",new Vector3(1.1f,.58f,.55f),new Vector3(.66f,.52f,.55f),.09f,pants);
            Pole("Bent thigh",new Vector3(1.1f,.58f,.88f),new Vector3(.66f,.52f,.88f),.09f,pants);
            Pole("Lower leg",new Vector3(.66f,.52f,.55f),new Vector3(.57f,.13f,.55f),.075f,pants);
            Pole("Lower leg",new Vector3(.66f,.52f,.88f),new Vector3(.57f,.13f,.88f),.075f,pants);
            Pole("Sleeve",new Vector3(.99f,1.16f,.49f),new Vector3(.66f,.71f,.6f),.07f,cloth);
            Pole("Sleeve",new Vector3(.99f,1.16f,.93f),new Vector3(.66f,.71f,.81f),.07f,cloth);
            Pole("Forearm toward hood",new Vector3(.66f,.71f,.6f),new Vector3(.70f,1.2f,.60f),.055f,cloth);
            Pole("Forearm toward hood",new Vector3(.66f,.71f,.81f),new Vector3(.70f,1.2f,.80f),.055f,cloth);
            if(c.seat_layout=="transverse")figureRoot.transform.rotation=Quaternion.Euler(0,-90,0);
            shapeParent=null;
        }
    }
    public static void Render() {
        string[] args=Environment.GetCommandLineArgs();string output="",configPath="";
        for(int i=0;i<args.Length-1;i++) {if(args[i]=="-lfOutput")output=args[i+1];if(args[i]=="-lfConfig")configPath=args[i+1];}
        if(String.IsNullOrEmpty(output))throw new Exception("Missing output directory");
        var c=JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
        if(SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null)throw new Exception("Working graphics device required");
        Directory.CreateDirectory(output);UnityEngine.Random.InitState(c.seed);materialId=0;
        var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        AssetDatabase.DeleteAsset("Assets/LiminalGenerated");AssetDatabase.CreateFolder("Assets","LiminalGenerated");
        Color tone=new Color(c.tint_r,c.tint_g,c.tint_b);
        RenderSettings.ambientMode=UnityEngine.Rendering.AmbientMode.Flat;RenderSettings.ambientLight=new Color(.32f,.33f,.28f);
        RenderSettings.fog=true;RenderSettings.fogColor=tone*.25f;RenderSettings.fogDensity=Mathf.Min(c.fog_density,.012f);RenderSettings.fogMode=FogMode.ExponentialSquared;
        var wall=Mat("Aged opaque cream enamel",Color.Lerp(tone,new Color(.7f,.69f,.53f),.6f));var floor=Mat("Dark worn rubber",new Color(.13f,.14f,.12f));
        var metal=Mat("Dull stainless steel",new Color(.39f,.41f,.37f),.4f);var dark=Mat("Opaque dark inset",new Color(.025f,.033f,.028f));
        var seat=Mat("Worn brown upholstery",new Color(.29f,.21f,.12f));var glow=Mat("Warm fluorescent tube",new Color(.8f,.85f,.65f),.5f,true);
        if(c.scene_type=="subway_car") Subway(c,wall,floor,metal,dark,seat,glow);
        else {
            Box("Enclosed floor",new Vector3(0,-.12f,0),new Vector3(4,.2f,24),floor);Box("Enclosed ceiling",new Vector3(0,3,0),new Vector3(4.2f,.2f,24),wall);
            for(int side=-1;side<=1;side+=2) {Box("Solid corridor wall",new Vector3(side*2,1.5f,0),new Vector3(.2f,3,24),wall);for(int n=0;n<8;n++) {Box("Wall panel seam",new Vector3(side*1.88f,1.45f,-10+n*3),new Vector3(.03f,2.9f,.035f),metal);Box("Recessed door frame",new Vector3(side*1.86f,1.1f,-8+n*3),new Vector3(.06f,2.2f,1),dark);}}
            Box("End wall",new Vector3(0,1.5f,12),new Vector3(4,3,.2f),wall);for(int n=0;n<8;n++)Lamp(new Vector3(0,2.85f,-10+n*3),glow);
        }
        var camera=new GameObject("Camera").AddComponent<Camera>();camera.tag="MainCamera";var origin=new Vector3(c.camera_x,c.camera_y,c.camera_z);camera.transform.position=origin;
        camera.transform.rotation=Quaternion.Euler(c.camera_pitch,c.camera_yaw,c.camera_roll);camera.fieldOfView=c.camera_fov;camera.nearClipPlane=.03f;camera.farClipPlane=80;
        camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.025f,.03f,.025f);
        EditorSceneManager.SaveScene(scene,"Assets/Liminal.unity");AssetDatabase.SaveAssets();
        var rt=new RenderTexture(c.width,c.height,24);camera.targetTexture=rt;var texture=new Texture2D(c.width,c.height,TextureFormat.RGB24,false);
        int frames=Mathf.Max(1,Mathf.RoundToInt(c.seconds*c.fps));Process encoder=null;
        try {
            if(!String.IsNullOrEmpty(c.video_path)) {
                var start=new ProcessStartInfo(c.ffmpeg);start.UseShellExecute=false;start.RedirectStandardInput=true;start.RedirectStandardError=true;
                foreach(var arg in new[]{"-y","-v","error","-f","rawvideo","-pixel_format","rgb24","-video_size",$"{c.width}x{c.height}","-framerate",c.fps.ToString(),"-i","pipe:0","-vf","vflip","-frames:v",frames.ToString(),"-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",c.video_path})start.ArgumentList.Add(arg);
                encoder=Process.Start(start);
            }
            var encoderErrors=encoder?.StandardError.ReadToEndAsync();var buffer=new byte[c.width*c.height*3];
            for(int frame=0;frame<frames;frame++) {
                float phase=2*Mathf.PI*frame/(c.fps*12f);camera.transform.position=origin+new Vector3(.012f*Mathf.Sin(phase),.006f*Mathf.Cos(phase),0);
                camera.Render();RenderTexture.active=rt;texture.ReadPixels(new Rect(0,0,c.width,c.height),0,0);texture.Apply();
                if(encoder!=null) {texture.GetRawTextureData<byte>().CopyTo(buffer);encoder.StandardInput.BaseStream.Write(buffer,0,buffer.Length);}
                if(encoder==null || frame==0)File.WriteAllBytes(Path.Combine(output,$"frame-{frame:D05}.png"),texture.EncodeToPNG());
            }
            if(encoder!=null) {encoder.StandardInput.Close();if(!encoder.WaitForExit(120000))throw new Exception("Video encoder did not finish");if(encoder.ExitCode!=0)throw new Exception("Video encoder failed: "+encoderErrors.Result);}
            File.WriteAllText(Path.Combine(output,"complete.json"),"{\"frames\":"+frames+",\"fps\":"+c.fps+"}");
        } finally {
            if(encoder!=null) {try {if(!encoder.HasExited)encoder.Kill();}finally {encoder.Dispose();}}
            RenderTexture.active=null;camera.targetTexture=null;UnityEngine.Object.DestroyImmediate(rt);UnityEngine.Object.DestroyImmediate(texture);
        }
    }
}

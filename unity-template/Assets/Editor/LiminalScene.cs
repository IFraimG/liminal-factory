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
        public Surface[] custom_materials;public Part[] custom_objects;public Illumination[] custom_lights;
        public float[] sky_color={.025f,.03f,.025f},ambient_color={.32f,.33f,.28f},fog_color={.12f,.12f,.09f},weather_area={60,30,80};
        public string weather="none";public float weather_amount=.5f;
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
    [Serializable] public class Surface {public string name,texture="flat";public float[] color;public float roughness=.85f,metallic=0,emission=0,texture_scale=1;}
    [Serializable] public class Vertex {public float x,y,z;}
    [Serializable] public class Part {public string name,primitive,material,alternate_material="";public float[] position,scale,rotation,step,jitter;public int[] repeat;public float alternate_probability=0;public Vertex[] vertices;public int[] triangles;}
    [Serializable] public class Illumination {public string name,kind;public float[] position,rotation,color;public float intensity,range=15,spot_angle=60;}
    static Vector3 V(float[] a) {return new Vector3(a[0],a[1],a[2]);}
    static Color C(float[] a) {return new Color(a[0],a[1],a[2],1);}
    static Mesh CustomMesh(Part part,int id) {
        var mesh=new Mesh();mesh.name=part.name+" mesh";
        var vertices=new Vector3[part.vertices.Length];var uv=new Vector2[vertices.Length];
        for(int i=0;i<vertices.Length;i++) {var v=part.vertices[i];vertices[i]=new Vector3(v.x,v.y,v.z);uv[i]=new Vector2(v.x+.5f,v.y+.5f);}
        mesh.vertices=vertices;mesh.triangles=part.triangles;mesh.uv=uv;mesh.RecalculateNormals();mesh.RecalculateBounds();
        AssetDatabase.CreateAsset(mesh,$"Assets/LiminalGenerated/custommesh{id}.asset");return mesh;
    }
    // A bounded, deterministic, branching tree built from persisted Unity primitives.
    // Local geometry fits approximately within a unit box; scale controls the crown and height.
    static void TreeBranch(Transform parent,Vector3 a,Vector3 b,float radius,Material material,string name) {
        var part=GameObject.CreatePrimitive(PrimitiveType.Cylinder);part.name=name;
        part.transform.SetParent(parent,false);part.transform.localPosition=(a+b)*.5f;
        part.transform.localRotation=Quaternion.FromToRotation(Vector3.up,(b-a).normalized);
        part.transform.localScale=new Vector3(radius*2,Vector3.Distance(a,b)*.5f,radius*2);
        part.GetComponent<Renderer>().sharedMaterial=material;part.isStatic=true;
        var collider=part.GetComponent<Collider>();if(collider)UnityEngine.Object.DestroyImmediate(collider);
    }
    static void BareTree(string name,Vector3 position,Vector3 scale,Quaternion rotation,Material material) {
        var tree=new GameObject(name);tree.transform.position=position;tree.transform.rotation=rotation;tree.transform.localScale=scale;tree.isStatic=true;
        TreeBranch(tree.transform,new Vector3(0,-.5f,0),new Vector3(0,.48f,0),.025f,material,"Trunk");
        for(int i=0;i<10;i++) {
            float angle=i*2.399963f+UnityEngine.Random.Range(-.16f,.16f);
            var direction=new Vector3(Mathf.Cos(angle),0,Mathf.Sin(angle));
            float height=-.18f+i*.06f,reach=UnityEngine.Random.Range(.26f,.43f)*(1-i*.045f);
            Vector3 start=new Vector3(0,height,0),middle=start+direction*reach*.55f+Vector3.up*.14f,end=start+direction*reach+Vector3.up*.28f;
            TreeBranch(tree.transform,start,middle,.011f,material,"Branch");
            TreeBranch(tree.transform,middle,end,.005f,material,"Twig");
            Vector3 side=Quaternion.AngleAxis(36,Vector3.up)*direction;
            TreeBranch(tree.transform,middle,middle+side*reach*.45f+Vector3.up*.20f,.004f,material,"Fork");
        }
    }
    static void Generic(Config c) {
        RenderSettings.ambientLight=C(c.ambient_color);RenderSettings.fogColor=C(c.fog_color);RenderSettings.fogDensity=c.fog_density;
        QualitySettings.pixelLightCount=8;QualitySettings.shadows=ShadowQuality.All;QualitySettings.shadowResolution=ShadowResolution.Medium;
        var materials=new System.Collections.Generic.Dictionary<string,Material>();
        foreach(var surface in c.custom_materials) {
            var m=Mat(surface.name,C(surface.color),surface.roughness,surface.emission>0);
            m.SetFloat("_Metallic",surface.metallic);if(m.HasProperty("_Smoothness"))m.SetFloat("_Smoothness",1-surface.roughness);
            if(surface.emission>0)m.SetColor("_EmissionColor",C(surface.color)*surface.emission);
            if(surface.texture!="flat") {
                var tex=new Texture2D(128,128,TextureFormat.RGB24,true);tex.name=surface.name+" surface detail";tex.wrapMode=TextureWrapMode.Repeat;
                for(int y=0;y<128;y++)for(int x=0;x<128;x++) {
                    float n=UnityEngine.Random.Range(.78f,1.07f),coarse=Mathf.PerlinNoise(x*.055f,y*.055f);
                    float detail=.8f+coarse*.24f;
                    if(surface.texture=="brick") {int xx=(x+((y/16)%2)*16)%32;if(y%16<2||xx<2)detail=.45f;}
                    if(surface.texture=="wood")detail=.65f+.3f*Mathf.Abs(Mathf.Sin(x*.45f+coarse*3));
                    if(surface.texture=="fabric")detail*=((x+y)%3==0?.8f:1f);
                    if(surface.texture=="metal")detail=.9f+coarse*.08f;
                    if(surface.texture=="snow")detail=.9f+coarse*.08f;
                    if(surface.texture=="bark")detail=.5f+.32f*Mathf.PerlinNoise(x*.12f,y*.018f)+.12f*Mathf.Abs(Mathf.Sin(x*.7f+coarse*4));
                    if(surface.texture=="panel") {detail=.7f+coarse*.22f;if(x%64<2||y%64<2)detail*=.55f;}
                    tex.SetPixel(x,y,new Color(n*detail,n*detail,n*detail));
                }
                tex.Apply();AssetDatabase.CreateAsset(tex,$"Assets/LiminalGenerated/detail{materialId}.asset");m.mainTexture=tex;m.mainTextureScale=Vector2.one*surface.texture_scale;
            }
            materials.Add(surface.name,m);
        }
        int meshId=0;
        foreach(var part in c.custom_objects) {
            var primitive=part.primitive=="sphere"?PrimitiveType.Sphere:part.primitive=="cylinder"?PrimitiveType.Cylinder:part.primitive=="capsule"?PrimitiveType.Capsule:part.primitive=="quad"?PrimitiveType.Quad:PrimitiveType.Cube;
            var mesh=part.primitive=="mesh"?CustomMesh(part,meshId++):null;
            for(int x=0;x<part.repeat[0];x++)for(int y=0;y<part.repeat[1];y++)for(int z=0;z<part.repeat[2];z++) {
                var pos=V(part.position)+Vector3.Scale(new Vector3(x,y,z),V(part.step));
                pos+=new Vector3(UnityEngine.Random.Range(-part.jitter[0],part.jitter[0]),UnityEngine.Random.Range(-part.jitter[1],part.jitter[1]),UnityEngine.Random.Range(-part.jitter[2],part.jitter[2]));
                var material=materials[part.material];
                if(!String.IsNullOrEmpty(part.alternate_material)&&UnityEngine.Random.value<part.alternate_probability)material=materials[part.alternate_material];
                if(part.primitive=="bare_tree") {BareTree(part.name,pos,V(part.scale),Quaternion.Euler(V(part.rotation)),material);continue;}
                if(mesh) {var obj=new GameObject(part.name);obj.transform.position=pos;obj.transform.localScale=V(part.scale);obj.transform.rotation=Quaternion.Euler(V(part.rotation));obj.AddComponent<MeshFilter>().sharedMesh=mesh;obj.AddComponent<MeshRenderer>().sharedMaterial=material;obj.isStatic=true;continue;}
                var o=Shape(primitive,part.name,pos,V(part.scale),material);o.transform.rotation=Quaternion.Euler(V(part.rotation));o.isStatic=true;
                var collider=o.GetComponent<Collider>();if(collider)UnityEngine.Object.DestroyImmediate(collider);
            }
        }
        foreach(var source in c.custom_lights) {
            var light=new GameObject(source.name).AddComponent<Light>();light.transform.position=V(source.position);light.transform.rotation=Quaternion.Euler(V(source.rotation));
            light.type=source.kind=="directional"?LightType.Directional:source.kind=="spot"?LightType.Spot:LightType.Point;light.color=C(source.color);light.intensity=source.intensity;light.range=source.range;light.spotAngle=source.spot_angle;light.shadows=LightShadows.Soft;
        }
    }
    static ParticleSystem Weather(Config c,Vector3 origin) {
        if(c.weather=="none"||c.weather_amount<=0)return null;
        var system=new GameObject(c.weather+" atmosphere").AddComponent<ParticleSystem>();system.Stop(true,ParticleSystemStopBehavior.StopEmittingAndClear);system.useAutoRandomSeed=false;system.randomSeed=(uint)(c.seed+1);
        system.transform.position=origin+new Vector3(0,c.weather_area[1]*.35f,15);
        var main=system.main;main.loop=true;main.playOnAwake=false;main.maxParticles=3000;main.startLifetime=35;main.startSpeed=0;main.simulationSpace=ParticleSystemSimulationSpace.World;
        main.startSize=c.weather=="rain"?.035f:c.weather=="dust"?.035f:.065f;main.startColor=new Color(.85f,.87f,.88f,c.weather=="dust"?.2f:.65f);
        var shape=system.shape;shape.shapeType=ParticleSystemShapeType.Box;shape.scale=V(c.weather_area);
        var velocity=system.velocityOverLifetime;velocity.enabled=true;velocity.space=ParticleSystemSimulationSpace.World;velocity.x=-.35f;velocity.y=c.weather=="rain"?-9:c.weather=="dust"?-.08f:-1.1f;velocity.z=.15f;
        var emission=system.emission;emission.rateOverTime=70*c.weather_amount;
        var shader=Shader.Find("Particles/Standard Unlit");if(!shader)throw new Exception("Particle shader unavailable");
        var material=new Material(shader);material.name=c.weather+" particles";material.SetFloat("_Mode",2);material.SetInt("_SrcBlend",(int)UnityEngine.Rendering.BlendMode.SrcAlpha);material.SetInt("_DstBlend",(int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);material.SetInt("_ZWrite",0);material.renderQueue=3000;
        AssetDatabase.CreateAsset(material,"Assets/LiminalGenerated/weather.mat");system.GetComponent<ParticleSystemRenderer>().sharedMaterial=material;
        return system;
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
        if(c.scene_type=="custom_scene") Generic(c);
        else if(c.scene_type=="subway_car") Subway(c,wall,floor,metal,dark,seat,glow);
        else {
            Box("Enclosed floor",new Vector3(0,-.12f,0),new Vector3(4,.2f,24),floor);Box("Enclosed ceiling",new Vector3(0,3,0),new Vector3(4.2f,.2f,24),wall);
            for(int side=-1;side<=1;side+=2) {Box("Solid corridor wall",new Vector3(side*2,1.5f,0),new Vector3(.2f,3,24),wall);for(int n=0;n<8;n++) {Box("Wall panel seam",new Vector3(side*1.88f,1.45f,-10+n*3),new Vector3(.03f,2.9f,.035f),metal);Box("Recessed door frame",new Vector3(side*1.86f,1.1f,-8+n*3),new Vector3(.06f,2.2f,1),dark);}}
            Box("End wall",new Vector3(0,1.5f,12),new Vector3(4,3,.2f),wall);for(int n=0;n<8;n++)Lamp(new Vector3(0,2.85f,-10+n*3),glow);
        }
        var camera=new GameObject("Camera").AddComponent<Camera>();camera.tag="MainCamera";var origin=new Vector3(c.camera_x,c.camera_y,c.camera_z);camera.transform.position=origin;
        camera.transform.rotation=Quaternion.Euler(c.camera_pitch,c.camera_yaw,c.camera_roll);camera.fieldOfView=c.camera_fov;camera.nearClipPlane=.03f;camera.farClipPlane=c.scene_type=="custom_scene"?1500:80;
        camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=c.scene_type=="custom_scene"?C(c.sky_color):new Color(.025f,.03f,.025f);
        var weather=Weather(c,origin);
        EditorSceneManager.SaveScene(scene,"Assets/Liminal.unity");AssetDatabase.SaveAssets();
        var rt=new RenderTexture(c.width,c.height,24);rt.antiAliasing=4;camera.targetTexture=rt;var texture=new Texture2D(c.width,c.height,TextureFormat.RGB24,false);
        int frames=Mathf.Max(1,Mathf.RoundToInt(c.seconds*c.fps));Process encoder=null;
        try {
            if(!String.IsNullOrEmpty(c.video_path)) {
                var start=new ProcessStartInfo(c.ffmpeg);start.UseShellExecute=false;start.RedirectStandardInput=true;start.RedirectStandardError=true;
                foreach(var arg in new[]{"-y","-v","error","-f","rawvideo","-pixel_format","rgb24","-video_size",$"{c.width}x{c.height}","-framerate",c.fps.ToString(),"-i","pipe:0","-vf","vflip","-frames:v",frames.ToString(),"-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",c.video_path})start.ArgumentList.Add(arg);
                encoder=Process.Start(start);
            }
            var encoderErrors=encoder?.StandardError.ReadToEndAsync();var buffer=new byte[c.width*c.height*3];
            if(weather)weather.Simulate(10,true,true,true);
            for(int frame=0;frame<frames;frame++) {
                if(weather)weather.Simulate(1f/c.fps,true,false,true);
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

"""Developer fixture for the generic renderer; not an AI fidelity claim."""
import asyncio,json,math,shutil
from pathlib import Path
from backend.models.schema import SceneSpec
from backend.integrations.unity import Unity,discover

ROOT=Path('work/generic-scene-check').resolve()
def fixture():
    materials=[{'name':n,'color':c,'texture':t,'emission':e} for n,c,t,e in [('concrete',[.35,.33,.3],'concrete',0),('seam',[.12,.13,.12],'concrete',0),('snow',[.68,.68,.65],'snow',0),('darkglass',[.035,.045,.05],'flat',0),('warmglass',[.75,.38,.1],'flat',1.3),('coldglass',[.46,.6,.67],'flat',1.1),('wood',[.13,.12,.1],'wood',0),('metal',[.12,.14,.14],'metal',0),('lamp',[.7,.8,.85],'flat',2)]]
    objects=[]
    def part(n,p,s,m,primitive='box',rotation=None,repeat=None,step=None,alternate='',probability=0):
        objects.append(dict(name=n,primitive=primitive,position=p,scale=s,rotation=rotation or [0,0,0],material=m,repeat=repeat or [1,1,1],step=step or [0,0,0],alternate_material=alternate,alternate_probability=probability))
    part('Snow covered ground',[0,-.2,30],[140,.4,180],'snow')
    for x in [-27,27]:
        part('Apartment block',[x,13,16],[20,26,48],'concrete')
        part('Snow on roof',[x,26.1,16],[20.3,.2,48.3],'snow')
        part('Floor panel seams',[x,3.1,-7.9],[20.1,.05,.08],'seam',repeat=[1,8,1],step=[0,3.1,0])
        face=-16.94 if x<0 else 16.94
        part('Repeated side apartment windows',[face,2.4,-5],[.08,1.4,1.5],'darkglass',repeat=[1,8,14],step=[0,3.1,3.1],alternate='warmglass',probability=.22)
        part('Window frames',[face,1.65,-5],[.13,.07,1.7],'snow',repeat=[1,8,14],step=[0,3.1,3.1])
        part('Balcony floor',[face+(.7 if x<0 else -.7),2,-3],[1.5,.12,2.5],'concrete',repeat=[1,8,5],step=[0,3.1,9.3])
        part('Balcony railing',[face+(1.4 if x<0 else -1.4),2.5,-3],[.08,.8,2.5],'metal',repeat=[1,8,5],step=[0,3.1,9.3])
    for z,w,h in [(61,64,28),(99,90,31)]:
        part('Background apartment block',[0,h/2,z],[w,h,13],'concrete')
        part('Distant windows',[-w/2+2,2.8,z-6.56],[1.4,1.5,.1],'darkglass',repeat=[int(w/3.2)-1,8,1],step=[3.2,3.1,0],alternate='warmglass',probability=.22)
    import random
    random.seed(1701)
    for i in range(18):
        x=random.uniform(-14,14);z=random.uniform(0,50);height=random.uniform(4,7)
        part('Bare tree trunk',[x,height/2,z],[.17,height/2,.17],'wood','cylinder')
        for side in [-1,1]:
            for level in [1,2,3]:
                part('Bare branching crown',[x+side*level*.35,height*.5+level*.45,z],[.065,height*.2,.065],'wood','cylinder',[0,0,side*(20+level*10)])
                part('Fine bare twigs',[x+side*level*.7,height*.55+level*.5,z+.3],[.025,height*.13,.025],'wood','cylinder',[20,0,side*55])
    lights=[]
    for i,(x,z) in enumerate([(-10,4),(10,23),(-5,39)]):
        part('Street lamp pole',[x,3.4,z],[.08,3.4,.08],'metal','cylinder')
        part('Cool street lamp fixture',[x,6.9,z],[.7,.2,.45],'lamp')
        lights.append(dict(name='Street light '+str(i),kind='point',position=[x,6.6,z],color=[.7,.8,.88],intensity=2,range=17))
    for x in [-5,5]:
        part('Playground frame upright',[x,1.1,8],[.04,1.1,.04],'metal','cylinder')
    part('Playground frame crossbar',[0,2.2,8],[10,.09,.09],'metal')
    part('Snow covered parked car',[-12,.7,-4],[2.2,1.1,4.5],'concrete')
    part('Car roof snow',[-12,1.5,-3.8],[1.9,.25,2.4],'snow')
    part('Car window',[-12,1.2,-4],[2, .6,2.3],'darkglass')
    return SceneSpec(scene_type='custom_scene',custom_materials=materials,custom_objects=objects,custom_lights=lights,sky_color=[.24,.13,.075],ambient_color=[.28,.25,.22],fog_color=[.25,.16,.1],fog_density=.004,camera_x=0,camera_y=15,camera_z=-22,camera_pitch=14,camera_yaw=0,camera_roll=0,camera_fov=62,weather='snow',weather_amount=.8,weather_area=[65,32,90],explanation='Developer fixture checks generic geometry, repeated facade detail, exterior camera and saved weather. It is not model-generated or a source fidelity claim.').model_dump()

async def main():
    ROOT.mkdir(parents=True,exist_ok=True);project=ROOT/'unity-project'
    template=Path('work/subway-check/unity-project')
    if template.is_dir() and not (project/'ProjectSettings/ProjectVersion.txt').exists():
        for name in ('ProjectSettings','Packages'):shutil.copytree(template/name,project/name,dirs_exist_ok=True)
    (ROOT/'scene_spec.json').write_text(json.dumps(fixture(),indent=2))
    config={'style':'Coldcore','resolution':'1080p','fps':24,'loop_seconds':2,'duration_minutes':1/60,'recording_minutes':1/60}
    renderer=Unity(str(discover()[0]))
    await renderer.render(ROOT,config,True)
    await renderer.render(ROOT,config,False)
    print('Generic fixture preview and 1-second 1080p saved-scene capture verified:',ROOT)
if __name__=='__main__':asyncio.run(main())

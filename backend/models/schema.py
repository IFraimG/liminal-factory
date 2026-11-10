from typing import Literal
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import re
from pydantic import BaseModel, Field, field_validator, model_validator

class Status(StrEnum):
    pending='Pending'; running='Running'; waiting_client='Waiting for Client'; waiting_quota='Waiting for quota'; waiting_cli='Waiting for CLI'; waiting_permission='Waiting for Permission'; waiting='Waiting for Approval'; approved='Approved'; failed='Failed'; completed='Completed'; cancelled='Cancelled'

def youtube_url(value: str, channel=False):
    p=urlparse(value)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None,443) or p.hostname not in {'youtube.com','www.youtube.com','m.youtube.com','youtu.be'}:
        raise ValueError('Use an HTTPS URL on youtube.com or youtu.be')
    if channel:
        if p.hostname=='youtu.be' or not re.fullmatch(r'/(@[\w.\-]+|channel/UC[\w\-]{22})/?',p.path):
            raise ValueError('Channel URL must use /@handle or /channel/UC…')
    else:
        video=p.path.strip('/') if p.hostname=='youtu.be' else parse_qs(p.query).get('v',[''])[0] if p.path=='/watch' else ''
        if not re.fullmatch(r'[\w\-]{11}',video): raise ValueError('A valid YouTube video ID is required')
    return value

class EpisodeInput(BaseModel):
    name: str=Field(min_length=1,max_length=120)
    audio_url: str
    channel_url: str
    start_seconds: float=Field(default=0,ge=0,le=86400)
    analysis_minutes: float=Field(default=5,gt=0,le=30)
    permission: bool=True
    duration_minutes: float=Field(default=60,gt=0,le=180)
    recording_minutes: float|None=Field(default=None,gt=0,le=180)
    unity_planning_enabled: bool=True
    channel_review_enabled: bool=True
    postproduction_enabled: bool=True
    presentation_minutes: float|None=Field(default=None,gt=0,le=180)
    presentation_mode: Literal['video','image']='video'
    resolution: str='1080p'
    image_resolution: Literal['1920x1080','2560x1440','3840x2160']='1920x1080'
    agent_guidance: str=Field(default='',max_length=8000)
    fps: int=24
    audio_mode: str='Seamless Loop'
    audio_gain_db: float=Field(default=0,ge=-24,le=12)
    audio_fade_seconds: float=Field(default=0,ge=0,le=30)
    loop_seconds: int=Field(default=12,ge=2,le=120)
    style: str='Liminal Space'
    output_directory: str=''
    agent_priorities: dict[str,list[str]]=Field(default_factory=dict)
    @field_validator('agent_guidance')
    @classmethod
    def guidance_text(cls,value):return value.strip()
    @field_validator('agent_priorities')
    @classmethod
    def priorities(cls,value):
        from backend.orchestration.priorities import validate_order
        from backend.orchestration.workflow import ALL_TASKS,GATES
        if set(value)-(ALL_TASKS-GATES):raise ValueError('Agent priority requires an executable pipeline step')
        return {name:validate_order(order) for name,order in value.items()}
    @field_validator('audio_url')
    @classmethod
    def video(cls,v): return youtube_url(v)
    @field_validator('channel_url')
    @classmethod
    def channel(cls,v): return youtube_url(v,True)
    @model_validator(mode='after')
    def choices(self):
        if self.resolution not in {'1080p','1440p','4K'} or self.fps not in {24,30,60}: raise ValueError('Unsupported output settings')
        if self.audio_mode not in {'Seamless Loop','Ambient Evolution','Multi-track','Variational Extend'}: raise ValueError('Unsupported audio mode')
        if self.style not in {'Liminal Space','Dreamcore','Coldcore','Surreal Ambient'}: raise ValueError('Unsupported style')
        return self

class Settings(BaseModel):
    working_directory: str=''
    max_concurrent_agents: int=Field(default=3,ge=1,le=8)
    agent_kind: str='codex'
    antigravity_port: int=Field(default=8047,ge=1024,le=65535)
    antigravity_wait_seconds: int=Field(default=300,ge=10,le=1800)
    model: str=''
    vision_enabled: bool=False
    appearance: str='dark'
    yt_dlp_use_chrome_cookies: bool=False
    yt_dlp_chrome_profile: str=''
    cache_hours: int=Field(default=24,ge=0,le=720)
    tools: dict[str,str]=Field(default_factory=dict)
    agent_models: dict[str,str]=Field(default_factory=dict)
    @field_validator('yt_dlp_chrome_profile')
    @classmethod
    def chrome_profile(cls,v):
        if v and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}',v): raise ValueError('Use a Chrome profile folder name, not a path or browser options')
        return v
    @field_validator('agent_kind')
    @classmethod
    def kind(cls,v):
        if v not in {'codex','gemini','antigravity','kimi'}: raise ValueError('Use codex or antigravity')
        return v

class SunoOptions(BaseModel):
    exclude_styles: str=Field(min_length=1,max_length=1000)
    weirdness: int=Field(ge=0,le=100)
    style_influence: int=Field(ge=0,le=100)
    variety: Literal['off','normal','high','extra','max']
    duration_seconds: int=Field(ge=30,le=600)
    max_mode: bool
    personalize: Literal['off']
    vocal_gender: Literal['none']
    rationale: str=Field(min_length=20,max_length=2000)

class MusicBrief(BaseModel):
    brief: str=Field(min_length=10)
    prompts: list[str]=Field(min_length=2,max_length=8)
    suno_options: SunoOptions|None=None

class SunoMusicBrief(MusicBrief):
    suno_options: SunoOptions

class VisualBrief(BaseModel):
    architecture: str
    composition: str
    palette: list[str]
    lighting: str
    camera: str
    landscape: str
    atmosphere: str
    materials: list[str]
    animations: list[str]
class Metadata(BaseModel):
    titles: list[str]=Field(min_length=5,max_length=5)
    recommended: str
    description: str
    hashtags: str
    @model_validator(mode='after')
    def valid(self):
        if len(set(t.casefold() for t in self.titles))!=5 or self.recommended not in self.titles: raise ValueError('Five unique titles and a recommendation required')
        if not re.fullmatch(r'#[A-Za-z0-9_]+(?:, #[A-Za-z0-9_]+)*',self.hashtags): raise ValueError('Hashtags must be #tag, #tag')
        return self

class SceneMaterial(BaseModel):
    model_config={'extra':'forbid'}
    name: str=Field(min_length=1,max_length=80)
    color: list[float]=Field(min_length=3,max_length=3)
    roughness: float=Field(default=.85,ge=0,le=1)
    metallic: float=Field(default=0,ge=0,le=1)
    emission: float=Field(default=0,ge=0,le=5)
    texture: Literal['flat','plaster','concrete','brick','wood','metal','fabric','snow','asphalt','bark','panel']='flat'
    texture_scale: float=Field(default=1,gt=0,le=50)
    @field_validator('color')
    @classmethod
    def rgb(cls,v):
        if any(not 0<=x<=1 for x in v):raise ValueError('RGB must be within 0..1')
        return v

class MeshVertex(BaseModel):
    model_config={'extra':'forbid'}
    x: float=Field(ge=-.5,le=.5,allow_inf_nan=False)
    y: float=Field(ge=-.5,le=.5,allow_inf_nan=False)
    z: float=Field(ge=-.5,le=.5,allow_inf_nan=False)

class SceneObject(BaseModel):
    model_config={'extra':'forbid'}
    name: str=Field(min_length=1,max_length=120)
    primitive: Literal['box','sphere','cylinder','capsule','quad','bare_tree','mesh']
    position: list[float]=Field(min_length=3,max_length=3)
    scale: list[float]=Field(min_length=3,max_length=3)
    rotation: list[float]=Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    material: str
    alternate_material: str=''
    alternate_probability: float=Field(default=0,ge=0,le=1)
    repeat: list[int]=Field(default_factory=lambda:[1,1,1],min_length=3,max_length=3)
    step: list[float]=Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    jitter: list[float]=Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    vertices: list[MeshVertex]=Field(default_factory=list,max_length=256)
    triangles: list[int]=Field(default_factory=list,max_length=1536)
    @model_validator(mode='after')
    def bounded(self):
        import math
        if any(not math.isfinite(x) or abs(x)>500 for x in self.position+self.step+self.jitter):raise ValueError('Object coordinates must be finite and within 500m')
        if any(not math.isfinite(x) or not .001<=x<=500 for x in self.scale):raise ValueError('Object scale must be 0.001..500m')
        if any(not math.isfinite(x) or abs(x)>360 for x in self.rotation):raise ValueError('Rotation must be finite degrees')
        if any(not 1<=x<=100 for x in self.repeat) or math.prod(self.repeat)>2000:raise ValueError('Repeat budget exceeded')
        if any(abs(self.position[i])+abs(self.step[i])*(self.repeat[i]-1)+abs(self.jitter[i])>500 for i in range(3)):raise ValueError('Repeated geometry extends beyond 500m')
        if self.primitive=='mesh':
            if len(self.vertices)<3 or len(self.triangles)<3 or len(self.triangles)%3:raise ValueError('Mesh needs vertices and complete triangles')
            if any(i<0 or i>=len(self.vertices) for i in self.triangles):raise ValueError('Mesh triangle index out of bounds')
            if any(len(set(self.triangles[i:i+3]))!=3 for i in range(0,len(self.triangles),3)):raise ValueError('Mesh triangles must have distinct vertex indices')
        elif self.vertices or self.triangles:raise ValueError('Mesh data is only valid for mesh objects')
        return self

class SceneLight(BaseModel):
    model_config={'extra':'forbid'}
    name: str=Field(min_length=1,max_length=80)
    kind: Literal['point','spot','directional']
    position: list[float]=Field(min_length=3,max_length=3)
    rotation: list[float]=Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    color: list[float]=Field(min_length=3,max_length=3)
    intensity: float=Field(ge=0,le=8)
    range: float=Field(default=15,gt=0,le=150)
    spot_angle: float=Field(default=60,ge=1,le=170)
    @model_validator(mode='after')
    def bounded(self):
        import math
        if any(not math.isfinite(x) or abs(x)>500 for x in self.position+self.rotation):raise ValueError('Light coordinates must be finite and within limits')
        if any(not 0<=x<=1 for x in self.color):raise ValueError('Light RGB must be within 0..1')
        return self

class SceneSpec(BaseModel):
    seed: int=Field(default=1701,ge=0,le=1000000)
    fog_density: float=Field(default=.027,ge=0,le=.08)
    camera_fov: float=Field(default=62,ge=35,le=90)
    column_spacing: float=Field(default=9,ge=5,le=12)
    tint_r: float=Field(default=.48,ge=.1,le=.85)
    tint_g: float=Field(default=.48,ge=.1,le=.85)
    tint_b: float=Field(default=.35,ge=.1,le=.85)
    scene_type: Literal['subway_car','enclosed_corridor','custom_scene']='enclosed_corridor'
    seat_layout: Literal['longitudinal','transverse']='transverse'
    camera_x: float=Field(default=.25,ge=-100,le=100)
    camera_y: float=Field(default=1.15,ge=.5,le=40)
    camera_z: float=Field(default=-3,ge=-100,le=100)
    camera_pitch: float=Field(default=3,ge=-85,le=85)
    camera_yaw: float=Field(default=35,ge=-180,le=180)
    camera_roll: float=Field(default=-10,ge=-25,le=25)
    include_figure: bool=False
    custom_materials: list[SceneMaterial]=Field(default_factory=list,max_length=64)
    custom_objects: list[SceneObject]=Field(default_factory=list,max_length=400)
    custom_lights: list[SceneLight]=Field(default_factory=list,max_length=32)
    ground_continuation: Literal['auto','off']='auto'
    sky_color: list[float]=Field(default_factory=lambda:[.025,.03,.025],min_length=3,max_length=3)
    ambient_color: list[float]=Field(default_factory=lambda:[.32,.33,.28],min_length=3,max_length=3)
    fog_color: list[float]=Field(default_factory=lambda:[.12,.12,.09],min_length=3,max_length=3)
    weather: Literal['none','snow','rain','dust']='none'
    weather_amount: float=Field(default=.5,ge=0,le=1)
    weather_area: list[float]=Field(default_factory=lambda:[60,30,80],min_length=3,max_length=3)
    @model_validator(mode='after')
    def custom_scene_valid(self):
        import math
        for vector in (self.sky_color,self.ambient_color,self.fog_color):
            if any(not 0<=x<=1 for x in vector):raise ValueError('Environment RGB must be within 0..1')
        if any(not 1<=x<=200 for x in self.weather_area):raise ValueError('Weather area must be 1..200m')
        names=[m.name for m in self.custom_materials]
        if len(names)!=len(set(names)):raise ValueError('Material names must be unique')
        if sum(math.prod(o.repeat)*(32 if o.primitive=='bare_tree' else 1) for o in self.custom_objects)>6000:raise ValueError('Scene object budget exceeds 6000 instances including tree branches')
        if sum(len(o.vertices) for o in self.custom_objects)>12000:raise ValueError('Scene mesh vertex budget exceeds 12000')
        if any(o.material not in names or (o.alternate_material and o.alternate_material not in names) for o in self.custom_objects):raise ValueError('Object uses an undefined material')
        if self.scene_type=='custom_scene' and (not self.custom_objects or not self.custom_materials):raise ValueError('Custom scene needs actual geometry and materials')
        return self
    explanation: str=Field(min_length=10)

class SceneDesign(SceneSpec):
    seat_layout: Literal['longitudinal','transverse']
    scene_type: Literal['subway_car','enclosed_corridor','custom_scene']
    camera_x: float=Field(ge=-100,le=100)
    camera_y: float=Field(ge=.5,le=40)
    camera_z: float=Field(ge=-100,le=100)
    camera_pitch: float=Field(ge=-85,le=85)
    camera_yaw: float=Field(ge=-180,le=180)
    camera_roll: float=Field(ge=-25,le=25)
    include_figure: bool

class UnityBlueprint(BaseModel):
    model_config={'extra':'forbid'}
    scene_type: Literal['subway_car','enclosed_corridor','custom_scene','unsupported']
    reference_observations: str=Field(min_length=100,max_length=6000)
    geometry_and_layout: str=Field(min_length=100,max_length=6000)
    materials_and_surface_detail: str=Field(min_length=80,max_length=5000)
    lighting_and_color: str=Field(min_length=80,max_length=5000)
    camera_and_composition: str=Field(min_length=80,max_length=4000)
    atmosphere_and_motion: str=Field(min_length=60,max_length=4000)
    implementation_prompt: str=Field(min_length=1000,max_length=24000)
    fidelity_checks: list[str]=Field(min_length=6,max_length=24)
    limitations: list[str]=Field(min_length=1,max_length=20)

class UnityFidelityCheck(BaseModel):
    criterion: str=Field(min_length=3,max_length=1000)
    passed: bool
    observation: str=Field(min_length=10,max_length=2000)

class UnityFidelityReport(BaseModel):
    reference_category: str=Field(min_length=3,max_length=500)
    rendered_category: str=Field(min_length=3,max_length=500)
    category_matches: bool
    checks: list[UnityFidelityCheck]=Field(min_length=6,max_length=24)
    summary: str=Field(min_length=30,max_length=4000)
    limitations: list[str]=Field(min_length=1,max_length=20)

class UnityBlueprintRequest(BaseModel):
    feedback: str=Field(default='',max_length=8000)

class RecordingPlan(BaseModel):
    duration_minutes: float=Field(gt=0,le=180)
    fps: Literal[24,30,60]
    resolution: Literal['1080p','1440p','4K']
    camera: Literal['approved_scene_camera']
    explanation: str=Field(min_length=20,max_length=3000)

class StepPreparation(BaseModel):
    model_config={'extra':'forbid'}
    task: str=Field(min_length=1,max_length=80)
    summary: str=Field(min_length=10,max_length=2000)
    checks: list[str]=Field(min_length=1,max_length=6)
    @field_validator('checks')
    @classmethod
    def bounded_checks(cls,values):
        if any(not 3<=len(v)<=500 for v in values):raise ValueError('Use short concrete checks')
        return values


def step_preparation_schema(task):
    from pydantic import create_model
    from backend.orchestration.priorities import LOCAL_TASKS
    if task not in LOCAL_TASKS:raise ValueError('Preparation requires a local execution step')
    return create_model(task+'Preparation',__base__=StepPreparation,task=(Literal[task],...))


RevisionScope=Literal['unity_scene','visual_analysis','recording','music_brief','audio_processing','metadata']
class RevisionConfig(BaseModel):
    model_config={'extra':'forbid'}
    resolution: Literal['1080p','1440p','4K']|None=None
    fps: Literal[24,30,60]|None=None
    recording_minutes: float|None=Field(default=None,gt=0,le=180)
    audio_mode: Literal['Seamless Loop','Ambient Evolution','Multi-track','Variational Extend']|None=None
    audio_gain_db: float|None=Field(default=None,ge=-24,le=12)
    audio_fade_seconds: float|None=Field(default=None,ge=0,le=30)
class RevisionChange(BaseModel):
    model_config={'extra':'forbid'}
    scope: RevisionScope
    instruction: str=Field(min_length=3,max_length=8000)
    allowed_fields: list[str]=Field(default_factory=list,max_length=30)
class RevisionPlan(BaseModel):
    model_config={'extra':'forbid'}
    changes: list[RevisionChange]=Field(max_length=6)
    config_updates: RevisionConfig
    explanation: str=Field(min_length=10,max_length=3000)
    needs_clarification: bool
    clarification: str=Field(max_length=3000)
    @model_validator(mode='after')
    def actionable(self):
        if not self.needs_clarification and not self.changes:raise ValueError('Select a minimal affected scope')
        if self.needs_clarification and not self.clarification.strip():raise ValueError('Explain which information is missing')
        return self
class RevisionInput(BaseModel):
    prompt: str=Field(min_length=3,max_length=8000)
    provider: Literal['codex','antigravity','kimi']='codex'
    scope: Literal['auto','unity_scene','visual_analysis','recording','music_brief','audio_processing','metadata']='auto'
    @field_validator('prompt')
    @classmethod
    def prompt_text(cls,value):
        value=value.strip()
        if len(value)<3:raise ValueError('Describe the requested changes')
        return value

class RevisionReply(BaseModel):
    model_config={'extra':'forbid'}
    question_id: str=Field(min_length=1,max_length=100)
    answer: str=Field(min_length=1,max_length=8000)
    @field_validator('answer')
    @classmethod
    def answer_text(cls,value):
        value=value.strip()
        if not value:raise ValueError('Enter an answer')
        return value


class PresentationInput(BaseModel):
    mode: Literal['video','image']='video'
    minutes: float=Field(default=60,gt=0,le=180)
    prompt: str=Field(default='',max_length=8000)
    @model_validator(mode='after')
    def needs_prompt(self):
        self.prompt=self.prompt.strip()
        if self.mode=='image' and len(self.prompt)<3:raise ValueError('Describe the requested image edit')
        return self

class ImageEditResult(BaseModel):
    model_config={'extra':'forbid'}
    image_path: str=Field(min_length=1,max_length=300)
    description: str=Field(min_length=10,max_length=3000)

class ChannelTitleCandidate(BaseModel):
    model_config={'extra':'forbid'}
    video_id: str=Field(pattern=r'^[A-Za-z0-9_-]{11}$')
    title: str=Field(min_length=1,max_length=500)
    reason: str=Field(min_length=3,max_length=1200)

class ChannelMetadataPlan(BaseModel):
    model_config={'extra':'forbid'}
    candidates: list[ChannelTitleCandidate]=Field(min_length=1,max_length=5)
    hashtags: str=Field(min_length=2,max_length=1500)
    description: str=Field(max_length=5000)
    @model_validator(mode='after')
    def validate_plan(self):
        if len({c.video_id for c in self.candidates})!=len(self.candidates):raise ValueError('Use unique source videos')
        if len({c.title.casefold() for c in self.candidates})!=len(self.candidates):raise ValueError('Use unique proposed titles')
        if not re.fullmatch(r'#[\w]+(?:, #[\w]+)*',self.hashtags):raise ValueError('Use one line: #ambient, #darkambient, #coldcore; no spaces inside a hashtag')
        tags=self.hashtags.split(', ')
        if len(tags)>20 or len({t.casefold() for t in tags})!=len(tags):raise ValueError('Use at most 20 unique hashtags')
        return self

class ChannelReviewRequest(BaseModel):
    model_config={'extra':'forbid'}
    action: Literal['search','refine']='search'
    feedback: str=Field(default='',max_length=8000)
    expected_round_id: str|None=None
    video_id: str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{11}$')
    @model_validator(mode='after')
    def valid_feedback(self):
        self.feedback=self.feedback.strip()
        if self.action=='refine' and len(self.feedback)<3:raise ValueError('Describe the requested title correction')
        return self

class ChannelTitleApproval(BaseModel):
    model_config={'extra':'forbid'}
    round_id: str
    expected_round_id: str
    video_id: str=Field(pattern=r'^[A-Za-z0-9_-]{11}$')

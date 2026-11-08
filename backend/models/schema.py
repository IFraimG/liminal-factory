from typing import Literal
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import re
from pydantic import BaseModel, Field, field_validator, model_validator

class Status(StrEnum):
    pending='Pending'; running='Running'; waiting_client='Waiting for Client'; waiting_cli='Waiting for CLI'; waiting_permission='Waiting for Permission'; waiting='Waiting for Approval'; approved='Approved'; failed='Failed'; completed='Completed'; cancelled='Cancelled'

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
    permission: bool=False
    duration_minutes: float=Field(default=60,gt=0,le=180)
    recording_minutes: float|None=Field(default=None,gt=0,le=180)
    resolution: str='1080p'
    fps: int=24
    audio_mode: str='Seamless Loop'
    loop_seconds: int=Field(default=12,ge=2,le=120)
    style: str='Liminal Space'
    output_directory: str=''
    @field_validator('audio_url')
    @classmethod
    def video(cls,v): return youtube_url(v)
    @field_validator('channel_url')
    @classmethod
    def channel(cls,v): return youtube_url(v,True)
    @model_validator(mode='after')
    def choices(self):
        if self.resolution not in {'1080p','1440p','4K'} or self.fps not in {24,30,60}: raise ValueError('Unsupported output settings')
        if self.audio_mode not in {'Seamless Loop','Ambient Evolution','Multi-track'}: raise ValueError('Unsupported audio mode')
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

class SceneSpec(BaseModel):
    seed: int=Field(default=1701,ge=0,le=1000000)
    fog_density: float=Field(default=.027,ge=.005,le=.08)
    camera_fov: float=Field(default=62,ge=35,le=90)
    column_spacing: float=Field(default=9,ge=5,le=12)
    tint_r: float=Field(default=.48,ge=.1,le=.85)
    tint_g: float=Field(default=.48,ge=.1,le=.85)
    tint_b: float=Field(default=.35,ge=.1,le=.85)
    scene_type: Literal['subway_car','enclosed_corridor']='enclosed_corridor'
    seat_layout: Literal['longitudinal','transverse']='transverse'
    camera_x: float=Field(default=.25,ge=-1.4,le=1.4)
    camera_y: float=Field(default=1.15,ge=.5,le=2.2)
    camera_z: float=Field(default=-3,ge=-7,le=7)
    camera_pitch: float=Field(default=3,ge=-30,le=30)
    camera_yaw: float=Field(default=35,ge=-180,le=180)
    camera_roll: float=Field(default=-10,ge=-25,le=25)
    include_figure: bool=False
    explanation: str=Field(min_length=10)

class SceneDesign(SceneSpec):
    seat_layout: Literal['longitudinal','transverse']
    scene_type: Literal['subway_car','enclosed_corridor']
    camera_x: float=Field(ge=-1.4,le=1.4)
    camera_y: float=Field(ge=.5,le=2.2)
    camera_z: float=Field(ge=-7,le=7)
    camera_pitch: float=Field(ge=-30,le=30)
    camera_yaw: float=Field(ge=-180,le=180)
    camera_roll: float=Field(ge=-25,le=25)
    include_figure: bool

class RecordingPlan(BaseModel):
    duration_minutes: float=Field(gt=0,le=180)
    fps: Literal[24,30,60]
    resolution: Literal['1080p','1440p','4K']
    camera: Literal['approved_scene_camera']
    explanation: str=Field(min_length=20,max_length=3000)

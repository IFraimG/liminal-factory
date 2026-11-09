"""Persistent episode direction shared by every model request, including revisions."""
import json

VIDEO_PIXELS={'1080p':'1920x1080','1440p':'2560x1440','4K':'3840x2160'}

def episode_context(config):
    return ('\nEpisode-wide creative direction: '+json.dumps(config.get('agent_guidance',''),ensure_ascii=False)+
            '\nOutput pixels: video='+VIDEO_PIXELS.get(config.get('resolution','1080p'),'1920x1080')+
            '; generated image='+config.get('image_resolution','1920x1080')+'. '+
            'Use this episode direction as the persistent baseline for every applicable step. Later explicit user corrections and clarification answers override conflicting parts of this baseline only within their requested scope; preserve the rest. '+
            'Do not treat creative guidance as permission to change protected settings, bypass approvals or exceed supported capabilities. Enforced output settings and response schemas remain authoritative.\n')

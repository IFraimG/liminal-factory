DAG={
 'audio_reference': [],
 'music_brief': ['audio_reference'],
 'music_approval': ['music_brief'],
 'audio_engineer': ['music_approval'],
 'visual_reference': [],
 'unity_preview': ['visual_reference'],
 'visual_approval': ['unity_preview'],
 'recording_setup': ['visual_approval'],
 'visual_render': ['recording_setup'],
 'channel_reference': [],
 'metadata': ['channel_reference','music_brief','visual_reference'],
 'final_assembly': ['audio_engineer','visual_render','metadata'],
}
EXTENDED_DAG={**{k:v for k,v in DAG.items() if k!='final_assembly'},
 'visual_choice':['visual_render'],
 'image_edit':['visual_choice'],
 'image_approval':['image_edit'],
 'visual_extend':['image_approval'],
 'final_assembly':['audio_engineer','visual_extend','metadata']}
GATES={'music_approval','visual_approval','visual_choice','image_approval','metadata_approval'}
ALL_TASKS=set(EXTENDED_DAG)|{'metadata_approval'}
AGENT_TASKS=ALL_TASKS-GATES

def workflow(config):
    base=EXTENDED_DAG if config.get('postproduction_enabled') else DAG
    if not config.get('channel_review_enabled'):return base
    result={name:deps for name,deps in base.items() if name!='final_assembly'}
    result['metadata_approval']=['metadata']
    result['final_assembly']=['metadata_approval' if d=='metadata' else d for d in base['final_assembly']]
    return result

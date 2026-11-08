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
GATES={'music_approval','visual_approval'}
AGENT_TASKS={'music_brief','visual_reference','metadata'}

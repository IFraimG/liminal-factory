"""The audio branch knows its target before a visual source is selected."""
def extension_settings(config):
    minutes=config.get('presentation_minutes') or config.get('duration_minutes',60)
    mode='Variational Extend' if config.get('postproduction_enabled') else config.get('audio_mode','Seamless Loop')
    return minutes,mode

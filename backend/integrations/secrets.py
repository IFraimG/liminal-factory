import sys

def secret(name,value=None):
    if name not in {'youtube_api_key'}: raise ValueError('Unknown credential')
    if sys.platform!='darwin': raise RuntimeError('Credentials require macOS Keychain')
    # Explicit native backend; never fall back to a plaintext keyring implementation.
    from keyring.backends.macOS import Keyring
    ring=Keyring()
    if value is not None:
        if value: ring.set_password('dev.liminal.factory',name,value)
        else:
            try: ring.delete_password('dev.liminal.factory',name)
            except Exception: pass
        return None
    return ring.get_password('dev.liminal.factory',name)

"""Deterministic yt-dlp invocation and redaction of credential-bearing output."""
import re
from urllib.parse import urlsplit,urlunsplit

def chrome_cookie_args(enabled=False,profile=''):
    if not enabled: return []
    if profile and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}',profile):
        raise ValueError('Use a Chrome profile folder name such as Default or Profile 1, not a path or browser options')
    return ['--cookies-from-browser','chrome'+(':'+profile if profile else '')]

def redact_download_output(text):
    text=re.sub(r'(?i)((?:set-cookie|cookie|authorization|proxy-authorization|x-api-key)\s*:\s*)[^\r\n]+',r'\1[redacted]',text)
    def clean_url(match):
        try:
            p=urlsplit(match.group(0));host=p.netloc.rsplit('@',1)[-1]
            return urlunsplit((p.scheme,host,p.path,'[redacted]' if p.query else '', ''))
        except ValueError: return '[redacted URL]'
    return re.sub(r'https?://[^\s<>]+',clean_url,text)

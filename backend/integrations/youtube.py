"""Public channel metadata via yt-dlp; no YouTube Data API credential needed."""
import json,time
from urllib.parse import urlparse
from backend.models.schema import youtube_url
from backend.integrations.process import run
from backend.integrations.download import chrome_cookie_args,redact_download_output

async def channel_titles(url,executable,store,cache_hours=24,chrome_cookies=False,chrome_profile=''):
    youtube_url(url,True)
    # Use the root channel: yt-dlp discovers its public videos, shorts and streams
    # tabs and follows continuations. Never limit extraction to the first page.
    channel='https://www.youtube.com/'+urlparse(url).path.strip('/')
    cache_key='yt-dlp:channel:v1:'+channel
    cached=store.rows('SELECT * FROM cache WHERE key=?',(cache_key,))
    if cached and time.time()-cached[0]['created']<cache_hours*3600:
        return json.loads(cached[0]['data'])
    raw=await run([executable,'--ignore-config','--no-cache-dir',
        *chrome_cookie_args(chrome_cookies,chrome_profile),
        '--flat-playlist','--skip-download','--dump-single-json','--abort-on-error',
        '--socket-timeout','30','--retries','2','--extractor-retries','2',
        '--',channel],timeout=900,stdout_only=True,sanitize=redact_download_output)
    try: data=json.loads(raw)
    except (ValueError,TypeError): raise RuntimeError('yt-dlp returned invalid channel metadata') from None
    titles=[]; seen=set()
    def visit(item):
        if not isinstance(item,dict): raise RuntimeError('yt-dlp returned invalid channel entries')
        if 'entries' in item:
            entries=item['entries']
            if not isinstance(entries,list): raise RuntimeError('yt-dlp returned incomplete channel entries')
            for entry in entries: visit(entry)
            return
        title=item.get('title'); identity=item.get('id')
        if not identity or not isinstance(title,str) or not title.strip():
            raise RuntimeError('yt-dlp returned an incomplete video entry')
        if title in ('Deleted video','Private video') or item.get('availability') in ('private','premium_only','subscriber_only'): return
        if identity in seen: return
        seen.add(identity); titles.append(title)
    visit(data)
    if not titles: raise RuntimeError('No public channel titles found; check the channel URL and Chrome session')
    store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(cache_key,json.dumps(titles),time.time()))
    return titles

async def channel_videos(url,executable,store,cache_hours=24,chrome_cookies=False,chrome_profile=''):
    """Keep verified video IDs/title provenance for the title-review workflow."""
    import re
    youtube_url(url,True);channel='https://www.youtube.com/'+urlparse(url).path.strip('/');key='yt-dlp:channel:videos:v1:'+channel
    cached=store.rows('SELECT * FROM cache WHERE key=?',(key,))
    if cached and time.time()-cached[0]['created']<cache_hours*3600:return json.loads(cached[0]['data'])
    raw=await run([executable,'--ignore-config','--no-cache-dir',*chrome_cookie_args(chrome_cookies,chrome_profile),'--flat-playlist','--skip-download','--dump-single-json','--abort-on-error','--socket-timeout','30','--retries','2','--extractor-retries','2','--',channel],timeout=900,stdout_only=True,sanitize=redact_download_output)
    try:payload=json.loads(raw)
    except (ValueError,TypeError):raise RuntimeError('yt-dlp returned invalid channel metadata') from None
    videos=[];seen=set()
    def visit(item):
        if not isinstance(item,dict):raise RuntimeError('Incomplete channel entry')
        if 'entries' in item:
            if not isinstance(item['entries'],list):raise RuntimeError('Incomplete channel entries')
            for child in item['entries']:visit(child)
            return
        if item.get('availability') in ('private','premium_only','subscriber_only') or item.get('title') in ('Deleted video','Private video'):return
        identity=item.get('id','');title=item.get('title')
        if not isinstance(identity,str) or not re.fullmatch(r'[\w-]{11}',identity,flags=re.ASCII) or not isinstance(title,str) or not title.strip():raise RuntimeError('Channel video has no valid ID/title')
        if identity not in seen:
            seen.add(identity);videos.append({'video_id':identity,'title':title,'url':'https://www.youtube.com/watch?v='+identity})
    visit(payload)
    if not videos:raise RuntimeError('No public channel videos found')
    store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(key,json.dumps(videos),time.time()));return videos

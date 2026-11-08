import json,time
import httpx
from urllib.parse import urlparse
from backend.models.schema import youtube_url

async def channel_titles(url,key,store,cache_hours=24):
    youtube_url(url,True)
    cached=store.rows('SELECT * FROM cache WHERE key=?',(url,))
    if cached and time.time()-cached[0]['created']<cache_hours*3600: return json.loads(cached[0]['data'])
    if not key: raise RuntimeError('YouTube API key missing. Enable YouTube Data API v3 in Google Cloud and save a restricted API key in Settings → YouTube (macOS Keychain).')
    async with httpx.AsyncClient(timeout=30) as client:
        async def get(resource,params):
            # Do not propagate httpx exceptions containing the credential-bearing URL.
            try:
                r=await client.get('https://www.googleapis.com/youtube/v3/'+resource,params={**params,'key':key})
                if r.status_code!=200: raise RuntimeError(f'YouTube API returned HTTP {r.status_code}; verify key/quota')
                return r.json()
            except httpx.HTTPError: raise RuntimeError('YouTube API network request failed') from None
        path=urlparse(url).path.strip('/')
        query={'forHandle':path[1:]} if path.startswith('@') else {'id':path.split('/')[1]}
        channels=await get('channels',{'part':'contentDetails',**query})
        if not channels.get('items'): raise RuntimeError('Channel not found')
        playlist=channels['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        titles=[]; token=''; seen=set()
        while True:
            data=await get('playlistItems',{'part':'snippet','playlistId':playlist,'maxResults':50,**({'pageToken':token} if token else {})})
            titles += [i['snippet']['title'] for i in data.get('items',[]) if i['snippet']['title'] not in ('Deleted video','Private video')]
            token=data.get('nextPageToken','')
            if not token: break
            if token in seen: raise RuntimeError('YouTube pagination returned a repeated token')
            seen.add(token)
    store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(url,json.dumps(titles),time.time()))
    return titles

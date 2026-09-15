"""Check public delivery after commit; never generate audio or change spend."""
import datetime,json,os,pathlib,time,urllib.request,urllib.parse,xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
BASE='https://ayeprinz.github.io/the-forge'
FEED=BASE+'/feed.xml'
ROOT=pathlib.Path(__file__).parent

def verify(date):
    ep=json.loads((ROOT/'scripts'/f'{date}.json').read_text())
    expected=BASE+'/audio/'+ep.get('audio_file',f'{date}.mp3')
    req=urllib.request.Request(FEED,headers={'Cache-Control':'no-cache','User-Agent':'Forge-delivery-check'})
    with urllib.request.urlopen(req,timeout=30) as r: xml=r.read()
    items=[i for i in ET.fromstring(xml).findall('./channel/item') if i.findtext('guid')==date]
    if len(items)!=1:raise ValueError('Public feed does not yet contain exactly one matching episode')
    item=items[0];enc=item.find('enclosure')
    if item.findtext('title')!=ep['title'] or enc is None or enc.get('url')!=expected:raise ValueError('Public feed has stale metadata or enclosure')
    local=ROOT/'docs'/'audio'/ep.get('audio_file',f'{date}.mp3')
    size=local.stat().st_size
    if int(enc.get('length','0'))!=size:raise ValueError('Enclosure length differs from generated audio')
    with urllib.request.urlopen(urllib.request.Request(expected,method='HEAD'),timeout=30) as r:
        if r.status!=200 or int(r.headers.get('Content-Length','0'))!=size:raise ValueError('Public audio unavailable or wrong size')
    duration=item.findtext('{http://www.itunes.com/dtds/podcast-1.0.dtd}duration')
    return {'date':date,'title':ep['title'],'url':expected,'bytes':size,'duration':duration,'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}

if __name__=='__main__':
    date=os.environ.get('EPISODE_DATE') or datetime.datetime.now(ZoneInfo('Europe/London')).date().isoformat()
    last=None
    for attempt in range(40):
        try: result=verify(date);break
        except Exception as e:
            last=e;print(f'Waiting for public delivery ({attempt+1}/40): {type(e).__name__}: {e}',flush=True)
            if attempt<39:time.sleep(15)
    else:raise SystemExit(f'PUBLICATION NOT VERIFIED: {last}; do not rerender paid audio')
    payload=urllib.parse.urlencode({'urlprefix':FEED}).encode()
    with urllib.request.urlopen(urllib.request.Request('https://overcast.fm/ping',data=payload,method='POST'),timeout=30) as r:result['overcast_ping']=r.read().decode().strip()
    print(json.dumps(result,indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('\n## Public delivery verified\n\n'+json.dumps(result,indent=2)+'\n')

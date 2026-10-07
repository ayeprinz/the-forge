"""Preserve one complete episode with integrity hashes before Git publication."""
import datetime,hashlib,json,os,pathlib,shutil
from zoneinfo import ZoneInfo
root=pathlib.Path(__file__).parent
slug=os.environ.get('EPISODE_DATE') or datetime.datetime.now(ZoneInfo('Europe/London')).date().isoformat()
ep=json.loads((root/'scripts'/f'{slug}.json').read_text())
name=ep.get('audio_file',f'{slug}.mp3')
assert pathlib.Path(name).name==name
files=[f'docs/audio/{name}',f'docs/{slug}-audio-check.json','docs/feed.xml']
report=json.loads((root/files[1]).read_text())
assert report['date']==slug and not report['usage']['uncertain'] and report['usage']['usd']<=2
out=root/'delivery';out.mkdir(exist_ok=True)
manifest={'date':slug,'script_sha256':hashlib.sha256((root/'scripts'/f'{slug}.json').read_bytes()).hexdigest(),'files':{}}
for name in files:
    src=root/name;dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
    manifest['files'][name]=hashlib.sha256(src.read_bytes()).hexdigest()
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Complete audio, report and feed packaged before publication.')

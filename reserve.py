"""Reserve a complete episode allowance durably before calling the audio API."""
import datetime, json, os, pathlib, subprocess
from zoneinfo import ZoneInfo
root=pathlib.Path(__file__).parent
slug=os.environ.get('EPISODE_DATE') or datetime.datetime.now(ZoneInfo('Europe/London')).date().isoformat()
ep=json.loads((root/'scripts'/f'{slug}.json').read_text())
if (root/'docs/audio'/ep.get('audio_file',f'{slug}.mp3')).exists():
 print('Existing audio, no paid reservation needed');raise SystemExit(0)
p=root/'audio-ledger.json'
ledger=json.loads(p.read_text()) if p.exists() else {'currency':'USD','month_cap':60,'reservations':{'2026-09-13':{'reserved_usd':2,'month':'2026-09','status':'legacy-unreconciled'}}}
operation=ep.get('revision',slug)
if operation!=slug and operation!='2026-09-13-r2':raise RuntimeError('Revision needs a separate explicit allowance')
if operation in ledger['reservations']:raise RuntimeError('Already reserved; recover existing clips and reconcile before another paid attempt')
month=datetime.datetime.now(ZoneInfo('Europe/London')).strftime('%Y-%m')
used=sum(v['reserved_usd'] for v in ledger['reservations'].values() if v['month']==month)
if used+2>ledger['month_cap']:raise RuntimeError('Monthly allowance exhausted')
ledger['reservations'][operation]={'reserved_usd':2,'month':month,'status':'reserved','run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT']}
p.write_text(json.dumps(ledger,indent=2)+'\n')
subprocess.run(['git','add','audio-ledger.json'],check=True)
subprocess.run(['git','commit','-m',f'Reserve audio allowance for {operation}'],check=True)
subprocess.run(['git','push'],check=True)
print('Durable allowance reserved. Failed and uncertain attempts remain counted.')

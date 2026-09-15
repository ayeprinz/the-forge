"""Reject missing/unreviewed new lessons before reservation or speech requests."""
import datetime,hashlib,json,os,pathlib,re
from zoneinfo import ZoneInfo
from build import validate_script

def check(root,date):
    path=root/'scripts'/f'{date}.json'
    if not path.exists():
        raise ValueError(f'MISSING SCRIPT: {date}. Preparation must upload a complete reviewed lesson; no audio allowance reserved.')
    ep=validate_script(path)
    audio=root/'docs'/'audio'/ep.get('audio_file',f'{date}.mp3')
    if audio.is_file():
        return 'existing',ep
    turns=ep['turns']; words=sum(len(t['t'].split()) for t in turns)
    if not 7000<=words<=8000:
        raise ValueError(f'NOT READY: {words} spoken words; ordinary main lesson requires 7000 to 8000 substantive words and editorial review.')
    if any(len(t['t'])>1200 or len(t['i'])>500 for t in turns):
        raise ValueError('A paid speech request exceeds its stricter limits')
    if {t['v'] for t in turns}!={'ash','sage'} or sum(t.get('pause_after')==7 for t in turns)!=5:
        raise ValueError('Both voices and five seven-second recall pauses required')
    if not re.match(r'^\[[^\]]+\] ',ep['title']):
        raise ValueError('Bracketed subject required')
    review=ep.get('editorial_review',{})
    digest=hashlib.sha256('\n'.join(t['t'] for t in turns).encode()).hexdigest()
    required={'subject-first','distinct-explanations','worked-arithmetic','source-support','dialogue-continuity','five-recall-answers','practical-application'}
    if review.get('status')!='approved' or review.get('sha256')!=digest or review.get('spoken_words')!=words or not required.issubset(review.get('checks',[])) or not review.get('source_urls'):
        raise ValueError('Missing or stale editorial review. Length alone is not approval.')
    return 'ready',ep

if __name__=='__main__':
    root=pathlib.Path(__file__).parent
    date=os.environ.get('EPISODE_DATE') or datetime.datetime.now(ZoneInfo('Europe/London')).date().isoformat()
    state,ep=check(root,date)
    print(f'{date}: {state}; spending guards remain unchanged')

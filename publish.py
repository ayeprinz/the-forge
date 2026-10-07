"""Retry Git publication only. Never render audio, force push, or rewrite history."""
import subprocess,time

def git(*args):
    return subprocess.run(['git',*args],capture_output=True,text=True)

def publish(delays=(0,10,30,60),run=git,sleep=time.sleep):
    for delay in delays:
        if delay: sleep(delay)
        pushed=run('push','origin','HEAD:main')
        if pushed.returncode==0:
            print('Publication commit pushed successfully');return
        # A dropped response can hide a successful push. Check before retrying.
        fetched=run('fetch','origin','main')
        if fetched.returncode==0:
            included=run('merge-base','--is-ancestor','HEAD','origin/main')
            if included.returncode==0:
                print('Publication commit already present remotely');return
        print('::warning::GitHub publication failed; retrying the same commit without new speech.')
    raise RuntimeError('GitHub publication failed after bounded retries. Complete audio artifact preserved. Re-run the failed publication job only.')

if __name__=='__main__':publish()

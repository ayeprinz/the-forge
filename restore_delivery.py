"""Restore a verified delivery artifact, with no speech API access."""
import hashlib,json,pathlib,shutil,os
root=pathlib.Path(__file__).parent
package=root/'delivery';manifest=json.loads((package/'manifest.json').read_text())
slug=manifest['date']
if os.environ.get('EPISODE_DATE'): assert slug==os.environ['EPISODE_DATE'],'Artifact date mismatch'
assert hashlib.sha256((root/'scripts'/f'{slug}.json').read_bytes()).hexdigest()==manifest['script_sha256'],'Script changed since recording'
for name,digest in manifest['files'].items():
    path=pathlib.PurePosixPath(name)
    assert not path.is_absolute() and '..' not in path.parts and path.parts[0]=='docs'
    src=package/name;assert hashlib.sha256(src.read_bytes()).hexdigest()==digest
    dest=root/name
    if dest.exists() and name.endswith('.mp3'):
        assert hashlib.sha256(dest.read_bytes()).hexdigest()==digest,'Existing audio differs; stop rather than overwrite'
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
# Rebuild with the current checkout so unrelated feed entries are retained.
import build
build.build_feed()
print('Verified saved episode restored without speech calls.')

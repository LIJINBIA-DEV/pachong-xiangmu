"""Install the temporary US deployment through verified SSH; secrets use stdin."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REMOTE = r'''
import hashlib,json,os,pathlib,subprocess,sys,tarfile
root=pathlib.Path('/opt/mediacrawler-temp-us')
assert root.is_dir() and root.resolve()==root
payload=json.load(sys.stdin)
env_path=root/'.env.server'
assert not env_path.exists(), 'Refusing to replace deployment credentials'
manifest=json.loads((root/'deployment/source-manifest.json').read_text())
archive=root/'deployment/source.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256']
expected={row['path']:row for row in manifest['files']}
with tarfile.open(archive) as tar:
    assert {member.name for member in tar.getmembers()}==set(expected)
    for member in tar.getmembers():
        assert member.isfile() and not pathlib.PurePosixPath(member.name).is_absolute()
        target=(root/member.name).resolve()
        assert root in target.parents
        content=tar.extractfile(member).read()
        assert hashlib.sha256(content).hexdigest()==expected[member.name]['sha256']
        target.parent.mkdir(parents=True,exist_ok=True)
        assert not target.exists(), 'Refusing to overwrite an existing source file'
        target.write_bytes(content)
        target.chmod(member.mode & 0o777)
ids=subprocess.check_output(['docker','ps','-aq'],text=True).split()
rows=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
before=[{'id':r['Id'],'name':r['Name'],'image':r['Image'],
         'started':r['State']['StartedAt'],'running':r['State']['Running']} for r in rows]
(root/'deployment/containers-before.json').write_text(json.dumps(before,indent=2))
for variable,reference in [('NODE_IMAGE','node:24-bookworm-slim'),
                           ('PYTHON_IMAGE','python:3.11-slim-bookworm')]:
    image=json.loads(subprocess.check_output(['docker','image','inspect',reference],text=True))[0]
    assert image['Architecture']=='amd64'
    payload[variable]=next(d for d in image['RepoDigests'] if d.startswith(reference.split(':')[0]+'@'))
payload.update(APP_BIND_IP='127.0.0.1',APP_PORT='18180',APP_UID='1000',APP_GID='1000',
               APP_IMAGE='mediacrawler-temp-us-app:local',APP_CPUS='2.0',APP_MEMORY_LIMIT='4g',
               BUILD_PIP_INDEX='https://pypi.org/simple',BUILD_DEBIAN_MIRROR='http://deb.debian.org/debian',
               APP_DATA_DIR='./docker/runtime/data',APP_BROWSER_DIR='./docker/runtime/browser_data',
               APP_LOG_DIR='./docker/runtime/logs')
assert all('\n' not in value and '\r' not in value and '$' not in value for value in payload.values())
for folder in ('data','browser_data','logs'):
    target=root/'docker/runtime'/folder
    target.mkdir(parents=True,exist_ok=False)
    target.chmod(0o750);os.chown(target,1000,1000)
descriptor=os.open(env_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(descriptor,'w') as output:
    for key,value in payload.items(): output.write(key+'='+json.dumps(value)+'\n')
print(json.dumps({'verified_source_files':len(manifest['files']),
                  'existing_containers_recorded':len(before),'env_mode':oct(env_path.stat().st_mode & 0o777),
                  'siliconflow_key_configured':bool(payload['SILICONFLOW_API_KEY']),
                  'jev_key_configured':bool(payload['TYPESAFE_API_KEY'])}))
'''


def main():
    from dotenv import dotenv_values
    from image_subject_settings import runtime_settings
    key = runtime_settings(ROOT / 'data')['api_key']
    if not key:
        raise ValueError('SiliconFlow key unavailable')
    existing = dotenv_values(ROOT / '.env') if (ROOT / '.env').exists() else {}
    values = {'SILICONFLOW_API_KEY': key,
              'TYPESAFE_API_KEY': os.environ.get('TYPESAFE_API_KEY') or existing.get('TYPESAFE_API_KEY') or ''}
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        'temp-us-server', 'python3 -c '+shlex.quote(REMOTE)], input=json.dumps(values),
        text=True, capture_output=True, check=True, timeout=90)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

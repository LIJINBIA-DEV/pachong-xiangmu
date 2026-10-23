"""Send existing API credentials over verified SSH stdin, never stdout or argv."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REMOTE = r'''
import hashlib,json,os,pathlib,subprocess,sys,tarfile
root=pathlib.Path('/home/jc/mediacrawler-spark')
payload=json.load(sys.stdin)
assert root.is_dir() and root.resolve()==root
env_path=root/'.env.spark'
assert not env_path.exists(), 'Refusing to replace an existing deployment config'
manifest=json.loads((root/'deployment/source-manifest.json').read_text())
archive=root/'deployment/source.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256']
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        assert member.isfile() and not pathlib.PurePosixPath(member.name).is_absolute()
        assert root in (root/member.name).resolve().parents
    tar.extractall(root,filter='data')
for row in manifest['files']:
    assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256']
ids=subprocess.check_output(['docker','ps','-aq'],text=True).split()
rows=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
before=[{'id':r['Id'],'name':r['Name'],'image':r['Image'],
         'started':r['State']['StartedAt'],'running':r['State']['Running']} for r in rows]
(root/'deployment/before.json').write_text(json.dumps(before,indent=2))
processes=subprocess.check_output(['ps','-eo','pid,lstart,comm'],text=True)
(root/'deployment/processes-before.txt').write_text(processes)
for variable,reference in [('NODE_IMAGE','docker.m.daocloud.io/library/node:24-bookworm-slim'),
                           ('PYTHON_IMAGE','docker.m.daocloud.io/library/python:3.11-slim-bookworm')]:
    image=json.loads(subprocess.check_output(['docker','image','inspect',reference],text=True))[0]
    assert image['Architecture']=='arm64'
    payload[variable]=next(d for d in image['RepoDigests'] if d.startswith(reference.split(':')[0]+'@'))
payload.update(SPARK_BIND_IP='192.168.30.168',APP_PORT='18180',APP_UID=str(os.getuid()),APP_GID=str(os.getgid()),
               APP_CPUS='2.0',APP_MEMORY_LIMIT='8g',SPARK_DATA_DIR='./docker/runtime/data',
               SPARK_BROWSER_DIR='./docker/runtime/browser_data',SPARK_LOG_DIR='./docker/runtime/logs')
assert all('\n' not in value and '\r' not in value for value in payload.values())
descriptor=os.open(env_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(descriptor,'w') as output:
    for key,value in payload.items():
        output.write(key+'='+value+'\n')
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
        raise ValueError('SiliconFlow key unavailable; no deployment credentials sent')
    existing = dotenv_values(ROOT / '.env') if (ROOT / '.env').exists() else {}
    values = {'SILICONFLOW_API_KEY': key,
              'TYPESAFE_API_KEY': os.environ.get('TYPESAFE_API_KEY') or existing.get('TYPESAFE_API_KEY') or ''}
    # Quote only the program, which contains no credentials. The JSON payload is stdin.
    import shlex
    completed = subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        'spark-xiaozhuji','python3 -c '+shlex.quote(REMOTE)],input=json.dumps(values),
        text=True,capture_output=True,check=True,timeout=60)
    print(completed.stdout.strip())


if __name__ == '__main__':
    main()

"""Isolated temporary vision service, reusing existing weights read-only."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

OUT=Path(os.environ.get('CUTE_COMPARE_OUTPUT',str(Path(__file__).resolve().parents[1]/'artifacts/model-compare-20261013'))).resolve()
REMOTE='/home/jc/mediacrawler-model-compare-20261013'
def ssh(code):
    p=subprocess.run(['ssh','-o','ConnectTimeout=10','spark-xiaozhuji','python3 -c '+shlex.quote(code)],capture_output=True,text=True,encoding='utf-8',timeout=30)
    if p.returncode: raise RuntimeError(p.stderr[-2000:])
    return json.loads(p.stdout)

parser=argparse.ArgumentParser();parser.add_argument('--stop',action='store_true');parser.add_argument('--status',action='store_true');args=parser.parse_args()
if args.stop:
    owned=json.loads((OUT/'spark-trial-service.json').read_text(encoding='utf-8'))
    expected_pid=int(owned['pid'])
    result=ssh(f'''import os,pathlib,json,signal
root=pathlib.Path({REMOTE!r}); p=int((root/'server.pid').read_text())
assert p=={expected_pid}, 'Temporary PID no longer belongs to this comparison run'
cmd=pathlib.Path('/proc/'+str(p)+'/cmdline')
if cmd.exists():
    actual=cmd.read_bytes()
    assert b'qwen36-27b-vision-compare' in actual and b'18636' in actual
    os.kill(p,signal.SIGTERM)
print(json.dumps({{'stopped_trial_pid':p}}))''')
elif args.status:
    result=ssh(f'''import pathlib,json,urllib.request
root=pathlib.Path({REMOTE!r}); result={{'pid':(root/'server.pid').read_text() if (root/'server.pid').exists() else None}}
try:
    with urllib.request.urlopen('http://127.0.0.1:18636/health',timeout=5) as r: result['health']=json.load(r)
except Exception as e: result['health_error']=type(e).__name__
result['log_tail']=(root/'server.log').read_text(errors='replace')[-3500:] if (root/'server.log').exists() else ''
print(json.dumps(result))''')
else:
    before=ssh('''import subprocess,json
ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
items=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
print(json.dumps([{'id':x['Id'],'name':x['Name'],'image':x['Image'],'started':x['State']['StartedAt'],'running':x['State']['Running']} for x in items]))''')
    (OUT/'spark-services-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    ssh(f'''import pathlib,json,socket
root=pathlib.Path({REMOTE!r});root.mkdir(exist_ok=True)
s=socket.socket();s.bind(('127.0.0.1',18636));s.close()
print(json.dumps({{'directory':str(root)}}))''')
    reusable=ssh(f'''import pathlib,json,hashlib
p=pathlib.Path({REMOTE!r})/'mmproj-F16.gguf'
match=p.is_file() and p.stat().st_size==927607360
if match:
    with p.open('rb') as f: match=hashlib.file_digest(f,'sha256').hexdigest()=='eacf610d1ee4bd5ed0197a0777dd8f4fceb8eefa27009067c7d496cb68fbde45'
print(json.dumps({{'verified':match}}))''')
    if not reusable['verified']:
        transfer=subprocess.run(['scp','-o','ConnectTimeout=10',str(OUT/'mmproj-F16.gguf'),'spark-xiaozhuji:'+REMOTE+'/mmproj-F16.gguf'],capture_output=True,text=True,encoding='utf-8',timeout=180)
        if transfer.returncode: raise RuntimeError('projector_transfer_failed')
    result=ssh(f'''import pathlib,hashlib,subprocess,json
root=pathlib.Path({REMOTE!r}); projector=root/'mmproj-F16.gguf'
with projector.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
assert digest=='eacf610d1ee4bd5ed0197a0777dd8f4fceb8eefa27009067c7d496cb68fbde45'
model=pathlib.Path('/home/jc/models/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf');assert model.is_file()
command=['/home/jc/src/buun-llama-cpp/build/bin/llama-server','-m',str(model),'--mmproj',str(projector),'--alias','qwen36-27b-vision-compare','--host','127.0.0.1','--port','18636','--gpu-layers','99','--ctx-size','16384','--parallel','1','--reasoning','off','--reasoning-budget','0','--jinja','--temp','0','--image-max-tokens','4096']
log=(root/'server.log').open('ab');p=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,cwd=root)
(root/'server.pid').write_text(str(p.pid));(root/'command.json').write_text(json.dumps(command))
print(json.dumps({{'pid':p.pid,'port':18636,'projector_sha256':digest,'model':str(model),'reasoning':'off'}}))''')
    (OUT/'spark-trial-service.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))

"""Read-only post-run service verification for the owned temporary comparison."""
import json
import shlex
import subprocess
from pathlib import Path
from compare_cute_models import OUT

owned_pid=int(json.loads((OUT/'spark-trial-service.json').read_text(encoding='utf-8'))['pid'])
program = '''import json,pathlib,socket,subprocess
ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
items=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
containers=[{'id':x['Id'],'name':x['Name'],'image':x['Image'],'started':x['State']['StartedAt'],'running':x['State']['Running']} for x in items]
s=socket.socket();s.settimeout(2);closed=s.connect_ex(('127.0.0.1',18636))!=0;s.close()
gone=not pathlib.Path('/proc/'+str(__OWNED_PID__)).exists()
print(json.dumps({'containers':containers,'temporary_model_port_closed':closed,'temporary_model_process_gone':gone}))
'''.replace('__OWNED_PID__',str(owned_pid))
response=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','spark-xiaozhuji','python3 -c '+shlex.quote(program)],capture_output=True,text=True,encoding='utf-8',timeout=30,check=True)
after=json.loads(response.stdout)
before=json.loads((OUT/'spark-services-before.json').read_text(encoding='utf-8'))
current={x['id']:x for x in after['containers']}
result={'original_spark_containers_unchanged':all(current.get(x['id'])==x for x in before),
        'temporary_model_port_closed':after['temporary_model_port_closed'],
        'temporary_model_process_gone':after['temporary_model_process_gone'],
        'changed_original_services':[x['name'] for x in before if current.get(x['id'])!=x]}
(OUT/'spark-services-after.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
(OUT/'service-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))

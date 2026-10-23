"""Final provenance checks, without writing production review data."""
import json
from pathlib import Path
import re
import shlex
import subprocess
from collections import Counter
import statistics
import sys

from compare_cute_models import OUT, PROJECT, MODELS
from image_subject_settings import runtime_settings

report=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
images=[i for p in report['posts'] for i in p['images']]
total=len(images)
expected_posts=len(report['posts'])
results={}
for model in MODELS:
    records=[i['models'][model] for i in images]
    textrecords=[p['text_models'][model] for p in report['posts']]
    assert len(records)==total and all(r['status']=='recognized' for r in records)
    assert len(textrecords)==expected_posts and all(r['status']=='recognized' for r in textrecords)
    assert all(r.get('reasoning_chars')==0 and not r.get('thinking_warning') for r in records+textrecords)
    results[model]={'images':total,'texts':expected_posts,'outcomes':dict(Counter(r['outcome'] for r in records)),
                    'image_seconds_median':round(statistics.median(r['seconds'] for r in records),2),
                    'text_evidence_warnings':sum(bool(r['validated'].get('validation_warnings')) for r in textrecords),
                    'citation_states':dict(Counter(t.get('citation',{}).get('status','legacy') for r in textrecords for t in r['validated']['targets'])),
                    'served_model_ids':sorted(set(r.get('served_model') or '' for r in records+textrecords))}
assert all((OUT/i['src']).is_file() for i in images)
document=(OUT/'index.html').read_text(encoding='utf-8')
key=runtime_settings(PROJECT/'data')['api_key']
assert key and key not in document and key not in (OUT/'results.json').read_text(encoding='utf-8')
assert 'replace(/可爱/g' in document and 'data-field' in document
ui=subprocess.run(['node',str(PROJECT/'scripts/verify_cute_compare_ui.cjs'),str(OUT)],capture_output=True,text=True,encoding='utf-8',check=True)
syntax=subprocess.run(['node','--check',str(OUT/'ui-check.js')],capture_output=True,text=True,encoding='utf-8',check=True)
program='''import subprocess,json,pathlib,socket
ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
items=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
result={'containers':[{'id':x['Id'],'name':x['Name'],'image':x['Image'],'started':x['State']['StartedAt'],'running':x['State']['Running']} for x in items]}
pid=int(pathlib.Path('/home/jc/mediacrawler-model-compare-20261013/server.pid').read_text())
s=socket.socket();s.settimeout(2);result['temporary_model_port_closed']=s.connect_ex(('127.0.0.1',18636))!=0;s.close()
result['temporary_model_pid']=pid
result['original_paddleocr_process_present']=pathlib.Path('/proc/1819737').is_dir()
log=pathlib.Path('/home/jc/mediacrawler-model-compare-20261013/server.log').read_text(errors='replace')
result['runtime_evidence']=[line for line in log.splitlines() if 'general.name' in line or 'thinking = 0' in line or 'loaded multimodal' in line or 'model name:' in line][:12]
print(json.dumps(result))'''
remote=subprocess.run(['ssh','-o','ConnectTimeout=10','spark-xiaozhuji','python3 -c '+shlex.quote(program)],capture_output=True,text=True,encoding='utf-8',timeout=30,check=True)
after=json.loads(remote.stdout)
baseline_path=OUT/'spark-services-before.json'
if (OUT/'citation-repair-v2/spark-services-before.json').exists():
    # Audit this repair against its own start, not an earlier comparison run.
    baseline_path=OUT/'citation-repair-v2/spark-services-before.json'
before=json.loads(baseline_path.read_text(encoding='utf-8'))
by_id={r['id']:r for r in after['containers']}
services_unchanged=all(by_id.get(row['id'])==row for row in before)
(OUT/'spark-services-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
production_checks={p.name:json.loads(p.read_text(encoding='utf-8')) for p in OUT.glob('audit-*.json')}
critical_records_unchanged=bool(production_checks) and all(all(p.startswith('.collection-tasks') for p in v['changed_paths']) for v in production_checks.values())
assert critical_records_unchanged, 'Review/cache/Excel snapshot changed; inspect before claiming preservation'
assert after['temporary_model_port_closed'] and after['original_paddleocr_process_present']
changed_services=[{'before':row,'after':[x for x in after['containers'] if x['name']==row['name']]} for row in before if by_id.get(row['id'])!=row]
value={'models':results,'preview_count':total,'all_previews_exist':True,'secrets_absent':True,
       'thinking_off_response_checks':len(MODELS)*(total+expected_posts),'production_checks':production_checks,'review_model_cache_excel_unchanged':critical_records_unchanged,
       'original_spark_containers_unchanged':services_unchanged,'concurrent_service_changes':changed_services,
       'spark_service_comparison_baseline':str(baseline_path.relative_to(OUT)),
       'temporary_model_port_closed':after['temporary_model_port_closed'],
       'ui_logic_verification':json.loads(ui.stdout),'live_browser_verification':False,'spark_runtime_evidence':after['runtime_evidence']}
(OUT/'verification.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(value,ensure_ascii=False))

"""Read-only remote capacity/access audit; export request metadata only."""
import csv, json, pathlib, shlex, subprocess, collections, html

OUT = pathlib.Path(__file__).resolve().parents[1] / 'artifacts/spark-capacity-access-20261019'
OUT.mkdir(exist_ok=True, parents=True)
REMOTE = r'''
import subprocess, json, pathlib, re, collections, urllib.request, datetime
def run(args):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=60)
 return p.stdout
rows=[]; coverage=[]; model_events=[]
for name in ['ollama-local','park-workflow-ollama-1','ollama-local-before-two-models-20260917-104451','vllm-qwen36-35b-tool']:
 data=run(['docker','logs','--timestamps',name])
 lines=data.splitlines()
 coverage.append({'source':name,'lines':len(lines),'first':lines[0].split(' ')[0] if lines else '', 'last':lines[-1].split(' ')[0] if lines else ''})
 for n,line in enumerate(lines,1):
  m=re.search(r'\[GIN\].*?\|\s*(\d{3})\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*(GET|POST|HEAD|DELETE|OPTIONS)\s+"([^"]+)"',line)
  if m:
   status,duration,ip,method,path=m.groups()
   rows.append({'source':name,'line':n,'time_utc':line.split(' ')[0],'ip':ip.strip(),'method':method,'path':path,'status':status,'duration':duration.strip(),'model':'not recorded'})
  if 'qwen3.6' in line.lower() and ('load' in line.lower() or 'model' in line.lower()):
   model_events.append({'source':name,'line':n,'text':line[:1500]})
  v=re.search(r'(\d+\.\d+\.\d+\.\d+):\d+ - "(GET|POST|HEAD) (\S+) HTTP/[^\"]+" (\d{3})',line)
  if v:
   ip,method,path,status=v.groups()
   rows.append({'source':name,'line':n,'time_utc':line.split(' ')[0],'ip':ip,'method':method,'path':path,'status':status,'duration':'not recorded','model':'qwen36-35b (service identity)'})
p=pathlib.Path('/home/jc/mediacrawler-model-compare-20261013/server.log')
if p.exists():
 lines=p.read_text(errors='replace').splitlines()
 coverage.append({'source':'q36-temporary-vision','lines':len(lines),'first':'request timestamps unavailable','last':'mtime '+str(p.stat().st_mtime)})
 for n,line in enumerate(lines,1):
  m=re.search(r'done request: (\w+) (\S+) (\S+) (\d{3})',line)
  if m:
   method,path,ip,status=m.groups()
   rows.append({'source':'q36-temporary-vision','line':n,'time_utc':'not recorded','ip':ip,'method':method,'path':path,'status':status,'duration':'not recorded','model':'qwen36-27b-vision-compare'})
for p in sorted(pathlib.Path('/home/jc/logs').glob('qwen36*.log')):
 if 'cli' in p.name or 'spec-test' in p.name or 'readme' in p.name: continue
 count=0; first=''; last=''
 with p.open(errors='replace') as f:
  for n,line in enumerate(f,1):
   count=n
   m=re.search(r'done request: (\w+) (\S+) (\S+) (\d{3})',line)
   v=re.search(r'(\d+\.\d+\.\d+\.\d+):\d+ - "(GET|POST|HEAD) (\S+) HTTP/[^\"]+" (\d{3})',line)
   if m or v:
    if m: method,path,ip,status=m.groups()
    else: ip,method,path,status=v.groups()
    stamp=re.search(r'\b\d{4}-\d\d-\d\d[T ][\d:.+Z-]+',line)
    stamp=stamp.group() if stamp else 'not recorded'
    if not first:first=stamp
    last=stamp
    rows.append({'source':p.name,'line':n,'time_utc':stamp,'ip':ip,'method':method,'path':path,'status':status,'duration':'not recorded','model':'qwen36-27b (log identity)' if '27b' in p.name else 'qwen36-35b (log identity)'})
 coverage.append({'source':p.name,'lines':count,'first':first or 'no HTTP records','last':last or 'no HTTP records','file_modified':datetime.datetime.fromtimestamp(p.stat().st_mtime,datetime.timezone(datetime.timedelta(hours=8))).isoformat()})
models={}
for endpoint in ['tags','ps']:
 try:
  with urllib.request.urlopen('http://127.0.0.1:11434/api/'+endpoint,timeout=5) as r: models[endpoint]=json.load(r)
 except Exception as e: models[endpoint]={'error':type(e).__name__}
print(json.dumps({'rows':rows,'coverage':coverage,'model_events':model_events,'models':models,'free':run(['free','-b']),'disk':run(['df','-B1','/home/jc']),'time':run(['date','-Is']).strip()},ensure_ascii=False))
'''
p=subprocess.run(['ssh','-o','ConnectTimeout=10','spark-xiaozhuji','python3 -c '+shlex.quote(REMOTE)],capture_output=True,text=True,encoding='utf-8',timeout=160,check=True)
data=json.loads(p.stdout)
(OUT/'audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
rows=data['rows']
inference=[r for r in rows if r['method']=='POST' and r['path'] in ['/api/chat','/api/generate','/v1/chat/completions','/v1/completions','/api/embed','/api/embeddings']]
for name,items in [('all-requests.csv',rows),('inference-requests.csv',inference)]:
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['source','line','time_utc','ip','method','path','status','duration','model']);w.writeheader();w.writerows(items)
groups=collections.Counter((r['source'],r['ip'],r['path'],r['status']) for r in inference)
summary={'captured_at':data['time'],'coverage':data['coverage'],'inference_count':len(inference),'groups':[{'source':k[0],'ip':k[1],'path':k[2],'status':k[3],'count':v} for k,v in groups.items()],'models':data['models'],'model_events_count':len(data['model_events'])}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
def table(items,keys):
 return '<table><thead><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in keys)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k,'')))+'</td>' for k in keys)+'</tr>' for r in items)+'</tbody></table>'
page='''<!doctype html><meta charset="utf-8"><title>Spark 模型调用记录核查</title><style>body{font:16px system-ui;margin:32px;color:#1e293b;background:#f8fafc}table{border-collapse:collapse;background:white;width:100%;font-size:13px;margin:20px 0}td,th{border:1px solid #cbd5e1;padding:9px;text-align:left}h1{font-size:26px}.note{background:#fff3cd;padding:16px}a{color:#0369a1}pre{white-space:pre-wrap}</style><h1>Spark 模型调用记录核查</h1>'''
page+='<p>采集时间：'+html.escape(data['time'])+'；只读核查，没有启动、停止或修改远程服务。</p>'
page+='<p class="note">来源 IP 不等于人员身份。Ollama 访问日志未逐条记录模型名，不能将其中所有推理请求归为 Qwen3.6；临时视觉服务请求没有逐条时间戳。127.0.0.1 可能来自本机进程或 SSH 转发。记录仅覆盖仍保留的日志，跨日志条目未做请求 ID 去重，不能当作完整历史调用总量。file_modified 为文件修改时间，不是每次请求时间。CSV 的 time_utc 为 UTC；北京时间加 8 小时。</p>'
page+='<h2>核查结论</h2><p>当前可用内存约 81 GiB，磁盘约 3.26 TB；具备部署 Qwen3.8-27B 的容量条件。官方原始仓库约 55.6 GB，运行还需要上下文缓存和视觉计算空间。低并发、受限上下文可行，但未实际部署压测。</p><p>27B 临时视觉接口有 209 条成功请求，来源全部为 127.0.0.1，不能由此识别使用者。历史 27B 日志中，192.168.30.177 有 30 条 HTTP 200 和 4 条 HTTP 400，另有 Docker 地址 172.17.0.2 的 10 条成功请求。该批历史日志文件最后修改于 2026 年 5 月。当前电脑 WLAN 为 192.168.30.178；历史 IP 可能变化，不能认定 .177 就是他人。</p><p>35B 历史服务也存在 .177 请求，已经在下表独立列出。park-workflow 的当前模型列表仅有 qwen3-vl:4b-instruct；其两条聊天请求不应直接归为 3.6。当前 ollama-local 保留日志从 2026-10-17 起，未发现聊天或生成请求。</p>'
page+='<p><a href="inference-requests.csv">下载推理请求 CSV</a> · <a href="all-requests.csv">下载全部访问请求 CSV（含健康检查）</a></p>'
page+='<h2>当前资源</h2><pre>'+html.escape(data['free']+'\n'+data['disk'])+'</pre><h2>日志覆盖</h2>'+table(data['coverage'],['source','lines','first','last','file_modified'])
page+='<h2>推理请求按来源汇总</h2>'+table(summary['groups'],['source','ip','path','status','count'])
page+='<h2>推理请求明细</h2>'+table(inference,['source','line','time_utc','ip','path','status','duration','model'])
(OUT/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='models'},ensure_ascii=False,indent=2))

"""Host-side SSH socket probe; never emits relay/API credentials."""
import http.client
import json
from pathlib import Path
import socket

ROOT=Path('/home/jc/mediacrawler-spark')
env=dict(line.split('=',1) for line in (ROOT/'.env.spark').read_text().splitlines()
         if '=' in line and not line.startswith('#'))
connection=http.client.HTTPConnection('jev-relay',timeout=25)
connection.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
connection.sock.settimeout(25)
connection.sock.connect(str(ROOT/'docker/runtime/jev-relay/jev.sock'))
connection.request('POST','/v1/systemone',body=json.dumps({'model':'jev-1.13.0',
    'state':{'text':'连接检查'},'questions':{}}).encode(),
    headers={'X-Jev-Relay-Token':env['TYPESAFE_RELAY_TOKEN'],'Content-Type':'application/json'})
response=connection.getresponse()
body=response.read().decode()
assert response.status==403 and 'API key' in body, 'Jev authentication endpoint not reached'
print(json.dumps({'http_status':response.status,'authentication_reached':True,'region_block':False}))
connection.close()

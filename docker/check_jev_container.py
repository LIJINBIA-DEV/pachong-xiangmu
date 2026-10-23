"""Probe the actual Jev SDK transport; authentication is left to the user."""
import asyncio
import json
from jev_transport import create_semantic_client, jev_request_target
from semantic_filter import API_URL

async def main():
    endpoint,headers=jev_request_target(API_URL)
    assert endpoint.startswith('http://jev-relay/')
    async with create_semantic_client() as client:
        response=await client.post(endpoint,headers=headers,json={'model':'jev-1.13.0',
            'state':{'text':'连接检查'},'questions':{}},timeout=25)
    assert response.status_code==403 and 'API key' in response.text
    print(json.dumps({'sdk_transport':'ssh_socket','http_status':403,
        'authentication_reached':True,'region_block':False,'api_key_required':True}))

if __name__=='__main__':
    asyncio.run(main())

import json

from fastapi.testclient import TestClient
import httpx
import pytest

from scripts.jev_relay import BODY_LIMIT, UPSTREAM, create_app
from semantic_filter import API_URL, check_jev_connection
from tests.semantic_responses import grounded_response


def test_relay_authentication_destination_and_provider_errors_are_preserved():
    calls = []
    def respond(request):
        calls.append(request)
        assert str(request.url) == UPSTREAM
        assert request.headers['Authorization'] == 'Bearer api-test-key'
        assert 'X-Jev-Relay-Token' not in request.headers
        assert 'X-Forward-To' not in request.headers
        return httpx.Response(429, json={'detail':'rate_limited'})
    with TestClient(create_app('relay-test-token', httpx.MockTransport(respond))) as client:
        payload = {'model':'jev-1.13.0', 'state':{'text':'公园可爱'}, 'questions':{}}
        assert client.post('/v1/systemone', json=payload).status_code == 401
        assert client.post('/v1/systemone', headers={'X-Jev-Relay-Token':'wrong'}, json=payload).status_code == 401
        assert client.post('/v1/chat/completions', json=payload).status_code == 404
        assert not calls
        response = client.post('/v1/systemone', headers={'X-Jev-Relay-Token':'relay-test-token',
            'Authorization':'Bearer api-test-key','X-Forward-To':'https://attacker.example/'},json=payload)
        assert response.status_code == 429 and response.json()['detail'] == 'rate_limited'
        assert json.loads(calls[0].content) == payload


def test_invalid_or_oversized_payload_never_reaches_provider(monkeypatch):
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
    with TestClient(create_app('relay-test-token', transport)) as client:
        headers = {'X-Jev-Relay-Token':'relay-test-token'}
        assert client.post('/v1/systemone',headers=headers,content=b'{bad').status_code == 400
        assert client.post('/v1/systemone',headers=headers,json={'model':'other-model'}).status_code == 400
        assert client.post('/v1/systemone',headers=headers,content=b'a'*(BODY_LIMIT+1)).status_code == 413
        assert not calls


@pytest.mark.asyncio
async def test_real_reviewer_uses_relay_and_reports_no_key_in_result(monkeypatch, capsys):
    monkeypatch.setenv('TYPESAFE_RELAY_SOCKET','/run/jev-relay/jev.sock')
    monkeypatch.setenv('TYPESAFE_RELAY_TOKEN','relay-test-token')
    calls=[]
    def respond(request):
        calls.append(request)
        return grounded_response(request)
    app=create_app('relay-test-token',httpx.MockTransport(respond))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client:
            result=await check_jev_connection('api-test-key',client=client)
    assert result['ok'] and result['reason']=='usable'
    assert calls and all(str(request.url)==API_URL for request in calls)
    assert all('X-Jev-Relay-Token' not in request.headers for request in calls)
    assert 'api-test-key' not in json.dumps(result)+capsys.readouterr().out


@pytest.mark.asyncio
async def test_failed_tunnel_cannot_fall_back_to_direct_jev(monkeypatch):
    monkeypatch.setenv('TYPESAFE_RELAY_SOCKET','/run/jev-relay/jev.sock')
    monkeypatch.setenv('TYPESAFE_RELAY_TOKEN','relay-test-token')
    calls=[]
    def respond(request):
        calls.append(str(request.url))
        raise httpx.ConnectError('socket unavailable',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result=await check_jev_connection('api-test-key',client=client)
    assert result['reason']=='network_error' and not result['ok']
    assert calls==['http://jev-relay/v1/systemone']


@pytest.mark.asyncio
async def test_relay_missing_token_fails_closed_and_non_jev_clients_keep_direct_transport(monkeypatch):
    from jev_transport import create_semantic_client
    monkeypatch.setenv('TYPESAFE_RELAY_SOCKET','/run/jev-relay/jev.sock')
    monkeypatch.delenv('TYPESAFE_RELAY_TOKEN',raising=False)
    with pytest.raises(ValueError,match='token'):
        create_semantic_client()
    # Local SemIf does not use Jev's relay configuration.
    client=create_semantic_client('semif-local')
    assert isinstance(client,httpx.AsyncClient)
    await client.aclose()


@pytest.mark.asyncio
async def test_siliconflow_stays_direct_with_jev_relay_configured(monkeypatch,tmp_path):
    from PIL import Image
    from image_subject_cloud import SiliconFlowImageReviewer
    from image_subject_settings import CLOUD_URL
    monkeypatch.setenv('TYPESAFE_RELAY_SOCKET','/run/jev-relay/jev.sock')
    monkeypatch.setenv('TYPESAFE_RELAY_TOKEN','relay-test-token')
    path=tmp_path/'sample.jpg'
    Image.new('RGB',(100,100),'blue').save(path)
    def respond(request):
        assert str(request.url)==CLOUD_URL
        assert 'X-Jev-Relay-Token' not in request.headers
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({
            'label':'二者都不是','reason':'没有人物或食物','image_type':'不确定','type_reason':'纯色无法判断'})}}]})
    reviewer=SiliconFlowImageReviewer(tmp_path,'siliconflow-test-key',transport=httpx.MockTransport(respond))
    try:
        result=await reviewer.classify(path)
        assert result['provider']=='siliconflow'
    finally:
        await reviewer.close()

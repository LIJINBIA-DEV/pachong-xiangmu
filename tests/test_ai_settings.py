import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.services import ai_settings, content_summary
from api.routers import data as data_router
from tests.test_content_summary import model_response


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for key in ['AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL', 'DEEPSEEK_API_KEY']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(data_router, 'DATA_DIR', tmp_path)
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    return tmp_path


def settings(**values):
    return ai_settings.AISettingsUpdate(base_url=values.pop('base_url', 'https://models.example/v1'), model=values.pop('model', 'custom-model'), **values)


def test_settings_keep_credentials_private_and_bind_them_to_endpoint(isolated):
    root = isolated
    assert not ai_settings.public_settings(root)['ready']
    saved = ai_settings.save_settings(root, settings(api_key='test-model-key', scope='available', max_posts=20, include_comments=True))
    assert saved['ready'] and saved['key_configured'] and saved['model'] == 'custom-model'
    assert 'test-model-key' not in json.dumps(saved)
    encoded = (root/'.ai-settings/settings.json').read_text()
    assert 'test-model-key' not in encoded
    assert ai_settings.runtime_settings(root)['api_key'] == 'test-model-key'
    ai_settings.save_settings(root, settings(model='another-model'))
    assert ai_settings.runtime_settings(root)['api_key'] == 'test-model-key'
    ai_settings.save_settings(root, settings(base_url='https://other.example/v1'))
    assert not ai_settings.public_settings(root)['key_configured']
    ai_settings.save_settings(root, settings(api_key='new-provider-key'))
    ai_settings.save_settings(root, settings(clear_key=True))
    assert not ai_settings.public_settings(root)['key_configured']
    if os.name == 'posix':
        assert (root/'.ai-settings/settings.json').stat().st_mode & 0o777 == 0o600
        assert (root/'.ai-settings/credential.key').stat().st_mode & 0o777 == 0o600


def test_environment_keys_do_not_follow_changed_provider(isolated, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'legacy-environment-key')
    assert ai_settings.public_settings(isolated)['key_from_environment']
    ai_settings.save_settings(isolated, settings())
    assert ai_settings.runtime_settings(isolated)['api_key'] == ''
    monkeypatch.setenv('AI_API_KEY', 'generic-environment-key')
    assert ai_settings.runtime_settings(isolated)['api_key'] == ''


@pytest.mark.parametrize('url', ['file:///private/test', 'http://models.example/v1', 'https://user:password@models.example', 'https://models.example?key=secret', 'http://169.254.169.254', 'https://[::]/v1'])
def test_invalid_endpoints_are_rejected(url):
    with pytest.raises((ValidationError, ValueError)):
        settings(base_url=url)


def test_base_and_full_urls_and_local_models():
    assert ai_settings.endpoint('https://models.example/v1/') == 'https://models.example/v1/chat/completions'
    assert ai_settings.endpoint('https://models.example/v1/chat/completions') == 'https://models.example/v1/chat/completions'
    assert ai_settings.endpoint('http://127.0.0.1:1234/v1') == 'http://127.0.0.1:1234/v1/chat/completions'
    assert settings(model='local-model:32b').model == 'local-model:32b'


def test_http_settings_validation_never_echoes_keys_and_private_files_stay_hidden(isolated):
    app = FastAPI(); app.include_router(data_router.router, prefix='/api')
    client = TestClient(app)
    bad = client.put('/api/data/ai-settings', json={'base_url':'https://models.example/v1', 'model':'custom', 'api_key':['PRIVATE_KEY']})
    assert bad.status_code == 422 and 'PRIVATE_KEY' not in bad.text
    bad = client.put('/api/data/ai-settings', json={'base_url':'https://models.example/v1', 'model':'custom', 'api_key':'PRIVATE\nKEY'})
    assert bad.status_code == 422 and 'PRIVATE' not in bad.text
    payload = settings(api_key='test-model-key').model_dump(exclude={'api_key'}) | {'api_key':'test-model-key'}
    assert client.put('/api/data/ai-settings', json=payload, headers={'Origin':'https://foreign.example'}).status_code == 403
    saved = client.put('/api/data/ai-settings', json=payload)
    assert saved.status_code == 200 and saved.json()['ready']
    assert 'test-model-key' not in saved.text
    assert 'test-model-key' not in client.get('/api/data/ai-settings').text
    assert client.get('/api/data/content-summary', params={'file':'.ai-settings/settings.json'}).status_code == 403


@pytest.mark.asyncio
async def test_generation_uses_saved_provider_model_and_scope_without_rewriting_data(isolated):
    root = isolated
    folder = root/'xhs'; folder.mkdir()
    path = folder/'posts.json'
    path.write_text(json.dumps([{'note_id':'1', 'content':'服务使用体验很好。', 'source_keyword':'服务体验', 'semantic_result':'matched'}], ensure_ascii=False))
    before = path.read_bytes()
    ai_settings.save_settings(root, settings(api_key='test-model-key', model='local-model:32b', include_comments=True, max_posts=7))
    requests = []
    def respond(request):
        assert str(request.url) == 'https://models.example/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer test-model-key'
        payload = json.loads(request.content)
        assert payload['model'] == 'local-model:32b'
        assert 'thinking' not in payload
        assert 'test-model-key' not in request.content.decode()
        requests.append(payload)
        return httpx.Response(200, json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(model_response(payload), ensure_ascii=False)}}]})
    jobs = content_summary.SummaryJobs(client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    job = await jobs.start(root, path, content_summary.SummaryRequest(file='xhs/posts.json'))
    # New settings affect the next generation; this job keeps its captured connection and model.
    ai_settings.save_settings(root, settings(base_url='https://replacement.example/v1', api_key='different-key', model='different-model'))
    await asyncio.gather(*list(jobs.tasks.values()))
    assert job['status'] == 'ready' and len(requests) == 2
    assert job['options']['model'] == 'local-model:32b'
    assert job['options']['max_posts'] == 7 and job['options']['include_comments']
    assert path.read_bytes() == before
    for report in (root/'.content-summaries').rglob('*.json'):
        assert 'test-model-key' not in report.read_text()


@pytest.mark.asyncio
async def test_redirects_cannot_forward_the_key(isolated):
    calls = []
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'Location':'https://foreign.example/chat/completions'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match='summary_provider_failed'):
            await content_summary.model_json(client, 'test-key', 'custom', 'system', {}, 'https://models.example/v1/chat/completions')
    assert calls == ['https://models.example/v1/chat/completions']

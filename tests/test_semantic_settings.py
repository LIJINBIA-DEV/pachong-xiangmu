"""Persist Jev credentials without putting plaintext keys in browser state or task files."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routers import crawler as router, data as data_router, jev_proxy as proxy_router
from api.services import semantic_settings as settings, ai_settings
from api.schemas.crawler import CrawlerStartRequest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path))
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.setattr(router.crawler_manager, 'task_credentials', {})
    return tmp_path


def save(root, key=None, clear=False):
    return settings.save_settings(root, settings.SemanticSettingsUpdate(api_key=key, clear_key=clear))


def test_encrypted_storage_survives_reload_and_keeps_summary_settings(isolated):
    root = isolated
    ai_settings.save_settings(root, ai_settings.AISettingsUpdate(base_url='https://models.example', model='model', api_key='summary-secret'))
    assert save(root, 'jev-private-key') == {'key_configured': True}
    assert settings.runtime_key(root) == 'jev-private-key'
    for file in (root / '.ai-settings').glob('*'):
        assert b'jev-private-key' not in file.read_bytes()
        assert file.stat().st_mode & 0o777 == 0o600
    assert importlib.reload(settings).runtime_key(root) == 'jev-private-key'
    assert save(root) == {'key_configured': True}
    save(root, 'replacement-key')
    assert settings.runtime_key(root) == 'replacement-key'
    save(root, clear=True)
    assert not settings.public_settings(root)['key_configured']
    assert ai_settings.runtime_settings(root)['api_key'] == 'summary-secret'


def test_clearing_does_not_revive_environment_keys_or_follow_symlinks(isolated, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'environment-secret')
    assert settings.runtime_key(isolated) == 'environment-secret'
    save(isolated, clear=True)
    assert settings.runtime_key(isolated) == ''
    path = isolated / '.ai-settings/jev.json'
    path.unlink()
    outside = isolated / 'outside.json'
    outside.write_text('{}')
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        settings.runtime_key(isolated)
    with pytest.raises(ValueError):
        save(isolated, 'new-key')
    assert outside.read_text() == '{}'


def test_api_never_returns_key_and_rejects_invalid_inputs_and_foreign_origin(isolated, monkeypatch):
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    app.include_router(data_router.router, prefix='/api')
    client = TestClient(app)
    router.crawler_manager.task_credentials['old-task'] = {'semantic_api_key': 'old-private-key', 'cookies': 'keep-cookie'}
    response = client.put('/api/crawler/semantic-settings', json={'api_key': 'jev-private-key'})
    assert response.status_code == 200 and response.json() == {'key_configured': True}
    assert response.headers['cache-control'] == 'no-store'
    assert router.crawler_manager.task_credentials['old-task'] == {'cookies': 'keep-cookie'}
    for _ in range(2):
        response = client.get('/api/crawler/semantic-settings')
        assert 'jev-private-key' not in response.text and response.json()['key_configured']
    for invalid in [['PRIVATE_KEY'], 'PRIVATE\nKEY', 'X' * 513]:
        response = client.put('/api/crawler/semantic-settings', json={'api_key': invalid})
        assert response.status_code == 422
        assert 'PRIVATE' not in response.text and 'XXX' not in response.text
        assert settings.runtime_key(isolated) == 'jev-private-key'
    invalid_check = client.post('/api/crawler/semantic-key-check', json={'api_key': ['PRIVATE_KEY']})
    assert invalid_check.status_code == 422 and 'PRIVATE_KEY' not in invalid_check.text
    assert client.put('/api/crawler/semantic-settings', json={'clear_key': True}, headers={'Origin': 'https://foreign.example'}).status_code == 403
    assert client.get('/api/data/files/.ai-settings/jev.json').status_code == 403
    assert client.put('/api/crawler/semantic-settings', json={'clear_key': True}).json() == {'key_configured': False}


@pytest.mark.asyncio
async def test_connection_checks_and_proxy_use_saved_key(isolated, monkeypatch):
    save(isolated, 'saved-key')
    checked = []
    async def check(key, *args):
        checked.append(key)
        return {'ok': True, 'reason': 'usable'}
    monkeypatch.setattr(router, 'check_jev_connection', check)
    monkeypatch.setattr(proxy_router, 'check_jev_connection', check)
    monkeypatch.setattr(proxy_router.jev_proxy, 'bundled_available', lambda: True)
    from fastapi import Response
    assert (await router.check_semantic_key(router.SemanticKeyCheckRequest()))['ok']
    assert (await proxy_router.test_proxy(proxy_router.TestRequest(), Response()))['ok']
    assert checked == ['saved-key', 'saved-key']


@pytest.mark.asyncio
async def test_collection_start_uses_saved_key_in_child_only(isolated, monkeypatch):
    save(isolated, 'saved-key')
    module = importlib.import_module('api.services.crawler_manager')
    captured = {}
    def launch(command, **kwargs):
        captured.update(command=command, env=kwargs['env'])
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    manager = module.CrawlerManager()
    manager._read_output = AsyncMock()
    request = CrawlerStartRequest(platform='xhs', login_type='cookie', cookies='session-cookie',
        login_environment='local', save_option='excel', crawler_type='search', keywords='采集主题',
        semantic_filter=True, semantic_rule='topic', keyword_pairs=[('采集主题', '')], max_notes_count=1,
        enable_sub_comments=True, max_comments_count=10000)
    assert await manager.start(request)
    await manager._read_task
    assert captured['env']['TYPESAFE_API_KEY'] == 'saved-key'
    assert 'saved-key' not in str(captured['command'])
    assert 'saved-key' not in str(manager.logs)
    assert manager.current_config.max_comments_count == 5
    assert manager.current_config.enable_sub_comments is False
    for file in (isolated / '.collection-tasks').rglob('*.json'):
        assert 'saved-key' not in file.read_text()


def test_supplement_does_not_request_key_again(isolated):
    from collection_tasks import create_task
    from api.services.supplement import plan
    save(isolated, 'saved-key')
    path = isolated / 'weibo/posts.json'
    path.parent.mkdir()
    path.write_text(json.dumps([{'note_id': '1', 'source_keyword': '采集主题', 'content': '内容'}]))
    create_task(isolated, {'platform': 'wb', 'semantic_filter': True, 'semantic_model': 'jev-1.13.0'}, {'采集主题': 1}, 'weibo/posts.json')
    manager = SimpleNamespace(status='idle', task_credentials={})
    assert not plan(isolated, path, manager)['needs_api_key']


@pytest.mark.asyncio
async def test_supplement_start_captures_saved_key_after_restart(isolated, monkeypatch):
    from api.services.manual_review import update_annotation
    from api.services.supplement import start_supplement
    from collection_tasks import create_task
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    save(isolated, 'saved-key')
    path = isolated / 'weibo/posts.json'
    path.parent.mkdir()
    path.write_text(json.dumps([{'note_id': '1', 'source_keyword': '采集主题', 'content': '内容'}]))
    create_task(isolated, {'platform': 'wb', 'login_type': 'cookie', 'save_option': 'excel',
        'semantic_filter': True, 'semantic_rule': 'topic', 'semantic_model': 'jev-1.13.0',
        'keyword_pairs': [('采集主题', '')]}, {'采集主题': 1}, 'weibo/posts.json')
    update_annotation(isolated, path, '1:采集主题', 'post', 'unqualified')
    manager = SimpleNamespace(status='idle', task_credentials={}, start=AsyncMock(return_value=True))
    await start_supplement(isolated, path, manager)
    passed = manager.start.await_args.args[0]
    assert passed.semantic_api_key.get_secret_value() == 'saved-key'

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.xhs_login import XhsWebLogin
from media_platform.xhs.session import read_session, restore_session, save_session, session_path


def credentials():
    return {'cookies': [{'name': 'web_session', 'value': 'private-test-session',
                         'domain': '.xiaohongshu.com', 'path': '/', 'expires': -1}], 'origins': []}


def fake_browser(monkeypatch, service):
    import api.services.xhs_login as module
    service.login_environment = 'server'
    page = SimpleNamespace(goto=AsyncMock(), locator=lambda _: SimpleNamespace(inner_text=AsyncMock(return_value='扫码登录')))
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock(),
                              storage_state=AsyncMock(return_value=credentials()))
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
    monkeypatch.setattr(module, 'async_playwright', playwright)
    service.authenticated = AsyncMock(return_value=True)
    service.find_qr = AsyncMock(return_value='data:image/png;base64,test')
    service.verification_required = AsyncMock(return_value=False)
    return browser, context


def test_session_requires_live_xhs_cookie_and_never_exposes_credentials(tmp_path):
    state = credentials()
    state['cookies'] += [{'name': 'SUB', 'value': 'weibo-secret', 'domain': '.weibo.cn', 'expires': -1},
                         {'name': 'expired', 'domain': '.xiaohongshu.com', 'expires': 1}]
    save_session(tmp_path, state)
    assert read_session(tmp_path)['cookies'] == credentials()['cookies']
    assert XhsWebLogin(tmp_path).status()['saved_session']
    assert 'private-test-session' not in json.dumps(XhsWebLogin(tmp_path).status())
    state['cookies'][0]['expires'] = 1
    save_session(tmp_path, state)
    assert read_session(tmp_path) is None


@pytest.mark.asyncio
async def test_network_restriction_has_actionable_reason(tmp_path):
    service = XhsWebLogin(tmp_path)
    page = SimpleNamespace(locator=lambda _: SimpleNamespace(inner_text=AsyncMock(
        return_value='安全限制 IP at risk. Switch to a secure network and retry. 300012')))
    assert await service.verification_required(page)
    assert service.state['reason'] == 'login_network_restricted'


@pytest.mark.asyncio
async def test_guest_cookie_alone_is_not_authenticated(tmp_path):
    service = XhsWebLogin(tmp_path)
    visible = AsyncMock(return_value=False)
    page = SimpleNamespace(locator=lambda _: SimpleNamespace(first=SimpleNamespace(is_visible=visible)))
    context = SimpleNamespace(cookies=AsyncMock(return_value=credentials()['cookies']))
    assert not await service.authenticated(page, context)
    visible.return_value = True
    assert await service.authenticated(page, context)
    context.cookies.return_value = []
    assert not await service.authenticated(page, context)


@pytest.mark.asyncio
async def test_success_saves_private_session_and_crawler_can_restore(tmp_path, monkeypatch):
    service = XhsWebLogin(tmp_path)
    browser, context = fake_browser(monkeypatch, service)
    await service._run(True)
    assert service.status()['status'] == 'authenticated'
    assert service.status()['qr_image'] is None
    restored = SimpleNamespace(add_cookies=AsyncMock())
    assert await restore_session(restored, tmp_path)
    assert restored.add_cookies.await_args.args[0] == credentials()['cookies']
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['expired', 'verification_required', 'error'])
async def test_failed_refresh_keeps_previous_session(tmp_path, monkeypatch, outcome):
    import api.services.xhs_login as module
    from playwright.async_api import Error
    save_session(tmp_path, credentials())
    original = session_path(tmp_path).read_bytes()
    service = XhsWebLogin(tmp_path)
    browser, context = fake_browser(monkeypatch, service)
    if outcome == 'expired':
        monkeypatch.setattr(module, 'QR_TTL', -1)
    elif outcome == 'verification_required':
        service.verification_required.return_value = True
    else:
        context.new_page.side_effect = Error('secret-session')
    await service._run(True)
    assert service.status()['status'] == outcome
    assert service.status()['qr_image'] is None
    assert 'secret-session' not in json.dumps(service.status())
    assert session_path(tmp_path).read_bytes() == original
    browser.close.assert_awaited_once()


def test_api_routes_are_private_and_desktop_login_is_supported(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers.crawler import router
    import api.services.xhs_login as module
    monkeypatch.setattr(module, 'xhs_web_login', XhsWebLogin(tmp_path))
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    service = module.xhs_web_login
    service._run = AsyncMock()
    app = FastAPI(); app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        response = client.get('/api/crawler/xhs-login')
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['supported'] is True
        assert client.post('/api/crawler/xhs-login', json={'login_environment': 'local'}).status_code == 200
        assert service.login_environment == 'local'


@pytest.mark.asyncio
async def test_crawler_requires_own_platform_session_and_blocks_active_qr(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module('api.services.crawler_manager')
    import api.services.xhs_login as login_module
    from api.schemas.crawler import CrawlerStartRequest
    import config
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    service = XhsWebLogin(tmp_path)
    monkeypatch.setattr(login_module, 'xhs_web_login', service)
    manager = module.CrawlerManager(); manager._project_root = tmp_path
    request = CrawlerStartRequest(platform='xhs', login_type='qrcode', image_subject_recognition=False)
    with pytest.raises(ValueError, match='扫码'):
        await manager.start(request)
    save_session(tmp_path, credentials())
    service.task = asyncio.create_task(asyncio.Event().wait())
    with pytest.raises(ValueError, match='取消扫码'):
        await manager.start(request)
    await service.close()
    commands = []
    def popen(command, **kwargs):
        commands.append(command)
        raise OSError('do not start collection in tests')
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    assert not await manager.start(request)
    assert commands[0][commands[0].index('--lt') + 1] == 'qrcode'
    assert '--cookies' not in commands[0]

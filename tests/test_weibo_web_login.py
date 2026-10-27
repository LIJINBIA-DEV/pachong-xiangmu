import asyncio
from contextlib import asynccontextmanager
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.weibo_login import WeiboWebLogin
from media_platform.weibo.session import read_session, restore_session, save_session, session_path


def credentials():
    return {'cookies': [{'name':'SUB','value':'secret-cookie','domain':'.weibo.cn','path':'/', 'expires':-1}], 'origins':[]}


def fake_browser(monkeypatch, service, authenticated=(False, True)):
    from api.services import weibo_login as module
    responses = [SimpleNamespace(status=200, json=AsyncMock(return_value={'ok':1,'data':{'login':value}})) for value in authenticated]
    page = SimpleNamespace(goto=AsyncMock(), url=module.SIGNIN)
    context = SimpleNamespace(request=SimpleNamespace(get=AsyncMock(side_effect=responses)),
        cookies=AsyncMock(return_value=[]),
        new_page=AsyncMock(return_value=page), close=AsyncMock(), storage_state=AsyncMock(return_value=credentials()))
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
    monkeypatch.setattr(module, 'async_playwright', playwright)
    service.find_qr = AsyncMock(return_value='data:image/png;base64,QR')
    service.verification_required = AsyncMock(return_value=False)
    original_sleep = asyncio.sleep
    async def short_sleep(seconds):
        await original_sleep(0)
    monkeypatch.setattr(module.asyncio, 'sleep', short_sleep)
    return browser, context


def test_private_state_filters_expired_and_foreign_cookies_and_is_not_public(tmp_path):
    state = credentials()
    state['cookies'] += [{'domain':'.other.example','expires':-1,'value':'not-weibo'}, {'domain':'.weibo.cn','expires':1}]
    save_session(tmp_path, state)
    assert read_session(tmp_path)['cookies'] == credentials()['cookies']
    if os.name != 'nt':
        assert session_path(tmp_path).stat().st_mode & 0o777 == 0o600
    public = WeiboWebLogin(tmp_path).status()
    assert public['saved_session'] and 'secret-cookie' not in json.dumps(public)


@pytest.mark.asyncio
async def test_session_restores_actual_cookie_values_for_the_crawler_only(tmp_path):
    context = SimpleNamespace(add_cookies=AsyncMock())
    assert not await restore_session(context, tmp_path)
    save_session(tmp_path, credentials())
    assert await restore_session(context, tmp_path)
    assert context.add_cookies.await_args.args[0][0]['value'] == 'secret-cookie'


@pytest.mark.asyncio
async def test_authenticated_requires_mobile_confirmation_and_closes_browser(tmp_path, monkeypatch):
    service = WeiboWebLogin(tmp_path)
    browser, context = fake_browser(monkeypatch, service)
    await service._run(refresh=True)
    assert context.request.get.await_count == 2
    assert service.status()['status'] == 'authenticated'
    assert service.status()['qr_image'] is None
    assert service.status()['saved_session']
    assert 'secret-cookie' not in json.dumps(service.status())
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_expiry_does_not_destroy_previously_saved_login(tmp_path, monkeypatch):
    import api.services.weibo_login as module
    save_session(tmp_path, credentials())
    previous = session_path(tmp_path).read_bytes()
    service = WeiboWebLogin(tmp_path)
    browser, _ = fake_browser(monkeypatch, service)
    monkeypatch.setattr(module,'QR_TTL', -1)
    await service._run(refresh=True)
    assert service.status()['status'] == 'expired'
    assert service.status()['qr_image'] is None
    assert session_path(tmp_path).read_bytes() == previous
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_session_is_validated_before_reporting_success(tmp_path, monkeypatch):
    save_session(tmp_path, credentials())
    service = WeiboWebLogin(tmp_path)
    _, context = fake_browser(monkeypatch, service, authenticated=(True,))
    await service._run(refresh=False)
    service.find_qr.assert_not_awaited()
    assert context.request.get.await_count == 1 and service.status()['status'] == 'authenticated'


@pytest.mark.asyncio
async def test_browser_error_is_sanitized_and_cannot_mark_logged_in(tmp_path, monkeypatch):
    from playwright.async_api import Error
    service = WeiboWebLogin(tmp_path)
    _, context = fake_browser(monkeypatch, service)
    context.new_page.side_effect = Error('secret-cookie login URL')
    await service._run(refresh=True)
    assert service.status()['status'] == 'error' and not read_session(tmp_path)
    assert service.status()['reason'] == 'login_browser_error'
    assert 'secret-cookie' not in json.dumps(service.status())


@pytest.mark.asyncio
async def test_verification_requires_human_and_does_not_save(tmp_path, monkeypatch):
    service = WeiboWebLogin(tmp_path)
    fake_browser(monkeypatch, service, authenticated=(False,))
    service.verification_required.return_value = True
    await service._run(refresh=True)
    assert service.status()['status'] == 'verification_required'
    assert not read_session(tmp_path) and service.status()['qr_image'] is None


@pytest.mark.asyncio
async def test_cancel_and_refresh_stop_old_task_and_do_not_start_collection(tmp_path, monkeypatch):
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE','1')
    service = WeiboWebLogin(tmp_path)
    stopped = []
    async def waiting(refresh):
        try:
            service.state.update(status='waiting',qr_image='data:image/png;base64,QR')
            await asyncio.Event().wait()
        finally:
            stopped.append(refresh)
    service._run = waiting
    manager = SimpleNamespace(_lock=asyncio.Lock(),status='idle',process=None)
    await service.start(manager)
    await asyncio.sleep(0)
    original = service.state['attempt_id']
    await service.start(manager,refresh=True)
    await asyncio.sleep(0)
    assert original != service.state['attempt_id'] and stopped == [False]
    await service.cancel(manager)
    assert stopped == [False,True]
    assert not service.busy and service.state['qr_image'] is None and manager.status == 'idle'
    manager.status = 'running'
    with pytest.raises(ValueError,match='collection_active'):
        await service.start(manager)


@pytest.mark.asyncio
async def test_container_crawler_uses_qr_session_without_cookie_arguments(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module('api.services.crawler_manager')
    from api.schemas.crawler import CrawlerStartRequest
    import config
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE','1')
    monkeypatch.setattr(config,'SAVE_DATA_PATH',str(tmp_path/'data'))
    manager=module.CrawlerManager()
    manager._project_root=tmp_path
    request=CrawlerStartRequest(platform='wb',login_type='qrcode',image_subject_recognition=False)
    with pytest.raises(ValueError,match='扫码'):
        await manager.start(request)
    save_session(tmp_path,credentials())
    commands=[]
    def popen(command,**kwargs):
        commands.append(command)
        raise OSError('no real collection')
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    assert not await manager.start(request)
    assert commands[0][commands[0].index('--lt')+1]=='qrcode'
    assert '--cookies' not in commands[0]


def test_api_status_is_uncached_and_explicit_server_login_is_supported(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers.crawler import router
    import api.services.weibo_login as module
    service=WeiboWebLogin(tmp_path)
    service._run = AsyncMock()
    monkeypatch.setattr(module,'weibo_web_login',service)
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE',raising=False)
    app=FastAPI(); app.include_router(router,prefix='/api')
    with TestClient(app) as client:
        response=client.get('/api/crawler/weibo-login')
        assert response.headers['cache-control']=='no-store'
        assert response.json()['supported'] is True
        assert client.post('/api/crawler/weibo-login',json={'login_environment': 'server'}).status_code==200
        assert service.login_environment == 'server'

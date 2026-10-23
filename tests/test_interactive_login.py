import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services import interactive_login as module
from api.services.weibo_login import WeiboWebLogin
from media_platform.weibo.session import read_session, save_session, session_path


def fake_browser(monkeypatch, service):
    state = {'cookies': [{'name': 'SUB', 'value': 'fake-test-session', 'domain': '.weibo.cn',
                          'path': '/', 'expires': -1}], 'origins': []}
    page = SimpleNamespace(goto=AsyncMock())
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), storage_state=AsyncMock(return_value=state),
                              cookies=AsyncMock(return_value=[]), close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    launch = AsyncMock(return_value=browser)
    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    monkeypatch.setattr(module, 'async_playwright', playwright)
    monkeypatch.setenv('MEDIACRAWLER_BROWSER_CHANNEL', 'chromium')
    service.mobile_authenticated = AsyncMock(return_value=False)
    service.find_qr = AsyncMock(return_value='fake-qr')
    service.verification_required = AsyncMock(return_value=True)
    return browser, context, launch, state


@pytest.mark.asyncio
async def test_verification_keeps_same_context_until_confirmed_login(monkeypatch, tmp_path):
    service = WeiboWebLogin(tmp_path)
    browser, context, launch, _ = fake_browser(monkeypatch, service)
    service.mobile_authenticated.side_effect = [False, True]
    async def human_action(_):
        assert service.state['status'] == 'verification_required'
        assert not read_session(tmp_path)
        browser.close.assert_not_awaited()
    monkeypatch.setattr(module.asyncio, 'sleep', human_action)
    await module.run_interactive_login(service, True, 'wb')
    assert service.state['status'] == 'authenticated' and read_session(tmp_path)
    browser.new_context.assert_awaited_once()
    browser.close.assert_awaited_once()
    assert launch.call_args.kwargs['headless'] is False


@pytest.mark.asyncio
async def test_expiry_preserves_old_session_and_closes_browser(monkeypatch, tmp_path):
    service = WeiboWebLogin(tmp_path)
    browser, _, _, state = fake_browser(monkeypatch, service)
    save_session(tmp_path, state)
    before = session_path(tmp_path).read_bytes()
    monkeypatch.setattr(module, 'LOGIN_TIMEOUT', -1)
    await module.run_interactive_login(service, True, 'wb')
    assert service.state['status'] == 'expired'
    assert session_path(tmp_path).read_bytes() == before
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_closes_live_verification_without_saving(monkeypatch, tmp_path):
    service = WeiboWebLogin(tmp_path)
    browser, _, _, _ = fake_browser(monkeypatch, service)
    waiting = asyncio.Event()
    async def hold(_):
        waiting.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(module.asyncio, 'sleep', hold)
    task = asyncio.create_task(module.run_interactive_login(service, True, 'wb'))
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.state['status'] == 'cancelled' and not read_session(tmp_path)
    browser.close.assert_awaited_once()


def test_desktop_opt_in_does_not_change_windows_or_old_server(monkeypatch):
    monkeypatch.setenv('MEDIACRAWLER_DESKTOP_LOGIN', '1')
    monkeypatch.setenv('DISPLAY', ':99')
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    assert not module.desktop_enabled()
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    assert module.desktop_enabled()
    monkeypatch.delenv('MEDIACRAWLER_DESKTOP_LOGIN')
    assert not module.desktop_enabled()


def test_jev_proxy_is_scoped_and_relay_retains_priority(monkeypatch):
    import jev_transport
    calls = []
    monkeypatch.setattr(jev_transport.httpx, 'AsyncClient', lambda **kw: calls.append(kw))
    monkeypatch.delenv('TYPESAFE_RELAY_SOCKET', raising=False)
    monkeypatch.setenv('TYPESAFE_PROXY_URL', 'http://host.docker.internal:7897')
    jev_transport.create_semantic_client()
    assert calls[-1] == {'proxy': 'http://host.docker.internal:7897', 'trust_env': False}
    jev_transport.create_semantic_client('semif-local')
    assert calls[-1] == {}
    monkeypatch.setenv('TYPESAFE_RELAY_SOCKET', '/run/test.sock')
    monkeypatch.setenv('TYPESAFE_RELAY_TOKEN', 'test')
    jev_transport.create_semantic_client()
    assert 'transport' in calls[-1] and 'proxy' not in calls[-1]


@pytest.mark.asyncio
async def test_stale_saved_login_is_not_used_for_new_attempt(monkeypatch, tmp_path):
    service = WeiboWebLogin(tmp_path)
    browser, context, _, state = fake_browser(monkeypatch, service)
    save_session(tmp_path, state)
    service.mobile_authenticated.side_effect = [False, True]
    await module.run_interactive_login(service, False, 'wb')
    context.close.assert_awaited_once()
    assert browser.new_context.await_count == 2
    assert 'storage_state' not in browser.new_context.await_args_list[1].kwargs
    assert service.state['status'] == 'authenticated'


@pytest.mark.asyncio
async def test_two_platforms_cannot_share_desktop_concurrently(monkeypatch, tmp_path):
    from api.services import weibo_login, xhs_login
    from api.services.xhs_login import XhsWebLogin
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    first, second = WeiboWebLogin(tmp_path), XhsWebLogin(tmp_path)
    monkeypatch.setattr(weibo_login, 'weibo_web_login', first)
    monkeypatch.setattr(xhs_login, 'xhs_web_login', second)
    first.task = asyncio.create_task(asyncio.Event().wait())
    manager = SimpleNamespace(_lock=asyncio.Lock(), status='idle', process=None)
    try:
        with pytest.raises(ValueError, match='other_platform'):
            await second.start(manager)
        assert first.busy and not second.busy
    finally:
        await first.close()

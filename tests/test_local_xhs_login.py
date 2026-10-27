"""Local QR keeps the old profile and the same window through human verification."""
import asyncio
from contextlib import asynccontextmanager
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from playwright.async_api import Error
import pytest

from api.services import interactive_login, xhs_login
from media_platform.xhs import browser as browser_module
from media_platform.xhs.session import read_session, save_session, session_path


@pytest.fixture
def local_browser(monkeypatch, tmp_path):
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(browser_module, 'web_login_browser_channel', lambda: 'chrome')
    state = {'cookies': [{'name': 'web_session', 'value': 'test-private-session',
                          'domain': '.xiaohongshu.com', 'path': '/', 'expires': -1}], 'origins': []}
    page = SimpleNamespace(goto=AsyncMock())
    context = SimpleNamespace(pages=[], new_page=AsyncMock(return_value=page), close=AsyncMock(),
                              storage_state=AsyncMock(return_value=state),
                              cookies=AsyncMock(return_value=state['cookies']), add_cookies=AsyncMock())
    launch = AsyncMock(return_value=context)
    chromium = SimpleNamespace(launch_persistent_context=launch, launch=AsyncMock())

    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(chromium=chromium)

    monkeypatch.setattr(interactive_login, 'async_playwright', playwright)
    service = xhs_login.XhsWebLogin(tmp_path)
    service.authenticated = AsyncMock(return_value=True)
    service.verification_required = AsyncMock(return_value=False)
    service.find_qr = AsyncMock(return_value='data:image/png;base64,test')
    service.open_login = AsyncMock()
    return SimpleNamespace(service=service, context=context, chromium=chromium, page=page,
                           launch=launch, state=state, playwright=playwright)


@pytest.mark.asyncio
async def test_existing_profile_reused_and_snapshot_saved_only_after_authentication(local_browser, tmp_path):
    fixture = local_browser
    profile = tmp_path / 'browser_data' / 'xhs_user_data_dir'
    profile.mkdir(parents=True)
    marker = profile / 'existing-profile'
    marker.write_text('keep')
    await fixture.service._run(True)
    assert fixture.launch.await_args.kwargs == {
        'user_data_dir': str(profile), 'channel': 'chrome', 'headless': False,
        'viewport': {'width': 1920, 'height': 1080}}
    fixture.chromium.launch.assert_not_awaited()
    assert marker.read_text() == 'keep'
    assert fixture.service.status()['local_browser']
    assert fixture.service.status()['status'] == 'authenticated'
    assert fixture.service.status()['qr_image'] is None
    assert read_session(tmp_path) == fixture.state
    assert 'test-private-session' not in json.dumps(fixture.service.status())
    fixture.context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_verification_keeps_window_then_qr_disappears_on_success(local_browser, monkeypatch, tmp_path):
    fixture = local_browser
    fixture.service.authenticated.side_effect = [False, False, True]
    fixture.service.verification_required.side_effect = [True, False]
    observed = []

    async def human_action(_):
        observed.append(fixture.service.state['status'])
        fixture.context.close.assert_not_awaited()
        assert not read_session(tmp_path)
        if len(observed) == 2:
            assert fixture.service.state['qr_image']

    monkeypatch.setattr(interactive_login.asyncio, 'sleep', human_action)
    manager = SimpleNamespace(_lock=asyncio.Lock(), status='idle', process=None)
    await fixture.service.start(manager, login_environment='local')
    await fixture.service.task
    assert observed == ['verification_required', 'waiting']
    fixture.launch.assert_awaited_once()
    assert fixture.service.state['status'] == 'authenticated'
    assert fixture.service.state['qr_image'] is None
    assert not fixture.service.busy and manager.status == 'idle'


@pytest.mark.asyncio
async def test_refresh_does_not_replace_profile_or_overwrite_existing_cookie(local_browser, tmp_path):
    fixture = local_browser
    save_session(tmp_path, fixture.state)
    await fixture.service._run(False)
    fixture.context.add_cookies.assert_not_awaited()
    fixture.launch.assert_awaited_once()


@pytest.mark.asyncio
async def test_saved_snapshot_can_bootstrap_empty_profile(local_browser, tmp_path):
    fixture = local_browser
    save_session(tmp_path, fixture.state)
    fixture.context.cookies.return_value = []
    await fixture.service._run(False)
    fixture.context.add_cookies.assert_awaited_once_with(fixture.state['cookies'])


@pytest.mark.asyncio
async def test_cancel_preserves_previous_session_and_closes_verification_window(local_browser, monkeypatch, tmp_path):
    fixture = local_browser
    save_session(tmp_path, fixture.state)
    before = session_path(tmp_path).read_bytes()
    fixture.service.authenticated.return_value = False
    fixture.service.verification_required.return_value = True
    waiting = asyncio.Event()

    async def hold(_):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(interactive_login.asyncio, 'sleep', hold)
    manager = SimpleNamespace(_lock=asyncio.Lock(), status='idle', process=None)
    await fixture.service.start(manager, refresh=True, login_environment='local')
    await waiting.wait()
    await fixture.service.cancel(manager)
    assert fixture.service.state['status'] == 'cancelled'
    assert session_path(tmp_path).read_bytes() == before
    fixture.context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('message,reason', [
    ('ProcessSingleton: profile already in use secret', 'login_profile_busy'),
    ('Target page, context or browser has been closed secret', 'login_browser_closed')])
async def test_browser_errors_are_actionable_and_private(local_browser, message, reason):
    fixture = local_browser
    fixture.launch.side_effect = Error(message)
    await fixture.service._run(False)
    assert fixture.service.state['reason'] == reason
    assert 'secret' not in json.dumps(fixture.service.status())


@pytest.mark.asyncio
async def test_collection_uses_same_local_profile_instead_of_other_browser(local_browser, monkeypatch, tmp_path):
    from media_platform.xhs import core
    import config
    fixture = local_browser
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('MEDIACRAWLER_WEB_QR_LOGIN', '1')
    monkeypatch.setenv('MEDIACRAWLER_LOGIN_ENVIRONMENT', 'local')
    monkeypatch.setattr(config, 'LOGIN_TYPE', 'qrcode')
    monkeypatch.setattr(config, 'ENABLE_IP_PROXY', False)
    monkeypatch.setattr(config, 'ENABLE_CDP_MODE', True)
    monkeypatch.setattr(config, 'CRAWLER_TYPE', 'search')
    monkeypatch.setattr(core, 'async_playwright', fixture.playwright)
    crawler = core.XiaoHongShuCrawler()
    crawler.launch_browser_with_cdp = AsyncMock()
    crawler.launch_browser = AsyncMock()
    crawler.create_xhs_client = AsyncMock(return_value=SimpleNamespace(pong=AsyncMock(return_value=True)))
    crawler.search = AsyncMock()
    await crawler.start()
    assert fixture.launch.await_args.kwargs['user_data_dir'] == str(tmp_path / 'browser_data' / 'xhs_user_data_dir')
    crawler.launch_browser_with_cdp.assert_not_awaited()
    crawler.launch_browser.assert_not_awaited()
    fixture.context.add_cookies.assert_not_awaited()
    crawler.search.assert_awaited_once()

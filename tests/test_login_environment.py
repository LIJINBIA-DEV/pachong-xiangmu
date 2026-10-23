import importlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from login_environment import default_login_environment, resolve_login_environment


def test_modes_keep_container_default_and_reject_local_without_desktop(monkeypatch):
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    assert default_login_environment() == resolve_login_environment() == 'server'
    with pytest.raises(ValueError, match='桌面'):
        resolve_login_environment('local')
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE')
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert resolve_login_environment() == 'local'
    assert resolve_login_environment('server') == 'server'


@pytest.mark.parametrize('mode,expected', [('local', [False, False, False]), ('server', [False, False, True])])
def test_child_browser_configuration(mode, expected):
    from login_environment import login_process_environment
    result = subprocess.run([sys.executable, '-c',
        'import config,json;print(json.dumps([config.ENABLE_CDP_MODE,config.CDP_CONNECT_EXISTING,config.HEADLESS]))'],
        env={**os.environ, **login_process_environment(mode)}, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['local', 'server'])
async def test_selection_reaches_child_only(tmp_path, monkeypatch, mode):
    from api.schemas.crawler import CrawlerStartRequest
    import config
    module = importlib.import_module('api.services.crawler_manager')
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    manager = module.CrawlerManager()
    manager._project_root = tmp_path
    captured = []

    def popen(command, **kwargs):
        captured.append((command, kwargs['env']))
        raise OSError('No real collection in this test')

    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    request = CrawlerStartRequest(platform='wb', login_environment=mode,
        login_type='cookie', cookies='SUB=test', image_subject_recognition=False)
    assert not await manager.start(request)
    command, env = captured[0]
    assert env['MEDIACRAWLER_LOGIN_ENVIRONMENT'] == mode
    assert env['MEDIACRAWLER_CONTAINER_MODE'] == ('1' if mode == 'server' else '0')
    assert command[command.index('--headless') + 1] == ('true' if mode == 'server' else 'false')
    assert 'MEDIACRAWLER_CONTAINER_MODE' not in os.environ


@pytest.mark.asyncio
async def test_explicit_server_qr_works_on_desktop_without_starting_collection(tmp_path, monkeypatch):
    from api.services.weibo_login import WeiboWebLogin
    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    service = WeiboWebLogin(tmp_path)
    service._run = AsyncMock()
    import asyncio
    manager = SimpleNamespace(_lock=asyncio.Lock(), status='idle', process=None)
    await service.start(manager, login_environment='server')
    await service.task
    service._run.assert_awaited_once_with(False)
    assert manager.process is None and manager.status == 'idle'

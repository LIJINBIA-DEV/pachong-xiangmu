"""Container defaults and Cookie failures without touching real data or services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest


def test_container_config_does_not_connect_desktop_cdp():
    env = {**os.environ, 'MEDIACRAWLER_CONTAINER_MODE': '1'}
    result = subprocess.run([sys.executable, '-c',
        'import config,json; print(json.dumps([config.ENABLE_CDP_MODE,config.CDP_CONNECT_EXISTING,config.HEADLESS,config.LOGIN_TYPE]))'],
        env=env, capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout) == [False, False, True, 'cookie']


@pytest.mark.asyncio
async def test_container_browser_uses_bundled_chromium(tmp_path, monkeypatch):
    from media_platform.weibo.core import WeiboCrawler
    import config
    monkeypatch.setenv('MEDIACRAWLER_BROWSER_CHANNEL', 'chromium')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, 'SAVE_LOGIN_STATE', True)
    chromium = SimpleNamespace(launch_persistent_context=AsyncMock(return_value='context'))
    assert await WeiboCrawler().launch_browser(chromium, None, None, headless=True) == 'context'
    assert chromium.launch_persistent_context.call_args.kwargs['channel'] == 'chromium'
    assert chromium.launch_persistent_context.call_args.kwargs['headless']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [
    (401, {'ok':0}), (403, {'ok':0}), (432, {'ok':0}),
    (200, {'ok':0,'msg':'登录失效 secret-body'}),
    (200, {'ok':0,'msg':'需要验证码 secret-body'}),
])
async def test_cookie_failure_pauses_once_without_logging_response(monkeypatch, status, body):
    from media_platform.weibo import client as module
    from media_platform.weibo.exception import LoginRequired
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE','1')
    calls = []; errors = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status,json=body)
    monkeypatch.setattr(module,'make_async_client',lambda proxy:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(module.utils.logger,'error',errors.append)
    client=module.WeiboClient(headers={},playwright_page=None,cookie_dict={})
    with pytest.raises(LoginRequired) as caught:
        await client.get_note_by_keyword('可爱 公园',page=1)
    assert len(calls)==1
    assert 'secret-body' not in str(caught.value) and not errors
    assert client.last_search_response['message_code']=='login_required'


@pytest.mark.asyncio
async def test_container_empty_search_is_still_exhaustion(monkeypatch):
    from media_platform.weibo import client as module
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE','1')
    def respond(request):
        return httpx.Response(200,json={'ok':0,'msg':'这里还没有内容','data':{'cards':[]}})
    monkeypatch.setattr(module,'make_async_client',lambda proxy:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    client=module.WeiboClient(headers={},playwright_page=None,cookie_dict={})
    assert await client.get_note_by_keyword('可爱 公园',page=1)=={'cards':[]}


@pytest.mark.asyncio
async def test_container_login_check_preserves_transport_failure(monkeypatch):
    from media_platform.weibo.client import WeiboClient
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    client = WeiboClient(headers={}, playwright_page=None, cookie_dict={})
    client.request = AsyncMock(side_effect=httpx.ConnectError('mock connection failed'))
    with pytest.raises(httpx.ConnectError):
        await client.pong()


@pytest.mark.asyncio
async def test_container_start_requires_cookie_and_forces_headless_without_network(tmp_path,monkeypatch):
    import importlib
    module=importlib.import_module('api.services.crawler_manager')
    from api.schemas.crawler import CrawlerStartRequest
    import config
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE','1')
    monkeypatch.setattr(config,'SAVE_DATA_PATH',str(tmp_path))
    manager=module.CrawlerManager()
    manager._project_root=tmp_path
    request=CrawlerStartRequest(platform='wb',login_type='cookie',image_subject_recognition=False)
    with pytest.raises(ValueError,match='Cookie'):
        await manager.start(request)
    commands=[]
    def popen(command,**kwargs):
        commands.append(command)
        raise OSError('test-no-process')
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    request=request.model_copy(update={'cookies':'SUB=fake-cookie'})
    assert not await manager.start(request)
    assert commands[0][commands[0].index('--lt')+1]=='cookie'
    assert commands[0][commands[0].index('--headless')+1]=='true'
    assert not request.headless
    assert all('fake-cookie' not in row.message for row in manager.logs)


def test_compose_is_arm64_cloud_only_and_keeps_new_data_separate():
    docker=shutil.which('docker')
    if not docker:
        pytest.skip('Docker CLI unavailable; Compose validation requires CLI only')
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'TYPESAFE_API_KEY':'test-key','SILICONFLOW_API_KEY':'test-key',
         'SPARK_BIND_IP':'127.0.0.1','APP_PORT':'18180'}
    result=subprocess.run([docker,'compose','--env-file','.env.spark.example','-f','compose.spark.yaml','config','--format','json'],
        cwd=root,env=env,capture_output=True,text=True,check=True,timeout=30)
    parsed=json.loads(result.stdout)
    assert set(parsed['services'])=={'app'}
    app=parsed['services']['app']
    assert app['platform']=='linux/arm64'
    assert app['environment']['MEDIACRAWLER_IMAGE_PROVIDER']=='siliconflow'
    assert app['environment']['MEDIACRAWLER_CONTAINER_MODE']=='1'
    assert app['restart']=='unless-stopped' and app['init']
    assert 'deploy' not in app and 'devices' not in app
    assert app['ports'][0]['host_ip']=='127.0.0.1'
    assert app['ports'][0]['published']=='18180'
    assert len(app['volumes'])==3
    assert all('/docker/runtime/' in mount['source'].replace('\\','/') for mount in app['volumes'])
    assert str(root/'data') not in {mount['source'] for mount in app['volumes']}


@pytest.mark.asyncio
@pytest.mark.parametrize('container', [True, False])
async def test_shutdown_stops_container_crawler_without_changing_desktop_lifecycle(monkeypatch, container):
    import api.services
    from api.main import close_image_subject_jobs
    from api.services.image_subject import image_subject_jobs
    if container:
        monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    else:
        monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    stop = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(api.services, 'crawler_manager', SimpleNamespace(stop=stop))
    monkeypatch.setattr(image_subject_jobs, 'close', close)
    await close_image_subject_jobs()
    assert stop.await_count == int(container)
    close.assert_awaited_once()

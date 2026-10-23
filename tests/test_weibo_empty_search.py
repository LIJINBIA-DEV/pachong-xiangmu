"""Replay search exhaustion through the real request/retry and search loop."""
import json
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from tenacity import RetryError, wait_none

from media_platform.weibo import client as module
from media_platform.weibo.exception import DataFetchError

EMPTY = {'ok': 0, 'msg': '这里还没有内容', 'data': {'cards': []}}
SEARCH_URL = 'https://m.weibo.cn/api/container/getIndex?page_type=searchall'


@pytest.fixture
def client(monkeypatch):
    # Keep the real five-attempt policy, removing only the wait from tests.
    monkeypatch.setattr(module.WeiboClient, 'request', module.WeiboClient.request.retry_with(wait=wait_none()))
    return module.WeiboClient(headers={}, playwright_page=None, cookie_dict={})


def transport(monkeypatch, respond):
    monkeypatch.setattr(module, 'make_async_client', lambda proxy: httpx.AsyncClient(transport=httpx.MockTransport(respond)))


@pytest.mark.asyncio
async def test_exact_empty_search_page_returns_once_without_error_log(client, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=EMPTY)
    transport(monkeypatch, respond)
    errors = []
    monkeypatch.setattr(module.utils.logger, 'error', errors.append)
    assert await client.get_note_by_keyword('卡哇伊 花箱', page=2) == {'cards': []}
    assert len(calls) == 1
    assert errors == []


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,url,method', [
    (200, {**EMPTY, 'msg': '登录失效'}, SEARCH_URL, 'GET'),
    (200, {**EMPTY, 'msg': '访问频繁，请稍后再试'}, SEARCH_URL, 'GET'),
    (429, EMPTY, SEARCH_URL, 'GET'),
    (403, EMPTY, SEARCH_URL, 'GET'),
    (500, EMPTY, SEARCH_URL, 'GET'),
    (200, {**EMPTY, 'data': {'cards': [{'mblog': {'id': '1'}}]}}, SEARCH_URL, 'GET'),
    (200, {**EMPTY, 'data': {}}, SEARCH_URL, 'GET'),
    (200, EMPTY, 'https://m.weibo.cn/api/statuses/show?page_type=searchall', 'GET'),
    (200, EMPTY, 'https://m.weibo.cn/api/container/getIndex?page_type=profile', 'GET'),
    (200, EMPTY, SEARCH_URL, 'POST'),
])
async def test_real_errors_and_other_endpoints_are_not_mistaken_for_exhaustion(client, monkeypatch, status, body, url, method):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    transport(monkeypatch, respond)
    with pytest.raises(RetryError) as caught:
        await client.request(method, url)
    assert isinstance(caught.value.last_attempt.exception(), DataFetchError)
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_empty_second_page_records_shortfall_and_continues_next_keyword(client, monkeypatch, tmp_path):
    from media_platform.weibo import core
    from collection_tasks import create_task, prepare_run
    first, second = '卡哇伊 花箱', '可爱 公园'
    task = create_task(tmp_path, {}, {first: 2, second: 2})
    run = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '0')
    monkeypatch.setenv('MEDIACRAWLER_WEIBO_SEARCH_TYPE', 'default')
    for name, value in {'KEYWORDS': f'{first},{second}', 'START_PAGE': 1, 'CRAWLER_MAX_NOTES_COUNT': 2,
                        'SAVE_DATA_OPTION': 'json', 'CRAWLER_MAX_SLEEP_SEC': 0}.items():
        monkeypatch.setattr(core.config, name, value)
    calls = []
    def respond(request):
        query = parse_qs(request.url.query.decode())
        keyword = query['containerid'][0].split('&q=', 1)[1]
        page = int(query['page'][0])
        calls.append((keyword, page))
        if keyword == first and page == 2:
            return httpx.Response(200, json=EMPTY)
        ids = ['1'] if keyword == first else ['2', '3']
        return httpx.Response(200, json={'ok': 1, 'data': {'cards': [{'mblog': {'id': nid}} for nid in ids]}})
    transport(monkeypatch, respond)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    crawler = core.WeiboCrawler()
    crawler.wb_client = client
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.search()
    assert calls == [(first, 1), (first, 2), (second, 1)]
    assert [call.args[0]['mblog']['id'] for call in saved.await_args_list] == ['1', '2', '3']
    state = json.loads(run.read_text(encoding='utf-8'))
    assert {k: state['results'][first][k] for k in ('retained', 'target', 'reason')} == {'retained': 1, 'target': 2, 'reason': 'search_exhausted'}
    assert {k: state['results'][second][k] for k in ('retained', 'target', 'reason')} == {'retained': 2, 'target': 2, 'reason': 'target_reached'}
    diagnostics = state['results'][first]['diagnostics']
    assert diagnostics['http_status'] == 200
    assert diagnostics['api_ok'] == 0 and diagnostics['message_code'] == 'empty_result'
    assert diagnostics['cards_count'] == diagnostics['parsed_count'] == 0
    assert diagnostics['pages_checked'] == 2
    assert state['result_times'][first]
    assert state['cursors'][first]['page'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,reason', [('http', 'request_failed'), ('structure', 'parse_failed')])
async def test_search_failure_is_logged_without_becoming_empty(client, monkeypatch, tmp_path, mode, reason):
    from media_platform.weibo import core
    from collection_tasks import create_task, prepare_run
    keyword = '卡哇伊 花箱'
    task = create_task(tmp_path, {}, {keyword: 2})
    run = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '0')
    monkeypatch.setenv('MEDIACRAWLER_WEIBO_SEARCH_TYPE', 'default')
    for name, value in {'KEYWORDS': keyword, 'START_PAGE': 1, 'CRAWLER_MAX_NOTES_COUNT': 2,
                        'SAVE_DATA_OPTION': 'json', 'CRAWLER_MAX_SLEEP_SEC': 0}.items():
        monkeypatch.setattr(core.config, name, value)
    if mode == 'http':
        transport(monkeypatch, lambda request: httpx.Response(403, json={'ok': 0, 'msg': 'private-message', 'data': {'cards': []}}))
        expected_exception = RetryError
    else:
        transport(monkeypatch, lambda request: httpx.Response(200, json={'ok': 1, 'data': {'cards': ['unexpected-card']}}))
        expected_exception = AttributeError
    crawler = core.WeiboCrawler()
    crawler.wb_client = client
    with pytest.raises(expected_exception):
        await crawler.search()
    result = json.loads(run.read_text(encoding='utf-8'))['results'][keyword]
    assert result['reason'] == reason and result['retained'] == 0
    assert result['diagnostics']['checked_page'] == 1
    assert result['diagnostics']['http_status'] == (403 if mode == 'http' else 200)
    assert 'private-message' not in run.read_text(encoding='utf-8')

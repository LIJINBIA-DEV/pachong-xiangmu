from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import importlib
import json

import pytest
from pydantic import ValidationError

from publication_time import BEIJING, PublicationWindow, publication_timestamp
from api.schemas.crawler import CrawlerStartRequest


@pytest.mark.parametrize(('mode', 'days'), [('day', 1), ('week', 7), ('month', 30)])
def test_presets_are_fixed_rolling_windows(mode, days):
    now = datetime(2026, 10, 26, 16, 0, tzinfo=BEIJING)
    window = PublicationWindow.resolve(mode, now=now)
    assert window.start == (now - timedelta(days=days)).timestamp()
    assert window.exclusion(window.start * 1000) is None
    assert window.exclusion(window.start - 1) == 'outside_time_range'
    assert window.exclusion(window.end) == 'outside_time_range'
    assert window.exclusion(None) == 'unknown_publish_time'


def test_custom_dates_include_both_full_days_in_beijing_time():
    window = PublicationWindow.resolve('custom', '2026-10-01', '2026-10-01')
    assert window.exclusion('2026-09-30T16:00:00Z') is None
    assert window.exclusion('2026-10-01 23:59:59.999') is None
    assert window.exclusion('2026-10-02T00:00:00+08:00') == 'outside_time_range'
    assert not window.older_page(['2026-09-01', None])
    assert not window.older_page(['2026-09-01', '2026-10-01'])
    assert window.older_page(['2026-09-01', '2026-09-30'])


@pytest.mark.parametrize('value', [1790899200, 1790899200000, '1790899200000', '2026-10-02T08:00:00+08:00', 'Fri Oct 02 08:00:00 +0800 2026'])
def test_platform_publication_formats_have_same_timestamp(value):
    assert publication_timestamp(value) == datetime(2026, 10, 2, 8, tzinfo=BEIJING).timestamp()


@pytest.mark.parametrize('value', [None, '', 'yesterday', True, -1, float('nan')])
def test_unknown_dates_are_not_fabricated_and_unlimited_keeps_legacy_behavior(value):
    assert publication_timestamp(value) is None
    assert PublicationWindow.resolve().exclusion(value) is None


@pytest.mark.parametrize('extra', [
    {'publish_time_range': 'custom'},
    {'publish_time_range': 'custom', 'publish_start_date': '2026-10-03', 'publish_end_date': '2026-10-01'},
    {'publish_time_range': 'custom', 'publish_start_date': '2026-02-30', 'publish_end_date': '2026-10-01'},
    {'publish_time_range': 'year'},
    {'publish_time_range': 'week', 'crawler_type': 'detail'},
])
def test_api_rejects_invalid_or_unsupported_ranges(extra):
    with pytest.raises(ValidationError):
        CrawlerStartRequest(platform='xhs', **extra)


def configure(monkeypatch, core):
    for name, value in {'KEYWORDS': '长沙 教师编', 'START_PAGE': 1, 'CRAWLER_MAX_NOTES_COUNT': 2,
                        'CRAWLER_MAX_SLEEP_SEC': 0, 'SAVE_DATA_OPTION': 'json'}.items():
        monkeypatch.setattr(core.config, name, value)
    monkeypatch.delenv('MEDIACRAWLER_COLLECTION_RUN', raising=False)
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '0')
    monkeypatch.setenv('MEDIACRAWLER_PUBLICATION_WINDOW', json.dumps(PublicationWindow.resolve('custom', '2026-10-01', '2026-10-10').as_dict()))


@pytest.mark.asyncio
async def test_xhs_filters_before_storage_comments_media_and_keeps_searching_for_target(monkeypatch):
    from media_platform.xhs import core
    configure(monkeypatch, core)
    times = {'new': '2026-10-20', 'ok1': '2026-10-02', 'unknown': None, 'old': '2026-09-01', 'ok2': '2026-10-09'}
    pages = [['new', 'ok1', 'unknown'], ['old', 'ok2']]
    async def search(**kwargs):
        return {'has_more': kwargs['page'] < 2, 'items': [{'id': nid} for nid in pages[kwargs['page'] - 1]]}
    crawler = core.XiaoHongShuCrawler()
    crawler.xhs_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search))
    crawler.get_note_detail_async_task = AsyncMock(side_effect=lambda note_id, **kwargs: {'note_id': note_id, 'time': times[note_id], 'xsec_token': ''})
    crawler.batch_get_note_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(core.xhs_store, 'update_xhs_note', save)
    await crawler.search()
    assert [call.args[0]['note_id'] for call in save.await_args_list] == ['ok1', 'ok2']
    assert [nid for call in crawler.batch_get_note_comments.await_args_list for nid in call.args[0]] == ['ok1', 'ok2']
    assert [call.args[0]['note_id'] for call in crawler.download_media.await_args_list] == ['ok1', 'ok2']
    assert all(call.kwargs['sort'] == core.SearchSortType.LATEST for call in crawler.xhs_client.get_note_by_keyword.await_args_list)


@pytest.mark.asyncio
async def test_weibo_filters_before_full_text_comments_media_and_handles_rfc_dates(monkeypatch):
    from media_platform.weibo import core
    configure(monkeypatch, core)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    times = {'old': 'Tue Sep 01 08:00:00 +0800 2026', 'ok1': 'Fri Oct 02 08:00:00 +0800 2026', 'unknown': None, 'ok2': 'Fri Oct 09 08:00:00 +0800 2026'}
    pages = [['old', 'unknown', 'ok1'], ['ok2']]
    async def search(**kwargs):
        return {'cards': [{'mblog': {'id': nid, 'created_at': times[nid]}} for nid in pages[kwargs['page'] - 1]]}
    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.prepare_note = AsyncMock(side_effect=lambda note: note)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', save)
    await crawler.search()
    assert [call.args[0]['mblog']['id'] for call in save.await_args_list] == ['ok1', 'ok2']
    assert [note['mblog']['id'] for call in crawler.batch_get_notes_full_text.await_args_list for note in call.args[0]] == ['ok1', 'ok2']
    assert all(call.kwargs['search_type'] == core.SearchType.REAL_TIME for call in crawler.wb_client.get_note_by_keyword.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize('platform', ['xhs', 'wb'])
async def test_three_old_pages_stop_with_shortfall_without_collecting_posts(monkeypatch, tmp_path, platform):
    from collection_tasks import create_task, prepare_run, SearchProgress
    core = importlib.import_module('media_platform.' + ('xhs' if platform == 'xhs' else 'weibo') + '.core')
    configure(monkeypatch, core)
    task = create_task(tmp_path, {}, {'长沙 教师编': 2})
    run = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    if platform == 'xhs':
        crawler = core.XiaoHongShuCrawler()
        search = AsyncMock(side_effect=lambda **kw: {'has_more': True, 'items': [{'id': str(kw['page'])}]})
        crawler.xhs_client = SimpleNamespace(get_note_by_keyword=search)
        crawler.get_note_detail_async_task = AsyncMock(side_effect=lambda note_id, **kw: {'note_id': note_id, 'time': '2026-09-01'})
        crawler.batch_get_note_comments = AsyncMock()
        store = core.xhs_store
        name = 'update_xhs_note'
    else:
        monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
        crawler = core.WeiboCrawler()
        search = AsyncMock(side_effect=lambda **kw: {'cards': [{'mblog': {'id': str(kw['page']), 'created_at': 'Tue Sep 01 08:00:00 +0800 2026'}}]})
        crawler.wb_client = SimpleNamespace(get_note_by_keyword=search)
        store = core.weibo_store
        name = 'update_weibo_note'
    save = AsyncMock()
    monkeypatch.setattr(store, name, save)
    await crawler.search()
    assert search.await_count == 3 and save.await_count == 0
    assert SearchProgress().run['results']['长沙 教师编']['reason'] == 'time_range_exhausted'


@pytest.mark.asyncio
async def test_manager_passes_fixed_window_and_reuses_original_window_for_supplement(monkeypatch, tmp_path):
    import config
    from collection_tasks import read_task, prepare_run
    module = importlib.import_module('api.services.crawler_manager')
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path))
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    request = CrawlerStartRequest(platform='xhs', login_environment='local', save_option='excel', keywords='长沙 教师编', publish_time_range='week', image_subject_recognition=False)
    manager = module.CrawlerManager()
    manager._read_output = AsyncMock()
    assert await manager.start(request)
    await manager._read_task
    first_window = json.loads(popen.call_args.kwargs['env']['MEDIACRAWLER_PUBLICATION_WINDOW'])
    run = json.loads(manager.collection_run.read_text())
    task = read_task(tmp_path, run['task_id'])
    assert task['config']['publication_window'] == first_window
    assert first_window['end'] - first_window['start'] == 7 * 86400
    extra = prepare_run(tmp_path, task, {'长沙 教师编': 1}, supplement=True)
    other = module.CrawlerManager()
    other._read_output = AsyncMock()
    assert await other.start(request, collection_run=extra)
    await other._read_task
    assert json.loads(popen.call_args.kwargs['env']['MEDIACRAWLER_PUBLICATION_WINDOW']) == first_window

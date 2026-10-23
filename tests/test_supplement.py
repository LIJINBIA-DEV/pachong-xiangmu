import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from PIL import Image

from api.routers import data as router
from api.schemas import CrawlerStartRequest
from api.services.manual_review import annotations, update_annotation
from api.services.data_browser import load_review_dataset, browse_posts
from api.services.supplement import plan, start_supplement
from collection_tasks import create_task, prepare_run, read_task, register_output, SearchProgress, finish_run, find_task


@pytest.fixture
def task_collection(tmp_path, monkeypatch):
    folder = tmp_path / 'weibo'
    folder.mkdir()
    path = folder / 'first.json'
    notes = [{'note_id': str(i), 'creator_hash': f'user{i}', 'source_keyword': group,
              'image_names': '001.jpg,002.jpg', 'content': group, 'semantic_result': 'matched'}
             for i, group in [(1, '可爱 公园'), (2, '可爱 公园'), (3, '萌 广场')]]
    path.write_text(json.dumps(notes), encoding='utf-8')
    for note in notes:
        media = tmp_path / 'wb/media' / note['note_id']
        media.mkdir(parents=True)
        for name in ('001.jpg','002.jpg'):
            Image.new('RGB',(32,32)).save(media/name)
    manager = SimpleNamespace(status='idle', task_credentials={}, start=AsyncMock(return_value=True))
    import config
    import api.services
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(router, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(api.services, 'crawler_manager', manager)
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    return tmp_path, path, manager, TestClient(app)


def complete(root, path):
    for key, account, image in [('1:可爱 公园', 'non_marketing', 'qualified'),
                                ('2:可爱 公园', 'marketing', 'qualified'),
                                ('3:萌 广场', 'non_marketing', 'qualified')]:
        update_annotation(root, path, key, 'account', account)
        update_annotation(root, path, key, 'image', image, '001.jpg')


def config():
    return CrawlerStartRequest(platform='wb', login_type='cookie', save_option='excel', keywords='可爱 公园,萌 广场',
                               max_notes_count=2, cookies='secret-cookie', semantic_api_key='secret-key')


@pytest.mark.asyncio
async def test_replacement_quotas_lineage_cursor_and_shared_annotations(task_collection, monkeypatch):
    root, path, manager, _ = task_collection
    complete(root, path)
    status = await start_supplement(root, path, manager, target=2, config=config())
    assert status['shortfall'] == 2
    request = manager.start.await_args.args[0]
    run_path = manager.start.await_args.kwargs['collection_run']
    run = json.loads(run_path.read_text(encoding='utf-8'))
    assert run['quotas'] == {'可爱 公园': 1, '萌 广场': 1}
    assert run['blocked_accounts'] == ['user2']
    assert run['seen']['可爱 公园'] == ['1', '2', '3']
    assert request.keywords == '可爱 公园,萌 广场'
    assert request.max_notes_count == 1
    task = read_task(root, status['task_id'])
    metadata = json.dumps(task)
    assert 'secret-key' not in metadata and 'secret-cookie' not in metadata
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run_path))
    progress = SearchProgress()
    progress.record('可爱 公园', 4, ['4'])
    # Only processed IDs are recorded: remaining candidates on page 4 are not lost.
    second = root / 'weibo/second.json'
    second.write_text(json.dumps([{'note_id': '4', 'creator_hash': 'user1', 'source_keyword': '可爱 公园',
                                  'image_names': '001.jpg', 'content': '公园可爱'}]), encoding='utf-8')
    media = root / 'wb/media/4'
    media.mkdir(parents=True)
    Image.new('RGB',(32,32)).save(media/'001.jpg')
    register_output(second)
    progress.record('可爱 公园', 4, result={'retained': 1, 'target': 1, 'reason': 'target_reached'})
    assert json.loads(run_path.read_text(encoding='utf-8'))['files'] == ['weibo/second.json']
    finish_run(run_path, 'completed')
    assert len(load_review_dataset(root, path)[0]) == 4
    assert browse_posts(root, path)['file_total'] == 4
    entries = annotations(root, second)['entries']
    assert entries['1:可爱 公园']['decision'] == 'qualified'
    assert entries['4:可爱 公园']['account'] == 'non_marketing'
    assert entries['4:可爱 公园']['decision'] is None
    update_annotation(root, second, '4:可爱 公园', 'image', 'qualified', '001.jpg')
    assert annotations(root, path)['entries']['4:可爱 公园']['decision'] == 'qualified'
    status = plan(root, path, manager)
    assert status['shortfall'] == 1
    await start_supplement(root, path, manager)
    next_run = json.loads(manager.start.await_args.kwargs['collection_run'].read_text(encoding='utf-8'))
    assert next_run['quotas'] == {'萌 广场': 1}  # Fulfilled group is never recollected.
    assert next_run['cursors']['可爱 公园']['page'] == 4
    assert '4' in next_run['seen']['萌 广场']


def test_button_plan_requires_completed_review(task_collection):
    root, path, manager, client = task_collection
    assert client.get('/api/data/supplement', params={'file': 'weibo/first.json'}).json()['review_complete'] is False
    response = client.post('/api/data/supplement', json={'file': 'weibo/first.json', 'target': 2, 'config': config().model_dump(mode='json')})
    assert response.status_code == 409 and response.json()['detail'] == 'review_incomplete'
    manager.start.assert_not_awaited()
    complete(root, path)
    assert plan(root, path, manager)['review_complete'] is True


@pytest.mark.asyncio
async def test_container_restart_requires_cookie_reentry_without_persisting_it(task_collection, monkeypatch):
    from pydantic import SecretStr
    root, path, manager, _ = task_collection
    complete(root, path)
    task = create_task(root, config().model_dump(mode='json', exclude={'cookies', 'semantic_api_key'}),
                       {'可爱 公园': 2, '萌 广场': 2}, 'weibo/first.json')
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE', '1')
    assert plan(root, path, manager)['needs_cookies']
    with pytest.raises(ValueError, match='cookies_required'):
        await start_supplement(root, path, manager)
    manager.start.assert_not_awaited()
    assert read_task(root, task['id'])['runs'] == []
    await start_supplement(root, path, manager, cookies=SecretStr('replacement-cookie'))
    assert manager.start.await_args.args[0].cookies == 'replacement-cookie'
    run = manager.start.await_args.kwargs['collection_run']
    assert 'replacement-cookie' not in run.read_text(encoding='utf-8')
    assert 'replacement-cookie' not in json.dumps(read_task(root, task['id']))


@pytest.mark.asyncio
async def test_container_supplement_uses_saved_qr_login_after_restart(task_collection, monkeypatch):
    from media_platform.weibo.session import save_session
    root, path, manager, _ = task_collection
    manager._project_root = root
    complete(root, path)
    snapshot = config().model_copy(update={'login_type': config().login_type.__class__('qrcode')}).model_dump(mode='json', exclude={'cookies','semantic_api_key'})
    task = create_task(root, snapshot, {'可爱 公园': 2, '萌 广场': 2}, 'weibo/first.json')
    monkeypatch.setenv('MEDIACRAWLER_CONTAINER_MODE','1')
    status = plan(root,path,manager)
    assert status['needs_qr_login'] and not status['needs_cookies']
    with pytest.raises(ValueError,match='qr_login_required'):
        await start_supplement(root,path,manager)
    save_session(root,{'cookies':[{'name':'SUB','value':'private-token','domain':'.weibo.cn','path':'/','expires':-1}], 'origins':[]})
    assert not plan(root,path,manager)['needs_qr_login']
    await start_supplement(root,path,manager)
    assert manager.start.await_args.args[0].login_type.value == 'qrcode'
    assert manager.start.await_args.args[0].cookies == ''
    assert 'private-token' not in json.dumps(read_task(root,task['id']))


def test_final_post_corrections_drive_shortfalls_and_survive_linked_rounds(task_collection, monkeypatch):
    root, path, manager, _ = task_collection
    complete(root, path)
    task = create_task(root, config().model_dump(mode='json'), {'可爱 公园': 2, '萌 广场': 2}, 'weibo/first.json')
    assert plan(root, path, manager)['shortfall'] == 2
    update_annotation(root, path, '2:可爱 公园', 'post', 'qualified')
    assert plan(root, path, manager)['shortfall'] == 1
    update_annotation(root, path, '3:萌 广场', 'post', 'unqualified')
    assert plan(root, path, manager)['shortfall'] == 2
    run = prepare_run(root, task, {'萌 广场': 2})
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    second = path.with_name('second.json')
    second.write_text('[]', encoding='utf-8')
    register_output(second)
    assert annotations(root, second)['entries']['2:可爱 公园']['decision'] == 'qualified'
    assert plan(root, second, manager)['shortfall'] == 2
    update_annotation(root, second, '2:可爱 公园', 'post', None)
    status = plan(root, path, manager)
    assert status['shortfall'] == 3 and status['review_complete']


@pytest.mark.asyncio
async def test_no_start_when_target_reached_or_active(task_collection):
    root, path, manager, _ = task_collection
    complete(root, path)
    task = create_task(root, config().model_dump(mode='json'), {'可爱 公园': 1, '萌 广场': 1}, 'weibo/first.json')
    assert plan(root, path, manager)['shortfall'] == 0
    with pytest.raises(ValueError, match='target_reached'):
        await start_supplement(root, path, manager)
    manager.status = 'running'
    with pytest.raises(ValueError, match='collection_active'):
        await start_supplement(root, path, manager)
    manager.start.assert_not_awaited()


def test_missing_round_is_reported_and_task_metadata_hidden(task_collection, monkeypatch):
    root, path, _, client = task_collection
    task = create_task(root, config().model_dump(mode='json'), {'可爱 公园': 2}, 'weibo/first.json')
    run = prepare_run(root, task, {'可爱 公园': 1})
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    register_output(root / 'weibo/missing.xlsx')
    assert client.get('/api/data/review', params={'file': 'weibo/first.json'}).status_code == 422
    assert [file['path'] for file in client.get('/api/data/files').json()['files']] == ['weibo/first.json']
    assert client.get('/api/data/stats').json()['total_files'] == 1


@pytest.mark.asyncio
async def test_failed_start_preserves_original_reviews(task_collection):
    root, path, manager, _ = task_collection
    complete(root, path)
    before = path.read_bytes()
    manager.start.return_value = False
    with pytest.raises(ValueError, match='supplement_start_failed'):
        await start_supplement(root, path, manager, 2, config())
    assert path.read_bytes() == before
    assert annotations(root, path)['entries']['1:可爱 公园']['decision'] == 'qualified'
    assert plan(root, path, manager)['last_status'] == 'failed'


@pytest.mark.asyncio
async def test_search_resumes_partial_page_skips_known_posts_and_blocked_accounts(task_collection, monkeypatch):
    from media_platform.weibo import core
    from tools.user_hash import anonymize_user_id
    root, path, _, _ = task_collection
    task = create_task(root, config().model_dump(mode='json'), {'可爱 公园': 3}, 'weibo/first.json')
    run = prepare_run(root, task, {'可爱 公园': 1}, ['1'], [anonymize_user_id('media')], supplement=True)
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '0')
    progress = SearchProgress()
    progress.record('可爱 公园', 4)
    for name, value in {'KEYWORDS': '可爱 公园', 'START_PAGE': 1, 'CRAWLER_MAX_NOTES_COUNT': 50,
                        'SAVE_DATA_OPTION': 'excel', 'CRAWLER_MAX_SLEEP_SEC': 0}.items():
        monkeypatch.setattr(core.config, name, value)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(return_value={'cards': [
        {'mblog': {'id': '1'}}, {'mblog': {'id': '2', 'user': {'id': 'media'}}},
        {'mblog': {'id': '3'}}, {'mblog': {'id': '4'}}]}))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.search()
    assert crawler.wb_client.get_note_by_keyword.await_args.kwargs['page'] == 4
    assert [call.args[0]['mblog']['id'] for call in saved.await_args_list] == ['3']
    persisted = json.loads(run.read_text(encoding='utf-8'))
    assert persisted['cursors']['可爱 公园']['page'] == 4
    assert persisted['seen']['可爱 公园'] == ['1', '2', '3']
    assert '4' not in persisted['seen']['可爱 公园']
    assert persisted['results']['可爱 公园']['retained'] == 1


@pytest.mark.asyncio
async def test_initial_crawl_saves_effective_parameters_without_credentials(tmp_path, monkeypatch):
    from api.services.crawler_manager import CrawlerManager
    from unittest.mock import Mock
    import config as settings
    # Import the module explicitly: services also exports the singleton by this name.
    import importlib
    module = importlib.import_module('api.services.crawler_manager')
    monkeypatch.setattr(settings, 'SAVE_DATA_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'CRAWLER_MAX_NOTES_COUNT', 7)
    monkeypatch.setattr(settings, 'WEIBO_SEARCH_TYPE', 'real_time')
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    manager = CrawlerManager()
    manager._read_output = AsyncMock()
    request = CrawlerStartRequest(platform='wb', save_option='excel', keywords='可爱 公园,萌 广场', cookies='private-cookie')
    assert await manager.start(request)
    await manager._read_task
    run = json.loads(manager.collection_run.read_text(encoding='utf-8'))
    task = read_task(tmp_path, run['task_id'])
    assert run['quotas'] == {'可爱 公园': 7, '萌 广场': 7}
    assert task['config']['weibo_search_type'] == 'real_time'
    assert 'cookies' not in task['config'] and 'semantic_api_key' not in task['config']
    assert popen.call_args.kwargs['env']['MEDIACRAWLER_COLLECTION_RUN'] == str(manager.collection_run)
    assert popen.call_args.kwargs['env']['MEDIACRAWLER_WEIBO_SEARCH_TYPE'] == 'real_time'
    assert not any('private-cookie' in log.message for log in manager.logs)

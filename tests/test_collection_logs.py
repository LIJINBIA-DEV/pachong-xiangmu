import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routers import data as router
from api.services.collection_logs import collection_logs, evidence
from collection_tasks import create_task, prepare_run, SearchProgress, finish_run


@pytest.fixture
def history(tmp_path, monkeypatch):
    path = tmp_path / 'weibo' / 'sample.json'
    path.parent.mkdir()
    path.write_text('[]', encoding='utf-8')
    task = create_task(tmp_path, {'cookies': 'secret', 'semantic_api_key': 'key'},
                       {'卡哇伊 花箱': 2, '萌 公园': 2}, 'weibo/sample.json')
    run = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    return tmp_path, path, task, run


def test_durable_rounds_diagnostics_legacy_uncertainty_and_no_secrets(history, monkeypatch):
    root, path, task, run = history
    progress = SearchProgress()
    progress.record('卡哇伊 花箱', 2, result={'retained': 1, 'target': 2, 'reason': 'search_exhausted'})
    progress.record('萌 公园', 4, result={'retained': 2, 'target': 2, 'reason': 'target_reached'})
    finish_run(run, 'completed')
    second = prepare_run(root, task, {'卡哇伊 花箱': 1}, supplement=True)
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(second))
    SearchProgress().record('卡哇伊 花箱', 3, result={'retained': 0, 'target': 1, 'reason': 'search_exhausted',
        'diagnostics': {'http_status': 200, 'api_ok': 0, 'message_code': 'empty_result',
                        'cards_count': 0, 'parsed_count': 0, 'Cookie': 'private-cookie', 'raw': 'private-body'}})
    finish_run(second, 'completed')
    # Reload from disk: no in-memory manager or console buffer is needed.
    result = collection_logs(root, path)
    assert len(result['rounds']) == 2
    assert [item['round'] for item in result['entries']] == [2, 1, 1]
    current = result['entries'][0]
    assert current['missing'] == 1 and current['page'] == 3
    assert current['evidence'] == 'confirmed_empty' and current['recorded_at']
    assert next(item for item in result['entries'] if item['round'] == 1 and item['missing'])['evidence'] == 'legacy_unknown'
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in ['private-cookie', 'private-body', 'Cookie', 'semantic_api_key'])
    assert result['rounds'][0]['started_at'] and result['rounds'][0]['finished_at']


def test_api_access_validation_and_unprocessed_groups(history, monkeypatch):
    root, path, _, run = history
    finish_run(run, 'failed')
    monkeypatch.setattr(router, 'data_root', lambda: root)
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    with TestClient(app) as client:
        result = client.get('/api/data/collection-logs', params={'file': 'weibo/sample.json'})
        assert result.status_code == 200
        assert all(item['evidence'] == 'not_reached' for item in result.json()['entries'])
        assert all(item['page'] is None for item in result.json()['entries'])
        assert client.get('/api/data/collection-logs', params={'file': '../secret.json'}).status_code == 403
        assert client.get('/api/data/collection-logs', params={'file': 'weibo/missing.json'}).status_code == 404


def test_parsing_failure_is_distinct_from_empty_api_and_budget():
    assert evidence('search_exhausted', {'cards_count': 9, 'parsed_count': 0}) == 'unparsed_cards'
    assert evidence('search_exhausted', {'cards_count': 0, 'parsed_count': 0}) == 'no_parsed_posts'
    assert evidence('search_exhausted', {'message_code': 'empty_result', 'http_status': 403, 'api_ok': 0, 'cards_count': 0}) != 'confirmed_empty'
    assert evidence('page_budget', {}) == 'page_budget'


def test_login_failure_survives_log_sanitization(history):
    root, path, _, run = history
    SearchProgress().record('萌 公园', 2, result={'retained': 0, 'target': 2, 'reason': 'login_required',
        'diagnostics': {'http_status': 403, 'message_code': 'login_required', 'Cookie': 'secret-cookie'}})
    finish_run(run, 'failed')
    entry = next(item for item in collection_logs(root, path)['entries'] if item['keyword'] == '萌 公园')
    assert entry['reason'] == entry['evidence'] == 'login_required'
    assert entry['diagnostics']['message_code'] == 'login_required'
    assert 'secret-cookie' not in json.dumps(entry)


def test_no_history_and_interrupted_group(history):
    root, path, _, run = history
    SearchProgress().record('萌 公园', 5, result={'retained': 1, 'target': 2, 'reason': 'searching'})
    finish_run(run, 'stopped')
    assert next(item for item in collection_logs(root, path)['entries'] if item['keyword'] == '萌 公园')['evidence'] == 'interrupted'
    orphan = root / 'weibo' / 'old.json'
    orphan.write_text('[]', encoding='utf-8')
    assert collection_logs(root, orphan) == {'task_id': None, 'rounds': [], 'entries': []}


def test_display_page_is_last_request_not_next_resume_cursor(history):
    root, path, _, _ = history
    SearchProgress().record('萌 公园', 6, result={'retained': 1, 'target': 2, 'reason': 'page_budget',
        'diagnostics': {'checked_page': 5, 'pages_checked': 5}})
    item = next(item for item in collection_logs(root, path)['entries'] if item['keyword'] == '萌 公园')
    assert item['page'] == 5

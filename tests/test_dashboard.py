from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.routers import dashboard as router_module
from api.services.dashboard import dashboard_snapshot
from api.services.manual_review import update_annotation
from collection_tasks import create_task, prepare_run, finish_run, atomic_json


@pytest.fixture
def task_data(tmp_path, monkeypatch):
    root = tmp_path
    path = root / 'weibo/posts.json'
    path.parent.mkdir()
    saved_at = int(datetime(2026, 10, 12, 2, tzinfo=timezone.utc).timestamp() * 1000)
    notes = [
        {'note_id': '1', 'source_keyword': '可爱 公园', 'content': '公园里的雕塑真可爱', 'semantic_result': 'matched', 'image_names': 'pass.jpg,reject.jpg,pending.jpg,error.jpg,bad.jpg,missing.jpg', 'last_modify_ts': saved_at},
        {'note_id': '2', 'source_keyword': '萌 雕塑', 'content': '雕塑真萌', 'semantic_result': 'matched', 'image_names': 'second.jpg', 'last_modify_ts': saved_at + 600000},
        {'note_id': '3', 'source_keyword': '可爱 公园', 'content': '公园真可爱', 'semantic_result': 'matched', 'comments_collection_stop_reason': 'comments_fetch_failed', 'last_modify_ts': saved_at},
        {'note_id': '4', 'source_keyword': '可爱 公园', 'content': '今天很可爱', 'semantic_result': 'matched', 'last_modify_ts': saved_at},
    ]
    path.write_text(json.dumps(notes, ensure_ascii=False), encoding='utf-8')
    for nid, names in [('1', ['pass.jpg', 'reject.jpg', 'pending.jpg', 'error.jpg', 'bad.jpg']), ('2', ['second.jpg'])]:
        directory = root / 'wb/media' / nid
        directory.mkdir(parents=True)
        for name in names:
            if name == 'bad.jpg':
                (directory / name).write_bytes(b'invalid-image')
            else:
                Image.new('RGB', (16, 16), 'green').save(directory / name)
    def prediction(root, image, version):
        name = image['key']
        value = 'qualified' if name in {'pass.jpg', 'second.jpg'} else 'unqualified' if name == 'reject.jpg' else None
        return {'status': 'error' if name == 'error.jpg' else 'unrecognized' if name == 'pending.jpg' else 'recognized', 'suggestion': value}
    monkeypatch.setattr('image_subject.cached_prediction', prediction)
    task = create_task(root, {'platform': 'wb', 'semantic_filter': True}, {'可爱 公园': 10, '萌 雕塑': 10, '萌 公园': 10}, 'weibo/posts.json')
    run_path = prepare_run(root, task, task['targets'])
    run = json.loads(run_path.read_text(encoding='utf-8'))
    run.update(files=['weibo/posts.json'], started_at='2026-10-12T02:00:00+00:00', results={'可爱 公园': {'reason': 'search_exhausted', 'retained': 3}, '萌 雕塑': {'reason': 'searching', 'retained': 1}})
    atomic_json(run_path, run)
    manager = SimpleNamespace(status='running', collection_run=run_path)
    return root, path, task, manager


def test_counts_use_current_task_real_evidence_and_model_denominator(task_data):
    root, path, task, manager = task_data
    # A human image override must not change the model statistics.
    update_annotation(root, path, '1:可爱 公园', 'image', 'qualified', 'reject.jpg')
    before = {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in root.rglob('*') if file.is_file()}
    result = dashboard_snapshot(root, manager)
    assert result['task']['id'] == task['id']
    assert result['task']['completed_groups'] == 1
    assert result['task']['current_keyword'] == '萌 雕塑'
    assert result['metrics']['collected_posts'] == 4
    assert result['metrics']['qualified_posts'] == 2  # Missing evidence and comment failure are gated.
    counts = result['metrics']['images']
    assert counts == {'downloaded': 5, 'download_pending': 1, 'download_failed': 1, 'qualified': 2, 'unqualified': 1, 'pending': 1, 'failed': 1, 'recognized': 3, 'pass_rate': 66.7}
    assert sum(point['collected'] for point in result['trend']) == 4
    assert sum(point['qualified'] for point in result['trend']) == 2
    after = {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in root.rglob('*') if file.is_file()}
    assert before == after


def test_historical_range_filters_charts_without_changing_whole_task_metrics(task_data):
    root, _, _, manager = task_data
    start = datetime(2026, 10, 12, 2, 9, tzinfo=timezone.utc)
    end = datetime(2026, 10, 12, 2, 11, tzinfo=timezone.utc)
    result = dashboard_snapshot(root, manager, 'custom', start, end)
    assert result['metrics']['collected_posts'] == 4
    assert sum(point['collected'] for point in result['trend']) == 1
    assert [row['collected'] for row in result['ranking']] == [0, 1, 0]
    with pytest.raises(ValueError, match='invalid_date_range'):
        dashboard_snapshot(root, manager, 'custom', end, start)


def test_idle_process_does_not_claim_saved_run_is_still_collecting(task_data):
    root, _, task, manager = task_data
    manager.status = 'idle'
    result = dashboard_snapshot(root, manager)
    assert result['task']['id'] == task['id']
    assert result['task']['current_keyword'] == ''
    assert result['groups'][1]['status'] == 'interrupted'
    assert all(group['status'] != 'running' for group in result['groups'])


def test_no_data_and_no_model_decisions_show_zero_and_unknown_rate(tmp_path):
    result = dashboard_snapshot(tmp_path, SimpleNamespace(status='idle', collection_run=None))
    assert result['task']['file'] is None
    assert result['metrics']['collected_posts'] == 0
    assert result['metrics']['images']['pass_rate'] is None
    assert not (tmp_path / '.manual-review').exists()


def test_endpoint_validates_filters_and_never_exposes_task_secrets(task_data, monkeypatch):
    root, _, task, manager = task_data
    monkeypatch.setattr(router_module, 'data_root', lambda: root)
    monkeypatch.setattr(router_module, 'crawler_manager', manager)
    app = FastAPI(); app.include_router(router_module.router, prefix='/api')
    client = TestClient(app)
    assert client.get('/api/dashboard').status_code == 200
    assert client.get('/api/dashboard?period=custom').status_code == 422
    assert client.get('/api/dashboard?period=wrong').status_code == 422
    assert client.get('/api/dashboard?task_id=../secret').status_code == 422
    metadata = root / '.collection-tasks' / task['id'] / 'task.json'
    saved = json.loads(metadata.read_text(encoding='utf-8')); saved['config'].update(cookies='PRIVATE_COOKIE', semantic_api_key='PRIVATE_KEY'); atomic_json(metadata, saved)
    response = client.get('/api/dashboard')
    assert 'PRIVATE_' not in response.text

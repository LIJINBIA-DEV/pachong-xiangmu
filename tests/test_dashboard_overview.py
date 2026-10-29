from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from api.routers import dashboard as router_module
from api.services.dashboard_overview import overview
from api.services.manual_review import update_annotation
from collection_tasks import atomic_json, create_task, prepare_run

NOW = datetime(2026, 10, 28, 8, tzinfo=timezone.utc)
IDLE = SimpleNamespace(status='idle', collection_run=None)


def note(nid, status='matched', topic='主题'):
    return {'note_id': nid, 'source_keyword': topic, 'content': '这是采集正文',
            'semantic_result': status, 'last_modify_ts': 1, 'time': 1}


def task_run(root, title, at, rows, *, task=None, status='completed', checked=None):
    task = task or create_task(root, {'platform': 'xhs', 'semantic_filter': True}, {title: 6})
    run = prepare_run(root, task, task['targets'])
    path = root / f'xhs/{run.stem}.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False))
    value = json.loads(run.read_text())
    value.update(started_at=at, finished_at=at, status=status, files=[str(path.relative_to(root))],
                 results={title: {'diagnostics': {'evaluated': checked or len(rows)}}})
    atomic_json(run, value)
    meta = root / '.collection-tasks' / task['id'] / 'task.json'
    task = json.loads(meta.read_text())
    if not task.get('anchor'):
        task['anchor'] = str(path.relative_to(root))
        atomic_json(meta, task)
    return task, run, path


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_week_is_cross_task_and_cards_charts_table_share_scope(tmp_path):
    a, _, _ = task_run(tmp_path, '甲', '2026-10-26T01:00:00+00:00', [note('a'), note('b', 'review')], checked=5)
    task_run(tmp_path, '乙', '2026-10-27T01:00:00+00:00', [note('c')])
    task_run(tmp_path, '上周', '2026-10-25T01:00:00+00:00', [note('old')])
    before = hashes(tmp_path)
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['tasks'] == 2
    assert result['metrics']['recorded'] == 3
    assert result['metrics']['checked'] == 6
    assert result['metrics']['retained'] == 2
    assert result['metrics']['review'] == 1  # Auto passes are not queued for humans.
    for key in ('recorded', 'retained', 'review'):
        assert result['metrics'][key] == sum(p[key] for p in result['timeline'])
        assert result['metrics'][key] == sum(t['metrics'][key] for t in result['tasks'])
    assert hashes(tmp_path) == before
    assert overview(tmp_path, IDLE, task_id=a['id'], now=NOW)['metrics']['recorded'] == 2
    assert overview(tmp_path, IDLE, 'all', now=NOW)['metrics']['recorded'] == 4
    assert overview(tmp_path, IDLE, 'today', now=NOW)['metrics']['recorded'] == 0


def test_supplements_deduplicate_records_but_count_each_collection(tmp_path):
    first_comment = {'note_id': 'a', 'comment_id': 'c1', 'content': '评论'}
    t, _, _ = task_run(tmp_path, '主题', '2026-10-27T01:00:00+00:00', [note('a'), first_comment])
    task_run(tmp_path, '主题', '2026-10-28T01:00:00+00:00', [note('a'), note('b', 'review'), first_comment,
             {'note_id': 'b', 'comment_id': 'c2', 'content': '新评论'}], task=t)
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['rounds'] == 2
    assert result['metrics']['recorded'] == 2
    assert result['metrics']['comments'] == 2
    today = overview(tmp_path, IDLE, 'today', now=NOW)
    assert today['metrics']['recorded'] == 1
    assert today['metrics']['retained'] == 0
    assert today['metrics']['comments'] == 1
    assert sum(p['recorded'] for p in today['timeline']) == 1


def test_human_conclusions_update_same_collection_period(tmp_path):
    _, _, path = task_run(tmp_path, '主题', '2026-10-26T01:00:00+00:00', [note('a', 'review'), note('b')])
    update_annotation(tmp_path, path, 'a:主题', 'post', 'qualified')
    update_annotation(tmp_path, path, 'b:主题', 'post', 'unqualified')
    before = hashes(tmp_path)
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['retained'] == 1
    assert result['metrics']['review'] == 0
    assert result['metrics']['excluded'] == 1
    assert result['metrics']['manual_retained'] == 1
    assert result['metrics']['manual_excluded'] == 1
    assert sum(result['metrics'][key] for key in ('retained', 'review', 'excluded', 'unfiltered', 'processing', 'duplicate')) == result['metrics']['recorded']
    assert hashes(tmp_path) == before


def test_legacy_main_semantic_pair_is_one_batch_with_summary_exclusions(tmp_path):
    def excel(path, semantic=False):
        book = Workbook(); sheet = book.active; sheet.title = 'Matched' if semantic else 'Contents'
        sheet.append(['note_id', 'source_keyword', 'semantic_result']); sheet.append(['a', '主题', 'matched'])
        if semantic:
            summary = book.create_sheet('Summary'); summary.append(['matched', 1]); summary.append(['excluded', 20])
        book.save(path)
    excel(tmp_path / 'xhs_search_20261027_101000.xlsx')
    excel(tmp_path / 'xhs_search_20261027_101000_semantic.xlsx', True)
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['tasks'] == 1
    assert result['metrics']['recorded'] == 1
    assert result['metrics']['checked'] == 21
    assert result['metrics']['excluded'] == 0  # Summary-only candidates are not fake full records.
    assert result['warnings']['estimated_round_times'] == 1
    assert result['tasks'][0]['duration_seconds'] is None


def test_empty_failed_and_missing_exports_are_not_lost(tmp_path):
    _, run, path = task_run(tmp_path, '失败任务', '2026-10-28T01:00:00+00:00', [], status='failed')
    path.unlink()
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['tasks'] == 1
    assert result['tasks'][0]['status'] == 'failed'
    assert result['metrics']['recorded'] == 0
    assert result['warnings']['missing_files'] == 1
    value = json.loads(run.read_text()); value['status'] = 'running'; atomic_json(run, value)
    assert overview(tmp_path, IDLE, now=NOW)['tasks'][0]['status'] == 'interrupted'
    assert overview(tmp_path, SimpleNamespace(status='running', collection_run=run), now=NOW)['tasks'][0]['status'] == 'running'


def test_same_post_in_distinct_tasks_is_a_record_per_task(tmp_path):
    task_run(tmp_path, '甲', '2026-10-27T01:00:00+00:00', [note('a')])
    task_run(tmp_path, '乙', '2026-10-28T01:00:00+00:00', [note('a')])
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['recorded'] == 2
    assert result['metrics']['unique_posts'] == 1


def test_custom_range_uses_shanghai_midnight_and_not_post_publication(tmp_path):
    task_run(tmp_path, '午夜前', '2026-10-27T15:59:59+00:00', [note('before')])
    task_run(tmp_path, '午夜后', '2026-10-27T16:00:00+00:00', [note('after')])
    result = overview(tmp_path, IDLE, 'today', now=NOW)
    assert result['metrics']['recorded'] == 1
    assert result['tasks'][0]['title'] == '午夜后'
    assert result['timeline'][0]['recorded'] == 1
    with pytest.raises(ValueError, match='invalid_date_range'):
        overview(tmp_path, IDLE, 'custom', now=NOW)
    custom = overview(tmp_path, IDLE, 'custom', '2026-10-27T00:00:00+08:00', '2026-10-27T23:59:59+08:00', now=NOW)
    assert custom['tasks'][0]['title'] == '午夜前'


def test_overview_endpoint_validation_and_no_secret_exposure(tmp_path, monkeypatch):
    task, _, _ = task_run(tmp_path, '主题', '2026-10-27T01:00:00+00:00', [note('a')])
    path = tmp_path / '.collection-tasks' / task['id'] / 'task.json'
    value = json.loads(path.read_text()); value['config'].update(semantic_api_key='PRIVATE_KEY', cookies='PRIVATE_COOKIE'); atomic_json(path, value)
    monkeypatch.setattr(router_module, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(router_module, 'crawler_manager', IDLE)
    app = FastAPI(); app.include_router(router_module.router, prefix='/api'); client = TestClient(app)
    response = client.get('/api/dashboard/overview?period=all')
    assert response.status_code == 200
    assert 'PRIVATE_' not in response.text
    assert str(tmp_path) not in response.text
    for query in ('period=invalid', 'period=custom', 'task_id=../secret', 'platform=../secret'):
        assert client.get('/api/dashboard/overview?' + query).status_code == 422


def test_no_data_remains_an_honest_zero(tmp_path):
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['tasks'] == result['metrics']['recorded'] == 0
    assert result['tasks'] == []
    assert not list(tmp_path.iterdir())


def test_legacy_uncertainty_matches_data_management_without_changing_export(tmp_path):
    from api.services.data_browser import browse_posts
    _, _, path = task_run(tmp_path, '主题', '2026-10-27T01:00:00+00:00',
                          [{**note('a'), 'selection_origin': 'review_policy', 'model_original_choice': 'review'}])
    before = path.read_bytes()
    assert overview(tmp_path, IDLE, now=NOW)['metrics']['review'] == 1
    assert browse_posts(tmp_path, path)['counts'] == {'review': 1}
    update_annotation(tmp_path, path, 'a:主题', 'post', 'qualified')
    assert overview(tmp_path, IDLE, now=NOW)['metrics']['retained'] == 1
    assert browse_posts(tmp_path, path)['counts'] == {'matched': 1}
    assert path.read_bytes() == before


def test_paired_comment_changes_invalidate_cached_dataset(tmp_path):
    contents = tmp_path / 'xhs_contents_20261027_100000.json'
    comments = tmp_path / 'xhs_comments_20261027_100000.json'
    contents.write_text(json.dumps([note('a')]))
    comments.write_text(json.dumps([{'note_id': 'a', 'comment_id': '1', 'content': '评论一'}]))
    assert overview(tmp_path, IDLE, now=NOW)['metrics']['comments'] == 1
    comments.write_text(json.dumps([{'note_id': 'a', 'comment_id': str(i), 'content': '评论'} for i in range(3)]))
    assert overview(tmp_path, IDLE, now=NOW)['metrics']['comments'] == 3


def test_media_is_availability_only_and_summary_counts_are_real(tmp_path):
    task, _, _ = task_run(tmp_path, '主题', '2026-10-27T01:00:00+00:00',
                          [{**note('a'), 'image_list': ['https://example.com/pic.jpg']},
                           {**note('b'), 'image_names': 'missing.jpg'}])
    directory = tmp_path / '.content-summaries' / hashlib.sha256(task['id'].encode()).hexdigest()
    directory.mkdir(parents=True)
    (directory / 'report.json').write_text(json.dumps({'status': 'ready', 'result': {'secret': 'DO_NOT_EXPOSE'}}))
    result = overview(tmp_path, IDLE, now=NOW)
    assert result['metrics']['retained'] == 2  # Missing images do not change a post decision.
    assert result['metrics']['images'] == 2
    assert result['metrics']['online_images'] == 1
    assert result['metrics']['missing_images'] == 1
    assert result['metrics']['downloaded'] == 0
    assert result['metrics']['summary_ready'] == 1
    assert 'DO_NOT_EXPOSE' not in json.dumps(result)

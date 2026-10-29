"""Only uncertain/unfiltered posts require a human; explicit human marks survive."""
import json

import pytest

from api.services.manual_review import annotations, storage_path, update_annotation
from api.services.review_export import export_review


@pytest.fixture
def posts(tmp_path):
    folder = tmp_path/'xhs'
    folder.mkdir()
    path = folder/'posts.json'
    notes = [{'note_id': str(i), 'source_keyword': '武汉消费', 'title': f'体验{i}',
        'content': '武汉消费体验。', 'semantic_rule': 'topic', 'topic_evidence': '武汉消费体验。',
        'semantic_result': status, 'manual_review_required': True}
        for i, status in enumerate(['matched', 'review', 'pending', 'unfiltered', 'matched'], 1)]
    notes[-1].update(selection_origin='review_policy', model_original_choice='review')
    path.write_text(json.dumps(notes, ensure_ascii=False))
    return tmp_path, path


def test_queue_distinguishes_model_passes_uncertainty_and_legacy_candidates(posts):
    root, path = posts
    before = path.read_bytes()
    result = annotations(root, path, persist=False)
    first = result['entries']['1:武汉消费']
    assert first['decision'] == 'qualified' and first['decision_source'] == 'automatic'
    assert first['screening_passed'] and first['post_decision'] is None
    assert result['completed'] == 1 and result['total'] == 5
    assert {key for key, entry in result['entries'].items() if entry['decision'] is None} == {
        '2:武汉消费', '3:武汉消费', '4:武汉消费', '5:武汉消费'}
    assert not storage_path(root, path).exists() and path.read_bytes() == before


def test_human_corrections_and_reset_keep_the_model_baseline(posts):
    root, path = posts
    original = path.read_bytes()
    update_annotation(root, path, '1:武汉消费', 'post', 'unqualified')
    update_annotation(root, path, '2:武汉消费', 'post', 'qualified')
    saved = storage_path(root, path).read_bytes()
    result = annotations(root, path)
    assert result['entries']['1:武汉消费']['decision_reason'] == 'manual_unqualified'
    assert result['entries']['2:武汉消费']['decision_reason'] == 'manual_qualified'
    assert storage_path(root, path).read_bytes() == saved
    update_annotation(root, path, '1:武汉消费', 'post', None)
    update_annotation(root, path, '2:武汉消费', 'post', None)
    result = annotations(root, path)
    assert result['entries']['1:武汉消费']['decision_reason'] == 'semantic_passed'
    assert result['entries']['2:武汉消费']['decision'] is None
    assert path.read_bytes() == original


def test_all_six_model_passes_need_no_manual_clicks_and_can_export(posts):
    root, path = posts
    notes = json.loads(path.read_text())
    path.write_text(json.dumps([{**notes[0], 'note_id': str(i)} for i in range(6)]))
    original = path.read_bytes()
    result = annotations(root, path, persist=False)
    assert result['completed'] == result['total'] == 6
    assert all(entry['decision_source'] == 'automatic' and entry['post_decision'] is None
               for entry in result['entries'].values())
    _, _, counts = export_review(root, path)
    assert counts['retained'] == 6 and counts['pending'] == 0
    assert path.read_bytes() == original and not storage_path(root, path).exists()


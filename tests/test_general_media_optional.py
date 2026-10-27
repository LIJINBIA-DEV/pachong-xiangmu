"""Obsolete spatial/image policies cannot change current post review."""
import hashlib
import json
from threading import Event
from zipfile import ZipFile

import pytest

from api.services.manual_review import annotations, storage_path, update_annotation, write_state
from api.services.review_package import build_package
from semantic_quality import image_requirement_problem, saved_jev_rejection
from semantic_rules import relation_instructions, target_scope


def test_old_image_predictions_and_place_taxonomy_are_inactive(tmp_path, monkeypatch):
    path = tmp_path / 'xhs' / 'posts.json'
    path.parent.mkdir()
    path.write_text(json.dumps([{'note_id': '1', 'source_keyword': '可爱 宠物',
        'content': '我家的宠物真可爱', 'image_list': '', 'semantic_object_type': 'pet',
        'quality_reason': 'pet_not_allowed', 'jev_original_choice': 'reject'}]))
    state = {'version': 1, 'accounts': {}, 'posts': {'1:可爱 宠物': {
        'images': {'old.jpg': 'unqualified'}, 'image_sources': {'old.jpg': 'model'}}}}
    write_state(tmp_path, path, state)
    before = storage_path(tmp_path, path).read_bytes()
    def inference_forbidden(*args, **kwargs):
        pytest.fail('Review tried to read an image-model result')
    monkeypatch.setattr('image_subject.cached_prediction', inference_forbidden)
    monkeypatch.setattr('image_subject.fingerprint', inference_forbidden)
    entry = annotations(tmp_path, path)['entries']['1:可爱 宠物']
    assert entry['requires_images'] is False and entry['decision'] is None
    assert storage_path(tmp_path, path).read_bytes() == before
    assert saved_jev_rejection({'semantic_object_type': 'pet', 'quality_reason': 'pet_not_allowed'}) is None
    assert image_requirement_problem({'image_list': ''}) is None
    assert target_scope('公园') == target_scope('老师') == target_scope('宠物')
    assert relation_instructions('公园') == relation_instructions('老师')
    assert update_annotation(tmp_path, path, '1:可爱 宠物', 'post', 'qualified')['completed'] == 1


def test_package_exports_approved_text_posts_and_all_optional_downloads(tmp_path):
    path = tmp_path / 'xhs' / 'posts.json'
    path.parent.mkdir()
    path.write_text(json.dumps([
        {'note_id': '1', 'content': '纯文字内容'},
        {'note_id': '2', 'content': '有附件的内容', 'image_names': 'old-rejected.jpg'},
    ]))
    media = tmp_path / 'xhs/media/2'
    media.mkdir(parents=True)
    # File packaging does not classify or decode image contents.
    (media / 'old-rejected.jpg').write_bytes(b'original saved attachment')
    update_annotation(tmp_path, path, '1:', 'post', 'qualified')
    update_annotation(tmp_path, path, '2:', 'image', 'unqualified', 'old-rejected.jpg')
    update_annotation(tmp_path, path, '2:', 'post', 'qualified')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    output = tmp_path / 'result.zip'
    counts = build_package(tmp_path, path, output, Event(), lambda *args: None)
    assert counts['retained'] == 2 and counts['images'] == 1
    with ZipFile(output) as package:
        assert '审核结果.xlsx' in package.namelist()
        assert any(name.endswith('/old-rejected.jpg') for name in package.namelist())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.asyncio
async def test_removed_inference_entry_point_cannot_start_a_model(tmp_path):
    from image_subject import recognize_files
    with pytest.raises(ValueError, match='image_recognition_removed'):
        await recognize_files(tmp_path, [])


def test_uncertain_general_evaluation_never_fills_the_initial_screening_target(tmp_path):
    from types import SimpleNamespace
    from api.services.dashboard import collection_progress
    from collection_tasks import create_task, prepare_run, atomic_json
    path = tmp_path / 'xhs/posts.json'
    path.parent.mkdir()
    path.write_text(json.dumps([{'note_id': '1', 'content': '老师工作很认真',
        'source_keyword': '认真 老师', 'semantic_rule': 'evaluation',
        'semantic_result': 'review', 'evaluation_evidence': '老师工作很认真',
        'evaluation_target_evidence': '老师工作很认真'}]))
    task = create_task(tmp_path, {'platform': 'xhs', 'semantic_filter': True}, {'认真 老师': 1}, 'xhs/posts.json')
    run = prepare_run(tmp_path, task, task['targets'])
    value = json.loads(run.read_text()); value['files'] = ['xhs/posts.json']; atomic_json(run, value)
    manager = SimpleNamespace(status='running', stage='running', log_session_id='test', started_at=None, collection_run=run)
    progress = collection_progress(tmp_path, manager)
    assert progress['saved'] == 1 and progress['qualified'] == 0 and progress['percent'] == 0

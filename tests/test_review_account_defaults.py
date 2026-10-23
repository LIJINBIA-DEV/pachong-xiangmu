import json

import pytest
from PIL import Image

from api.services.manual_review import annotations, read_state, storage_path, update_annotation
from tools.user_hash import anonymize_user_id
from weibo_account_filter import load_blocklist


def collection(tmp_path, notes, platform='weibo'):
    folder = tmp_path / platform
    folder.mkdir()
    path = folder / 'posts.json'
    path.write_text(json.dumps(notes), encoding='utf-8')
    for note in notes:
        media = tmp_path / ('wb' if platform == 'weibo' else platform) / 'media' / note['note_id']
        media.mkdir(parents=True, exist_ok=True)
        for name in note.get('image_names', '').split(','):
            if name:
                Image.new('RGB', (32, 32)).save(media / name)
    return path


def test_default_accounts_are_persisted_and_images_still_require_review(tmp_path):
    path = collection(tmp_path, [{'note_id': '1', 'creator_hash': 'personal', 'image_names': '001.jpg', 'nickname': '小张', 'author_verified': False},
                                 {'note_id': '2', 'creator_hash': 'personal', 'image_names': '001.jpg', 'nickname': '小张', 'author_verified': False}])
    original = path.read_bytes()
    entries = annotations(tmp_path, path)['entries']
    assert entries['1:']['account'] == entries['2:']['account'] == 'non_marketing'
    assert entries['1:']['account_source'] == 'default'
    assert entries['1:']['decision_reason'] == 'images_pending'
    assert read_state(tmp_path, path)['accounts']['creator:personal']['source'] == 'default'
    mark = storage_path(tmp_path, path).read_bytes()
    annotations(tmp_path, path)
    assert storage_path(tmp_path, path).read_bytes() == mark
    result = update_annotation(tmp_path, path, '1:', 'image', 'qualified', '001.jpg')
    assert result['entries']['1:']['decision'] == 'qualified'
    assert path.read_bytes() == original


@pytest.mark.parametrize('category', ['bot', 'media', 'government'])
@pytest.mark.parametrize('identity', ['creator_hash', 'creator_id', 'user'])
def test_all_downloaded_lists_exclude_accounts_even_after_positive_override(tmp_path, category, identity):
    uid = next(uid for uid, reason in load_blocklist()[0].items() if reason == 'account_blocklist_' + category)
    note = {'note_id': 'post', 'image_names': '001.jpg'}
    note[identity] = anonymize_user_id(uid) if identity == 'creator_hash' else {'id': uid} if identity == 'user' else uid
    path = collection(tmp_path, [note])
    entry = annotations(tmp_path, path)['entries']['post:']
    assert entry['account'] == 'marketing'
    assert entry['account_source'] == 'blocklist'
    assert entry['account_reason'] == 'account_blocklist_' + category
    assert entry['decision'] == 'unqualified'
    entry = update_annotation(tmp_path, path, 'post:', 'account', 'non_marketing')['entries']['post:']
    assert entry['account'] == 'marketing'


def test_human_marketing_and_explicit_reset_are_preserved(tmp_path):
    path = collection(tmp_path, [{'note_id': '1', 'creator_hash': 'personal', 'image_names': '001.jpg'}])
    update_annotation(tmp_path, path, '1:', 'image', 'qualified', '001.jpg')
    update_annotation(tmp_path, path, '1:', 'account', 'marketing')
    assert annotations(tmp_path, path)['entries']['1:']['decision'] == 'unqualified'
    update_annotation(tmp_path, path, '1:', 'account', None)
    assert annotations(tmp_path, path)['entries']['1:']['account'] is None
    assert annotations(tmp_path, path)['entries']['1:']['decision_reason'] == 'account_pending'


def test_legacy_human_marks_are_preserved_and_other_platforms_unchanged(tmp_path):
    path = collection(tmp_path, [{'note_id': '1', 'creator_hash': 'personal', 'image_names': '001.jpg'}])
    target = storage_path(tmp_path, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'version': 1, 'posts': {}, 'accounts': {'creator:personal': {'decision': 'marketing'}}}), encoding='utf-8')
    assert annotations(tmp_path, path)['entries']['1:']['account'] == 'marketing'
    other = collection(tmp_path, [{'note_id': '1', 'creator_hash': 'personal', 'image_names': '001.jpg'}], 'xhs')
    assert annotations(tmp_path, other)['entries']['1:']['account'] is None


def test_post_id_is_not_treated_as_an_author_uid(tmp_path):
    uid = next(iter(load_blocklist()[0]))
    path = collection(tmp_path, [{'note_id': uid, 'creator_hash': 'personal', 'image_names': '001.jpg'}])
    entry = annotations(tmp_path, path)['entries'][uid + ':']
    assert entry['account'] == 'non_marketing' and entry['account_rejection_reason'] is None


@pytest.mark.parametrize('fields', [
    {'nickname': '折服sh'},
    {'nickname': '小张', 'author_verified': True},
    {'nickname': '普***称'},
    {'nickname': '某地发布'},
])
def test_non_excluded_accounts_default_to_personal_even_without_confirmed_identity(tmp_path, fields):
    path = collection(tmp_path, [{'note_id': 'n', 'creator_hash': 'ordinary', 'image_names': '001.jpg', **fields}])
    original = path.read_bytes()
    entry = annotations(tmp_path, path)['entries']['n:']
    assert entry['account'] == 'non_marketing'
    assert entry['account_source'] == 'default'
    assert entry['account_identity_status'] == 'review'  # Keep the underlying uncertainty honest.
    assert entry['account_rejection_reason'] is None
    assert entry['decision_reason'] == 'images_pending'
    entry = update_annotation(tmp_path, path, 'n:', 'image', 'qualified', '001.jpg')['entries']['n:']
    assert entry['decision'] == 'qualified'
    assert path.read_bytes() == original


def test_old_identity_pending_defaults_migrate_but_all_human_marks_survive(tmp_path):
    notes = [{'note_id': str(i), 'creator_hash': str(i), 'nickname': '普通昵称', 'image_names': '001.jpg'} for i in range(3)]
    path = collection(tmp_path, notes)
    target = storage_path(tmp_path, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'version': 1, 'posts': {'0:': {'images': {'001.jpg': None}, 'image_sources': {'001.jpg': 'manual'}, 'post_decision': 'unqualified', 'post_decision_source': 'manual'}},
        'accounts': {'creator:0': {'decision': None, 'source': 'identity_review'},
                     'creator:1': {'decision': None, 'source': 'manual'},
                     'creator:2': {'decision': 'marketing', 'source': 'manual'}}}), encoding='utf-8')
    entries = annotations(tmp_path, path)['entries']
    assert entries['0:']['account'] == 'non_marketing'
    assert entries['0:']['images']['001.jpg'] is None
    assert entries['0:']['post_decision'] == 'unqualified'
    assert entries['1:']['account'] is None
    assert entries['2:']['account'] == 'marketing'
    stable = target.read_bytes()
    annotations(tmp_path, path)
    assert target.read_bytes() == stable

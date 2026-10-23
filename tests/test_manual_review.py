from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from PIL import Image

from api.routers import data as data_router
from api.services.manual_review import annotations, review_outcome, storage_path, update_annotation


@pytest.fixture
def collection(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(data_router, 'DATA_DIR', tmp_path)
    folder = tmp_path / 'weibo'
    folder.mkdir()
    path = folder / 'posts.json'
    notes = [
        {'note_id': '1', 'nickname': '同***名', 'creator_hash': 'hash-a', 'source_keyword': '可爱 公园', 'image_names': '001.jpg,002.png', 'content': '公园里的猫形雕塑真可爱'},
        {'note_id': '2', 'nickname': '同***名', 'creator_hash': 'hash-a', 'image_names': '001.jpg'},
        {'note_id': '3', 'nickname': '同***名', 'creator_hash': 'hash-b', 'image_names': '001.jpg'},
        {'note_id': '4', 'nickname': '同***名', 'image_names': '001.jpg'},
        {'note_id': '5', 'nickname': '同***名', 'image_names': '001.jpg'},
    ]
    # This fixture exercises review behavior for confirmed individual accounts.
    for note in notes:
        note.update(author_verified=True, author_verification='个人博主')
    path.write_text(json.dumps(notes, ensure_ascii=False), encoding='utf-8')
    for note in notes:
        media = tmp_path / 'wb/media' / note['note_id']
        media.mkdir(parents=True)
        for name in note['image_names'].split(','):
            Image.new('RGB', (32, 32)).save(media / name)
    app = FastAPI()
    app.include_router(data_router.router, prefix='/api')
    return tmp_path, path, TestClient(app)


def change(client, key='1:可爱 公园', kind='image', decision='qualified', image='001.jpg', file='weibo/posts.json'):
    return client.patch('/api/data/review', json={'file': file, 'post_key': key, 'kind': kind, 'decision': decision, 'image_key': image})


def test_not_downloaded_and_partial_images_keep_stable_keys(collection):
    root, path, client = collection
    for name in ('001.jpg', '002.png'):
        (root / 'wb/media/1' / name).unlink()
    imgs = annotations(root, path)['entries']['1:可爱 公园']['review_images']
    assert [img['key'] for img in imgs] == ['001.jpg', '002.png']
    assert all(not img['local'] and img['url'] == '' for img in imgs)
    assert change(client).status_code == 200
    local = root / 'wb/media/1'
    local.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (32, 32)).save(local / '001.jpg')
    entry = annotations(root, path)['entries']['1:可爱 公园']
    assert [img['key'] for img in entry['review_images']] == ['001.jpg', '002.png']
    assert entry['review_images'][0]['local'] and not entry['review_images'][1]['local']
    assert entry['images']['001.jpg'] == 'qualified'


@pytest.mark.parametrize('human', ['qualified', 'unqualified', None])
def test_download_recovery_preserves_human_mark_and_reset(collection, human):
    root, path, client = collection
    image = root / 'wb/media/1/001.jpg'
    image.unlink()
    original = path.read_bytes()
    change(client, decision=human)
    Image.new('RGB', (32, 32)).save(image)
    entry = annotations(root, path)['entries']['1:可爱 公园']
    assert entry['images'].get('001.jpg') == human
    assert entry['review_images'][0]['decision_source'] == 'manual'
    assert path.read_bytes() == original


@pytest.mark.parametrize('reason,body', [('keyword_miss','第一张真可爱'),('comments_fetch_failed','公园雕塑真可爱')])
def test_collection_gate_cannot_be_overridden_but_keeps_human_marks(collection,reason,body):
    root,path,client=collection
    notes=json.loads(path.read_text(encoding='utf-8'))
    notes[0].update(content=body,semantic_result='review',semantic_source='comments_unavailable',semantic_comment_stop_reason='comments_fetch_failed')
    path.write_text(json.dumps(notes,ensure_ascii=False),encoding='utf-8')
    change(client,decision='qualified')
    change(client,kind='post',decision='qualified')
    entry=annotations(root,path)['entries']['1:可爱 公园']
    assert entry['decision']=='unqualified' and entry['semantic_rejection_reason']==reason
    assert entry['post_decision']=='qualified' and entry['images']['001.jpg']=='qualified'
    from api.services.review_export import export_review
    with pytest.raises(ValueError,match='review_export_empty'):
        export_review(root,path)


@pytest.mark.parametrize('fields,reason', [
    ({'jev_original_choice':'reject','semantic_object_type':'person'},'semantic_reject'),
    ({'jev_original_choice':'review','semantic_object_type':'pet'},'pet_not_allowed'),
    ({'jev_original_choice':'keep','jev_original_object_type':'pet'},'pet_not_allowed'),
])
def test_legacy_jev_negative_is_excluded_despite_positive_images_and_override(collection,fields,reason):
    root,path,client=collection
    notes=json.loads(path.read_text(encoding='utf-8'))
    notes[0].update(fields)
    path.write_text(json.dumps(notes,ensure_ascii=False),encoding='utf-8')
    original=path.read_bytes()
    change(client)
    change(client,kind='post',decision='qualified')
    entry=annotations(root,path)['entries']['1:可爱 公园']
    assert entry['decision']==entry['automatic_decision']=='unqualified'
    assert entry['decision_reason']==entry['semantic_rejection_reason']==reason
    assert entry['decision_source']=='automatic'
    assert entry['images']['001.jpg']=='qualified'
    assert entry['post_decision']=='qualified'  # Preserve the old mark for audit.
    assert path.read_bytes()==original
    from types import SimpleNamespace
    from api.services.supplement import plan
    status=plan(root,path,SimpleNamespace(status='idle',task_credentials={}))
    group=next(group for group in status['groups'] if group['keyword']=='可爱 公园')
    assert group['retained']==0 and group['excluded']==1


def test_derived_decision_roundtrip_and_source_untouched(collection):
    root, path, client = collection
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    change(client)
    change(client, kind='account', decision='non_marketing')
    state = client.get('/api/data/review', params={'file': 'weibo/posts.json'}).json()
    assert state['completed'] == 1
    one = state['entries']['1:可爱 公园']
    assert one['decision'] == 'qualified' and one['images']['001.jpg'] == 'qualified' and one['account'] == 'non_marketing'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    # New reader/process loads marks from disk, not an in-memory cache.
    assert 'decision' not in json.loads(storage_path(root, path).read_text(encoding='utf-8'))['posts']['1:可爱 公园']
    change(client, kind='account', decision=None)
    assert annotations(root, path)['completed'] == 0
    assert annotations(root, path)['entries']['1:可爱 公园']['images']['001.jpg'] == 'qualified'


def test_account_sharing_requires_hash_and_is_batch_scoped(collection):
    root, path, client = collection
    state = change(client, kind='account', decision='marketing').json()['entries']
    assert state['1:可爱 公园']['account'] == state['2:']['account'] == 'marketing'
    assert state['1:可爱 公园']['decision'] == state['2:']['decision'] == 'unqualified'
    assert state['3:']['account'] == 'non_marketing'
    assert state['4:']['account_scope'] == 'post_only'
    state = change(client, key='4:', kind='account', decision='non_marketing').json()['entries']
    assert state['5:']['account'] == 'non_marketing'
    second = path.with_name('another.json')
    second.write_bytes(path.read_bytes())
    assert annotations(root, second)['entries']['1:可爱 公园']['account'] == 'non_marketing'


@pytest.mark.parametrize('overrides,status', [
    ({'kind': 'account', 'decision': 'qualified'}, 422),
    ({'kind': 'post', 'decision': 'marketing'}, 422),
    ({'kind': 'unknown', 'decision': 'qualified'}, 422),
    ({'decision': 'unexpected'}, 422),
    ({'kind': 'image', 'image_key': None}, 422),
    ({'image_key': 'wrong.jpg'}, 404),
    ({'post_key': 'missing'}, 404),
    ({'file': '../outside.json'}, 403),
])
def test_invalid_changes_cannot_create_annotation(collection, overrides, status):
    root, path, client = collection
    body = {'file': 'weibo/posts.json', 'post_key': '1:可爱 公园', 'kind': 'image', 'decision': 'qualified', 'image_key': '001.jpg'}
    assert client.patch('/api/data/review', json={**body, **overrides}).status_code == status
    assert not storage_path(root, path).exists()


def test_annotation_files_hidden_from_data_file_list_and_stats(collection):
    _, _, client = collection
    change(client)
    assert [file['path'] for file in client.get('/api/data/files').json()['files']] == ['weibo/posts.json']
    assert client.get('/api/data/stats').json()['total_files'] == 1


def test_simultaneous_changes_merge_without_lost_fields(collection):
    root, path, _ = collection
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs = [executor.submit(update_annotation, root, path, '1:可爱 公园', kind, decision, image)
                for kind, decision, image in [('image', 'qualified', '001.jpg'), ('image', 'unqualified', '002.png'), ('account', 'non_marketing', None)]]
        for job in jobs:
            job.result()
    entry = annotations(root, path)['entries']['1:可爱 公园']
    assert entry['images'] == {'001.jpg': 'qualified', '002.png': 'unqualified'}
    assert entry['decision'] == 'qualified'


@pytest.mark.parametrize('account,values,expected,reason', [
    ('marketing', [None, None], 'unqualified', 'marketing'),
    ('marketing', ['qualified', 'qualified'], 'unqualified', 'marketing'),
    ('non_marketing', ['qualified', 'unqualified'], 'qualified', 'retained'),
    ('non_marketing', ['unqualified', 'qualified'], 'qualified', 'retained'),
    ('non_marketing', ['qualified', None], 'qualified', 'retained'),
    ('non_marketing', ['unqualified', 'unqualified'], 'unqualified', 'all_images_rejected'),
    ('non_marketing', ['unqualified', None], None, 'images_pending'),
    ('non_marketing', [None, None], None, 'images_pending'),
    (None, ['qualified', 'unqualified'], None, 'account_pending'),
    (None, ['unqualified', 'unqualified'], 'unqualified', 'all_images_rejected'),
    (None, [None], None, 'account_pending'),
    ('non_marketing', [], 'unqualified', 'no_images'),
])
def test_review_outcome_matrix(account, values, expected, reason):
    imgs = [{'key': str(i)} for i in range(len(values))]
    decisions = {str(i): value for i, value in enumerate(values)}
    assert review_outcome(account, imgs, decisions) == (expected, reason)


def test_legacy_post_labels_and_obsolete_images_cannot_override_outcome(collection):
    root, path, client = collection
    change(client)
    change(client, kind='account', decision='non_marketing')
    target = storage_path(root, path)
    state = json.loads(target.read_text(encoding='utf-8'))
    state['posts']['1:可爱 公园']['decision'] = 'unqualified'
    state['posts']['1:可爱 公园']['images']['obsolete.jpg'] = 'qualified'
    target.write_text(json.dumps(state), encoding='utf-8')
    assert annotations(root, path)['entries']['1:可爱 公园']['decision'] == 'qualified'
    change(client, decision='unqualified')
    change(client, image='002.png', decision='unqualified')
    assert annotations(root, path)['entries']['1:可爱 公园']['decision'] == 'unqualified'
    change(client, image='002.png', decision=None)
    assert annotations(root, path)['entries']['1:可爱 公园']['decision'] is None


def test_failed_atomic_write_preserves_existing_decisions(collection, monkeypatch):
    root, path, client = collection
    change(client)
    original = storage_path(root, path).read_bytes()
    def fail_replace(*args):
        raise OSError('disk write failed')
    monkeypatch.setattr('api.services.manual_review.os.replace', fail_replace)
    assert change(client, decision='unqualified').status_code == 422
    assert storage_path(root, path).read_bytes() == original


def test_corrupt_annotation_file_is_reported_not_overwritten(collection):
    root, path, client = collection
    change(client)
    storage_path(root, path).write_text('{invalid', encoding='utf-8')
    assert client.get('/api/data/review', params={'file': 'weibo/posts.json'}).status_code == 422
    assert change(client).status_code == 422
    assert storage_path(root, path).read_text(encoding='utf-8') == '{invalid'


def test_manual_post_correction_persists_and_reset_restores_automatic_result(collection):
    root, path, client = collection
    original = path.read_bytes()
    change(client)
    result = change(client, kind='post', decision='unqualified', image=None)
    assert result.status_code == 200
    entry = result.json()['entries']['1:可爱 公园']
    assert entry['decision'] == 'unqualified'
    assert entry['decision_reason'] == 'manual_unqualified'
    assert entry['decision_source'] == entry['post_decision_source'] == 'manual'
    assert entry['automatic_decision'] == 'qualified'
    assert entry['account'] == 'non_marketing' and entry['images']['001.jpg'] == 'qualified'
    # Account/image changes and a new reader must preserve the final correction.
    change(client, kind='account', decision='marketing')
    result = change(client, kind='post', decision='qualified', image=None)
    assert result.status_code == 200
    change(client, decision='unqualified')
    entry = client.get('/api/data/review', params={'file': 'weibo/posts.json'}).json()['entries']['1:可爱 公园']
    assert entry['decision'] == 'qualified' and entry['automatic_decision'] == 'unqualified'
    assert entry['decision_reason'] == 'manual_qualified'
    reset = change(client, kind='post', decision=None, image=None)
    assert reset.status_code == 200
    entry = reset.json()['entries']['1:可爱 公园']
    assert entry['decision'] == 'unqualified' and entry['decision_reason'] == 'marketing'
    assert entry['decision_source'] == 'automatic' and entry['post_decision'] is None
    assert 'post_decision' not in json.loads(storage_path(root, path).read_text(encoding='utf-8'))['posts']['1:可爱 公园']
    assert path.read_bytes() == original


def test_post_correction_can_resolve_pending_without_changing_image_labels(collection):
    root, path, client = collection
    result = change(client, kind='post', decision='qualified', image=None)
    assert result.status_code == 200
    assert result.json()['completed'] == 1
    entry = result.json()['entries']['1:可爱 公园']
    assert entry['automatic_decision'] is None and entry['images'] == {}
    assert change(client, kind='post', decision=None, image=None).json()['completed'] == 0


@pytest.mark.parametrize('kind,decision,expected_keys,expected_reads', [
    ('image', 'qualified', {'1:可爱 公园'}, ['001.jpg', '002.png']),
    ('post', 'unqualified', {'1:可爱 公园'}, ['001.jpg', '002.png']),
    ('account', 'marketing', {'1:可爱 公园', '2:'}, ['001.jpg', '002.png', '001.jpg']),
])
def test_partial_save_reads_only_affected_posts_and_matches_full_review(collection, monkeypatch, kind, decision, expected_keys, expected_reads):
    root, path, client = collection
    client.get('/api/data/review', params={'file': 'weibo/posts.json'})
    reads = []
    def prediction(_root, image, _version):
        reads.append(image['key'])
        return {'status': 'not_downloaded'}
    monkeypatch.setattr('image_subject.cached_prediction', prediction)
    response = client.patch('/api/data/review', json={
        'file': 'weibo/posts.json', 'post_key': '1:可爱 公园', 'kind': kind,
        'decision': decision, 'image_key': '001.jpg', 'partial': True,
    })
    assert response.status_code == 200
    patch = response.json()
    assert patch['partial'] is True and set(patch['entries']) == expected_keys
    assert reads == expected_reads  # No other post's prediction files are opened.
    full = client.get('/api/data/review', params={'file': 'weibo/posts.json'}).json()
    assert full['total'] == 5 and len(full['entries']) == 5
    assert patch['entries'] == {key: full['entries'][key] for key in expected_keys}

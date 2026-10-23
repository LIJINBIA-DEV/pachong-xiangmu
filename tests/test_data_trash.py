import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routers import data as router
from api.services import crawler_manager
from api.services import data_trash
from api.services.manual_review import storage_path, update_annotation


@pytest.fixture
def sample(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(router, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(crawler_manager, 'status', 'idle')
    path = tmp_path / 'weibo/posts.json'
    path.parent.mkdir()
    path.write_text(json.dumps([{'note_id': '1', 'image_names': 'cat.jpg', 'creator_hash': 'a'}]), encoding='utf-8')
    image = tmp_path / 'wb/media/1/cat.jpg'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'image fixture')
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    return tmp_path, path, TestClient(app)


def delete(client, file='weibo/posts.json'):
    return client.post('/api/data/trash', json={'file': file})


def test_delete_restore_preserves_bytes_marks_media_and_list_counts(sample):
    root, path, client = sample
    update_annotation(root, path, '1:', 'image', 'qualified', 'cat.jpg')
    marks = storage_path(root, path).read_bytes()
    original = hashlib.sha256(path.read_bytes()).digest()
    mtime = path.stat().st_mtime
    entry = delete(client).json()
    assert not path.exists()
    assert client.get('/api/data/files').json()['files'] == []
    assert client.get('/api/data/stats').json()['total_files'] == 0
    assert client.get('/api/data/trash').json()['files'][0]['id'] == entry['id']
    assert storage_path(root, path).read_bytes() == marks
    assert (root / 'wb/media/1/cat.jpg').read_bytes() == b'image fixture'
    assert client.post(f"/api/data/trash/{entry['id']}/restore").status_code == 200
    assert hashlib.sha256(path.read_bytes()).digest() == original
    assert path.stat().st_mtime == pytest.approx(mtime)
    assert client.get('/api/data/trash').json()['files'] == []
    assert len(client.get('/api/data/files').json()['files']) == 1
    assert client.get('/api/data/review', params={'file': 'weibo/posts.json'}).json()['entries']['1:']['images']['cat.jpg'] == 'qualified'


def test_restore_never_overwrites_newer_file(sample):
    root, path, client = sample
    original = path.read_bytes()
    entry = delete(client).json()
    path.write_bytes(b'newer file')
    assert client.post(f"/api/data/trash/{entry['id']}/restore").status_code == 409
    assert path.read_bytes() == b'newer file'
    assert (root / '.data-trash' / entry['id'] / 'content').read_bytes() == original


@pytest.mark.parametrize('file', ['../outside.json', 'wb/media/1/cat.jpg', '.manual-review/marks.json', '.data-trash/entry.json'])
def test_internal_or_outside_paths_cannot_be_deleted(sample, file):
    _, path, client = sample
    assert delete(client, file).status_code == 403
    assert path.exists()


def test_active_collection_blocks_delete_and_restore(sample, monkeypatch):
    _, path, client = sample
    entry = delete(client).json()
    monkeypatch.setattr(crawler_manager, 'status', 'running')
    assert client.post(f"/api/data/trash/{entry['id']}/restore").status_code == 409
    assert not path.exists()
    monkeypatch.setattr(crawler_manager, 'status', 'idle')
    client.post(f"/api/data/trash/{entry['id']}/restore")
    monkeypatch.setattr(crawler_manager, 'status', 'stopping')
    assert delete(client).status_code == 409
    assert path.exists()


def test_failed_move_leaves_source_intact(sample, monkeypatch):
    _, path, client = sample
    before = path.read_bytes()
    def fail(*args):
        raise PermissionError('locked fixture')
    monkeypatch.setattr(data_trash.os, 'replace', fail)
    assert delete(client).status_code == 409
    assert path.read_bytes() == before
    assert client.get('/api/data/trash').json()['files'] == []


def test_missing_file_invalid_id_and_tampered_destination(sample):
    root, path, client = sample
    assert delete(client, 'weibo/missing.json').status_code == 404
    assert client.post('/api/data/trash/not-an-id/restore').status_code == 403
    entry = delete(client).json()
    metadata = root / '.data-trash' / entry['id'] / 'entry.json'
    entry['path'] = '../outside.json'
    metadata.write_text(json.dumps(entry), encoding='utf-8')
    assert client.post(f"/api/data/trash/{entry['id']}/restore").status_code == 403
    assert not path.exists()


def test_purge_only_removes_selected_trash_payload_preserving_media_and_marks(sample):
    root, path, client = sample
    update_annotation(root, path, '1:', 'image', 'qualified', 'cat.jpg')
    marks = storage_path(root, path).read_bytes()
    other = root / 'weibo/other.json'
    other.write_bytes(b'[]')
    first = delete(client).json()
    second = delete(client, 'weibo/other.json').json()
    assert client.delete(f"/api/data/trash/{first['id']}").status_code == 200
    assert not (root / '.data-trash' / first['id'] / 'content').exists()
    assert [entry['id'] for entry in client.get('/api/data/trash').json()['files']] == [second['id']]
    assert (root / 'wb/media/1/cat.jpg').read_bytes() == b'image fixture'
    assert storage_path(root, path).read_bytes() == marks
    assert client.post(f"/api/data/trash/{first['id']}/restore").status_code == 404
    assert client.post(f"/api/data/trash/{second['id']}/restore").status_code == 200
    assert other.read_bytes() == b'[]'


def test_purge_rejects_active_collection_invalid_ids_and_missing_entries(sample, monkeypatch):
    root, path, client = sample
    entry = delete(client).json()
    monkeypatch.setattr(crawler_manager, 'status', 'running')
    assert client.delete(f"/api/data/trash/{entry['id']}").status_code == 409
    monkeypatch.setattr(crawler_manager, 'status', 'idle')
    assert client.delete('/api/data/trash/not-an-id').status_code == 403
    assert client.delete('/api/data/trash/' + '0' * 32).status_code == 404
    assert len(client.get('/api/data/trash').json()['files']) == 1


def test_purge_failure_and_tampered_paths_preserve_payload(sample, monkeypatch):
    root, path, client = sample
    entry = delete(client).json()
    payload = root / '.data-trash' / entry['id'] / 'content'
    before = payload.read_bytes()
    from pathlib import Path
    original_unlink = Path.unlink
    def fail(target, *args, **kwargs):
        if target == payload:
            raise PermissionError('locked')
        return original_unlink(target, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail)
    assert client.delete(f"/api/data/trash/{entry['id']}").status_code == 409
    assert payload.read_bytes() == before
    entry['path'] = '../outside.json'
    (payload.parent / 'entry.json').write_text(json.dumps(entry), encoding='utf-8')
    assert client.delete(f"/api/data/trash/{entry['id']}").status_code == 403
    assert payload.read_bytes() == before

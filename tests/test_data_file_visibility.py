import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routers import data as router


@pytest.fixture
def collection(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(router, 'DATA_DIR', tmp_path)
    contents = {
        'weibo/weibo_search.xlsx': b'workbook fixture',
        'weibo/semantic_checkpoint_123.jsonl': b'{"choice":"keep"}\n',
        '.account-audit/events/hashed.json': b'{"reason":"news_media_account"}',
        '.future-cache/results/prediction.json': b'{"status":"internal"}',
        '.image-subject/settings.json': b'{"provider":"local"}',
        'wb/media/1/photo.jpg': b'photo fixture',
    }
    for relative, value in contents.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    return tmp_path, TestClient(app)


def test_file_list_and_stats_contain_only_collection_outputs_without_deleting_internal_records(collection):
    root, client = collection
    before = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
    files = client.get('/api/data/files').json()['files']
    assert [file['path'] for file in files] == ['weibo/weibo_search.xlsx']
    assert client.get('/api/data/files', params={'file_type':'json'}).json()['files'] == []
    stats = client.get('/api/data/stats').json()
    assert stats['total_files'] == 1
    assert stats['by_type'] == {'xlsx':1}
    assert stats['total_size'] == len(b'workbook fixture')
    after = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
    assert before == after


@pytest.mark.parametrize('relative', ['.account-audit/events/hashed.json', '.image-subject/settings.json', '.future-cache/results/prediction.json', 'weibo/semantic_checkpoint_123.jsonl'])
def test_internal_records_are_not_available_as_collection_previews_or_downloads(collection, relative):
    root, client = collection
    for route in ('files','download'):
        assert client.get('/api/data/' + route + '/' + relative).status_code == 403
    assert client.post('/api/data/trash', json={'file':relative}).status_code == 403
    assert (root / relative).is_file()


def test_real_json_and_jsonl_collection_exports_remain_accessible_and_photos_still_work(collection):
    root, client = collection
    (root/'weibo/posts.json').write_text('[{"note_id":"1"}]', encoding='utf-8')
    (root/'weibo/posts.jsonl').write_text('{"note_id":"2"}\n', encoding='utf-8')
    paths = {row['path'] for row in client.get('/api/data/files').json()['files']}
    assert paths == {'weibo/weibo_search.xlsx', 'weibo/posts.json', 'weibo/posts.jsonl'}
    assert client.get('/api/data/files/weibo/posts.json').status_code == 200
    assert client.get('/api/data/media/wb/media/1/photo.jpg').status_code == 200

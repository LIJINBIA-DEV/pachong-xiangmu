from hashlib import sha256
from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.routers import data as routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(routes, 'DATA_DIR', tmp_path)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def photo(root, name='001.jpg', size=(3200, 2000)):
    path = root / 'wb/media/post' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', size, '#508a42').save(path, quality=95)
    return path


def test_preview_is_small_and_click_target_remains_exact_original(client, tmp_path):
    path = photo(tmp_path)
    original = path.read_bytes()
    preview = client.get('/data/media/wb/media/post/001.jpg?preview=true')
    assert preview.status_code == 200
    assert preview.headers['content-type'] == 'image/webp'
    with Image.open(BytesIO(preview.content)) as image:
        assert max(image.size) <= 960
        assert image.width / image.height == pytest.approx(1.6, abs=0.01)
    assert len(preview.content) < len(original) / 5
    assert client.get('/data/media/wb/media/post/001.jpg').content == original
    assert sha256(path.read_bytes()).digest() == sha256(original).digest()


def test_preview_cache_revalidates_after_source_changes(client, tmp_path):
    path = photo(tmp_path)
    url = '/data/media/wb/media/post/001.jpg?preview=true'
    first = client.get(url)
    assert first.status_code == 200
    assert client.get(url, headers={'If-None-Match': first.headers['etag']}).status_code == 304
    cached = list((tmp_path / '.media-previews').glob('*.webp'))
    assert len(cached) == 1
    stamp = cached[0].stat().st_mtime_ns
    assert client.get(url).content == first.content
    assert cached[0].stat().st_mtime_ns == stamp
    Image.new('RGB', (1000, 1800), 'blue').save(path, quality=90)
    refreshed = client.get(url, headers={'If-None-Match': first.headers['etag']})
    assert refreshed.status_code == 200 and refreshed.headers['etag'] != first.headers['etag']
    with Image.open(BytesIO(refreshed.content)) as image:
        assert image.height > image.width


def test_exif_orientation_and_transparency_are_kept(client, tmp_path):
    path = photo(tmp_path, size=(1800, 1000))
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (1800, 1000), 'red').save(path, exif=exif)
    response = client.get('/data/media/wb/media/post/001.jpg?preview=true')
    with Image.open(BytesIO(response.content)) as image:
        assert image.height > image.width
    transparent = path.with_suffix('.png')
    Image.new('RGBA', (1200, 800), (10, 20, 30, 0)).save(transparent)
    response = client.get('/data/media/wb/media/post/001.png?preview=true')
    with Image.open(BytesIO(response.content)) as image:
        assert image.mode == 'RGBA' and image.getpixel((0, 0))[3] == 0


def test_corrupt_image_does_not_get_rewritten(client, tmp_path):
    path = photo(tmp_path)
    path.write_bytes(b'partial-image')
    response = client.get('/data/media/wb/media/post/001.jpg?preview=true')
    assert response.status_code == 422
    assert path.read_bytes() == b'partial-image'
    assert client.get('/data/media/wb/media/post/001.jpg').content == b'partial-image'


@pytest.mark.parametrize('url', [
    '/data/media/.private/media/secret.jpg?preview=true',
    '/data/media/%2E%2E/private.jpg?preview=true',
    '/data/media/elsewhere/photo.jpg?preview=true',
    '/data/media/wb/media/post/notes.json?preview=true',
])
def test_preview_preserves_media_access_boundary(client, tmp_path, url):
    photo(tmp_path)
    for relative in ('.private/media/secret.jpg', 'elsewhere/photo.jpg', 'wb/media/post/notes.json'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'private fixture')
    assert client.get(url).status_code in {403, 404}

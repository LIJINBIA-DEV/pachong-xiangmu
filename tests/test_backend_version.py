import asyncio
import json
from unittest.mock import patch

from api.services.backend_version import source_revision
from scripts.check_backend_version import check_backend


def test_revision_changes_with_backend_source_but_ignores_collected_data(tmp_path):
    (tmp_path / 'api').mkdir()
    source = tmp_path / 'api/main.py'
    source.write_text('version = 1', encoding='utf-8')
    first = source_revision(tmp_path)
    (tmp_path / 'api/webui').mkdir()
    (tmp_path / 'api/webui/index.html').write_text('frontend', encoding='utf-8')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/annotations.json').write_text('human labels', encoding='utf-8')
    assert source_revision(tmp_path) == first
    source.write_text('version = 2', encoding='utf-8')
    assert source_revision(tmp_path) != first


def test_checker_does_not_reuse_old_or_wrong_project_backend(tmp_path):
    from io import BytesIO
    revision = source_revision(tmp_path)
    for health, expected in [
        ({'status': 'ok'}, 2),
        ({'status': 'ok', 'source_revision': 'old'}, 2),
        ({'status': 'ok', 'source_revision': revision, 'project_root': str(tmp_path)}, 0),
        ({'status': 'ok', 'source_revision': revision, 'project_root': str(tmp_path / 'other')}, 1),
        ({'status': 'error'}, 1),
    ]:
        with patch('scripts.check_backend_version.urlopen', side_effect=lambda *args, **kwargs: BytesIO(json.dumps(health).encode())):
            assert check_backend('http://127.0.0.1:18080', tmp_path) == expected
    with patch('scripts.check_backend_version.urlopen', side_effect=OSError('offline')):
        assert check_backend('http://127.0.0.1:18080', tmp_path) == 1


def test_health_reports_loaded_revision_without_rehashing_current_files():
    from api.main import health_check, LOADED_SOURCE_REVISION
    with patch('api.main.source_revision', side_effect=AssertionError('Must report the loaded source snapshot')):
        health = asyncio.run(health_check())
    assert health['status'] == 'ok' and health['source_revision'] == LOADED_SOURCE_REVISION
    assert health['project_root']

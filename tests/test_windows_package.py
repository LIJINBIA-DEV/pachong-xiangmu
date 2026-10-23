from pathlib import Path
import zipfile

import pytest

from scripts.package_windows import ROOT, build_package, public_content


def test_handoff_archive_keeps_code_and_excludes_runtime(tmp_path):
    out = tmp_path / 'handoff.zip'
    build_package(ROOT, out)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert 'MediaCrawler/model/m_weibo.py' in names
        assert 'MediaCrawler/cache/cache_factory.py' in names
        assert 'MediaCrawler/一键启动.cmd' in names
        assert 'MediaCrawler/scripts/bootstrap_windows.ps1' in names
        assert 'MediaCrawler/webui/src/main.tsx' in names
        for name in names:
            assert Path(name).parts[1] not in {'data', 'browser_data', 'models', '.local', '.runtime', '.venv', '.git', 'artifacts'}
            assert 'node_modules' not in Path(name).parts
            assert not Path(name).name.startswith('.env')
        assert b'COOKIES = ""' in z.read('MediaCrawler/config/base_config.py')
    with pytest.raises(FileExistsError):
        build_package(ROOT, out)


def test_embedded_key_is_not_exported(tmp_path):
    file = tmp_path / 'sample.py'
    file.write_text('key = "sk-' + 'x' * 25 + '"')
    with pytest.raises(ValueError, match='Possible credential'):
        public_content(file, tmp_path)

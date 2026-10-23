"""Package current source for Spark; leave all desktop data and secrets behind."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tarfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('api', 'base', 'cache', 'cmd_arg', 'config', 'constant', 'database',
               'docker', 'libs', 'media_downloader', 'media_platform', 'model', 'proxy',
               'resources', 'scripts', 'store', 'tools', 'webui')
SOURCE_FILES = ('.dockerignore', '.gitignore', '.env.spark.example', 'compose.spark.yaml', 'compose.spark-jev-relay.yaml',
                '.env.server.example', 'compose.server.yaml',
                'pyproject.toml', 'uv.lock', 'README.md', 'LICENSE')
SKIP_DIRS = {'__pycache__', 'node_modules', '.pytest_cache', 'artifacts', 'runtime', 'tests', 'test'}
SKIP_SUFFIXES = {'.pyc', '.pyo', '.xlsx', '.jsonl', '.gguf', '.key', '.pem', '.db', '.log'}


def source_files():
    files = set(ROOT.glob('*.py'))
    files.update(ROOT / name for name in SOURCE_FILES)
    for directory in SOURCE_DIRS:
        for path in (ROOT / directory).rglob('*'):
            relative = path.relative_to(ROOT)
            if not path.is_file() or any(part in SKIP_DIRS for part in relative.parts):
                continue
            if relative.parts[:2] == ('api', 'webui'):
                continue
            if path.suffix.lower() in SKIP_SUFFIXES or path.name == 'settings.json' or path.name.startswith('.env'):
                continue
            files.add(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = source_files()
    records = []
    for path in files:
        content = path.read_bytes()
        if re.search(rb'\bsk-[A-Za-z0-9]{32,}\b', content):
            raise ValueError('Potential API credential in source; packaging stopped: ' + path.relative_to(ROOT).as_posix())
        records.append({'path': path.relative_to(ROOT).as_posix(), 'size': len(content),
                        'sha256': hashlib.sha256(content).hexdigest()})
    with tarfile.open(args.output / 'source.tar.gz', 'w:gz') as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(ROOT).as_posix(), recursive=False)
    metadata = {'created_at': datetime.now(timezone.utc).isoformat(), 'files': records,
                'archive_sha256': hashlib.sha256((args.output / 'source.tar.gz').read_bytes()).hexdigest()}
    (args.output / 'source-manifest.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps({'files': len(files), 'archive_bytes': (args.output / 'source.tar.gz').stat().st_size,
                      'archive_sha256': metadata['archive_sha256']}))


if __name__ == '__main__':
    main()

"""Identify the source version loaded by a running backend."""
import hashlib
from pathlib import Path


def source_revision(root):
    root = Path(root)
    files = set(root.glob('*.py'))
    for folder in ('api', 'config', 'media_platform', 'store'):
        files.update((root / folder).rglob('*.py'))
    files.update((root / 'resources/weibo_account_blocklist').rglob('*.json'))
    files.update((root / 'resources/weibo_account_blocklist').rglob('*.txt'))
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda file: file.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()

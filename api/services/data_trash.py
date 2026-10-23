"""Collection file trash and purge; preserve shared media and review marks."""
import json
import os
from pathlib import Path
import re
from threading import RLock
import time
import uuid

from api.services.data_browser import DATA_TYPES
from api.services.data_file_visibility import internal_record

_lock = RLock()
HIDDEN = {'media', '__pycache__', '.manual-review', '.data-trash'}


def collection_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative.replace('\\', '/')).resolve()
    parts = path.relative_to(root).parts
    if not parts or internal_record(Path(*parts)) or any(part in HIDDEN for part in parts) or path.suffix.lower() not in DATA_TYPES:
        raise ValueError('Only collection files can be deleted')
    return path


def trash_root(root: Path) -> Path:
    target = root / '.data-trash'
    # Reject redirected/symlinked storage, even when still inside the data root.
    if target.resolve() != root.resolve() / '.data-trash':
        raise ValueError('Invalid trash directory')
    return target


def move_to_trash(root: Path, relative: str) -> dict:
    with _lock:
        source = collection_path(root, relative)
        if not source.is_file():
            raise FileNotFoundError(relative)
        entry = {'id': uuid.uuid4().hex, 'path': source.relative_to(root.resolve()).as_posix(),
                 'name': source.name, 'size': source.stat().st_size, 'modified_at': source.stat().st_mtime, 'deleted_at': time.time()}
        folder = trash_root(root) / entry['id']
        folder.mkdir(parents=True)
        # Write metadata before moving so the moved file is always recoverable.
        (folder / 'entry.json').write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
        os.replace(source, folder / 'content')
        return entry


def read_entry(root: Path, entry_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', entry_id):
        raise ValueError('Invalid trash ID')
    folder = trash_root(root) / entry_id
    if folder.resolve() != trash_root(root).resolve() / entry_id:
        raise ValueError('Invalid trash entry')
    payload = folder / 'content'
    if not payload.is_file():
        raise FileNotFoundError(entry_id)
    if payload.resolve() != folder.resolve() / 'content':
        raise ValueError('Invalid trash content')
    metadata = folder / 'entry.json'
    if metadata.resolve() != folder.resolve() / 'entry.json':
        raise ValueError('Invalid trash metadata')
    entry = json.loads(metadata.read_text(encoding='utf-8'))
    if not isinstance(entry, dict) or entry.get('id') != entry_id or not isinstance(entry.get('path'), str) or not isinstance(entry.get('name'), str):
        raise ValueError('Invalid trash metadata')
    if any(not isinstance(entry.get(key), (int, float)) for key in ('size', 'modified_at', 'deleted_at')):
        raise ValueError('Invalid trash metadata')
    collection_path(root, entry['path'])
    return entry, payload


def list_trash(root: Path) -> list:
    with _lock:
        parent = trash_root(root)
        entries = []
        if parent.exists():
            for folder in parent.iterdir():
                try:
                    entry, _ = read_entry(root, folder.name)
                    entries.append(entry)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return sorted(entries, key=lambda entry: entry['deleted_at'], reverse=True)


def restore_file(root: Path, entry_id: str) -> dict:
    with _lock:
        entry, payload = read_entry(root, entry_id)
        destination = collection_path(root, entry['path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents replacing a newer file at the original path.
        with destination.open('xb') as target:
            try:
                with payload.open('rb') as source:
                    import shutil
                    shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            except BaseException:
                target.close()
                destination.unlink()
                raise
        try:
            os.utime(destination, (entry['modified_at'], entry['modified_at']))
            payload.unlink()
        except OSError:
            # Both copies are safe, but do not report a completed restoration.
            destination.unlink()
            raise
        return entry


def purge_file(root: Path, entry_id: str) -> dict:
    """Delete only the validated payload of one trash entry, never recurse."""
    with _lock:
        entry, payload = read_entry(root, entry_id)
        payload.unlink()
        # Once the payload is removed, the file is permanently deleted. Cleanup
        # failures must not misreport it as preserved or target unrelated files.
        try:
            (payload.parent / 'entry.json').unlink()
            payload.parent.rmdir()
        except OSError:
            pass
        return entry

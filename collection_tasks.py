"""Durable collection lineage and per-run search cursors, without credentials."""
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
import uuid
from datetime import datetime, timezone

_lock = RLock()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_path(root, relative):
    path = (Path(root).resolve() / relative).resolve()
    path.relative_to(Path(root).resolve())
    if any(part.startswith('.') for part in Path(relative).parts):
        raise ValueError('Invalid collection file')
    return path


def task_path(root, task_id):
    if not re.fullmatch(r'[a-f0-9]{32}', task_id):
        raise ValueError('Invalid collection task')
    return Path(root).resolve() / '.collection-tasks' / task_id / 'task.json'


def create_task(root, config, targets, anchor=None):
    task_id = uuid.uuid4().hex
    # Only operational, non-secret fields are persisted. Never persist login cookies
    # or API keys, including masked SecretStr representations.
    config = {key: value for key, value in config.items() if key not in {'cookies', 'semantic_api_key'}}
    task = {'version': 1, 'id': task_id, 'config': config, 'targets': targets,
            'anchor': anchor, 'runs': []}
    atomic_json(task_path(root, task_id), task)
    return task


def read_task(root, task_id):
    task = json.loads(task_path(root, task_id).read_text(encoding='utf-8'))
    if task.get('version') != 1 or task.get('id') != task_id:
        raise ValueError('Invalid task metadata')
    return task


def runs(root, task):
    folder = task_path(root, task['id']).parent
    for run_id in task['runs']:
        if not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise ValueError('Invalid collection run')
        yield folder / (run_id + '.json')


def task_files(root, task):
    result = []
    if task.get('anchor'):
        result.append(task['anchor'])
    for path in runs(root, task):
        result.extend(json.loads(path.read_text(encoding='utf-8')).get('files', []))
    return list(dict.fromkeys(result))


def find_task(root, path):
    relative = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    parent = Path(root).resolve() / '.collection-tasks'
    if not parent.exists():
        return None
    for metadata in parent.glob('*/task.json'):
        task = read_task(root, metadata.parent.name)
        main_relative = relative.removesuffix('_semantic.xlsx') + '.xlsx' if relative.endswith('_semantic.xlsx') else relative
        if relative in task_files(root, task) or main_relative in task_files(root, task):
            return task
    return None


def prepare_run(root, task, quotas, seed_ids=(), blocked_accounts=(), supplement=False):
    with _lock:
        task = read_task(root, task['id'])
        seen, cursors = {}, {}
        for path in runs(root, task):
            run = json.loads(path.read_text(encoding='utf-8'))
            for keyword, ids in run.get('seen', {}).items():
                seen.setdefault(keyword, set()).update(ids)
            cursors.update(run.get('cursors', {}))
        for keyword in task['targets']:
            seen.setdefault(keyword, set()).update(seed_ids)
        run_id = uuid.uuid4().hex
        path = task_path(root, task['id']).parent / (run_id + '.json')
        atomic_json(path, {'id': run_id, 'task_id': task['id'], 'root': str(Path(root).resolve()),
                           'quotas': quotas, 'seen': {k: sorted(v) for k, v in seen.items()},
                           'cursors': cursors, 'blocked_accounts': list(blocked_accounts),
                           'files': [], 'status': 'starting', 'results': {}, 'started_at': timestamp(),
                           'max_pages': 100 if supplement else 0})
        task['runs'].append(run_id)
        atomic_json(task_path(root, task['id']), task)
        return path


def finish_run(path, status):
    path = Path(path)
    run = json.loads(path.read_text(encoding='utf-8'))
    run['status'] = status
    if status not in {'starting', 'running'}:
        run['finished_at'] = timestamp()
    atomic_json(path, run)


def register_output(path, *, anchor=True):
    run_file = os.environ.get('MEDIACRAWLER_COLLECTION_RUN')
    if not run_file:
        return
    run_file = Path(run_file)
    run = json.loads(run_file.read_text(encoding='utf-8'))
    root = Path(run['root'])
    relative = Path(path).resolve().relative_to(root.resolve()).as_posix()
    with _lock:
        run = json.loads(run_file.read_text(encoding='utf-8'))
        if relative not in run['files']:
            run['files'].append(relative)
        atomic_json(run_file, run)
        task = read_task(root, run['task_id'])
        if anchor and not task['anchor']:
            task['anchor'] = relative
            atomic_json(task_path(root, task['id']), task)


class SearchProgress:
    def __init__(self):
        name = os.environ.get('MEDIACRAWLER_COLLECTION_RUN')
        self.path = Path(name) if name else None
        self.run = json.loads(self.path.read_text(encoding='utf-8')) if self.path else {}

    def target(self, keyword, fallback):
        return self.run.get('quotas', {}).get(keyword, fallback)

    def page(self, keyword, fallback):
        return self.run.get('cursors', {}).get(keyword, {}).get('page', fallback)

    def seen(self, keyword):
        return set(self.run.get('seen', {}).get(keyword, []))

    def blocked(self, creator_hash):
        return bool(creator_hash) and creator_hash in self.run.get('blocked_accounts', [])

    def record(self, keyword, page, note_ids=(), result=None):
        if not self.path:
            return
        # Output registration may have changed files since construction. Read the
        # latest run before writing so cursors never overwrite attached files.
        self.run = json.loads(self.path.read_text(encoding='utf-8'))
        self.run['seen'][keyword] = sorted(set(self.run['seen'].get(keyword, [])) | set(note_ids))
        self.run['cursors'][keyword] = {'page': page}
        if result is not None:
            self.run['results'][keyword] = result
            self.run.setdefault('result_times', {})[keyword] = timestamp()
        atomic_json(self.path, self.run)


def review_progress_path(run_file):
    return Path(run_file).with_suffix('.review-progress.json')


def review_progress(stage, content_id=None):
    """Only instrument explicitly opted-in review runs, never unrelated workbench jobs."""
    run_file = os.environ.get('MEDIACRAWLER_COLLECTION_RUN')
    if not run_file:
        return
    path = review_progress_path(run_file)
    if not path.exists():
        return
    try:
        with _lock:
            current = json.loads(path.read_text())
            if stage == 'SEARCHING' and current['stage'] == 'CRAWLING':
                return
            ids = set(current.get('ids', []))
            if content_id and content_id != 'N/A':
                ids.add(str(content_id))
            current.update(stage=stage, ids=sorted(ids), current=min(len(ids), current['total']))
            atomic_json(path, current)
    except (OSError, ValueError, KeyError):
        # Optional progress must never break collection.
        return

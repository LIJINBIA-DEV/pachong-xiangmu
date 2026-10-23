"""Durable, deduplicated account decisions, without cookies or raw responses."""
import hashlib
import json
import os
from pathlib import Path

from collection_tasks import atomic_json, timestamp
from tools.user_hash import anonymize_user_id


def record_event(record, identity, *, root=None, source_file='', stage='collection'):
    run_path = os.environ.get('MEDIACRAWLER_COLLECTION_RUN') if stage == 'collection' else None
    run = json.loads(Path(run_path).read_text(encoding='utf-8')) if run_path else {}
    if root is None:
        if run_path:
            root = Path(run_path).parents[2]
        else:
            import config
            root = Path(config.SAVE_DATA_PATH or 'data')
    root = Path(root)
    user = record.get('user') or record
    event = {'stage': stage, 'run_id': run.get('id'), 'source_file': source_file,
             'note_id': str(record.get('note_id') or ''), 'keyword': str(record.get('source_keyword') or ''),
             'creator_hash': str(record.get('creator_hash') or anonymize_user_id(user.get('idstr') or user.get('id') or user.get('user_id'))),
             'nickname': str(user.get('screen_name') or user.get('nickname') or '')[:120],
             **identity, 'recorded_at': timestamp()}
    key = hashlib.sha256(json.dumps({k: v for k, v in event.items() if k != 'recorded_at'}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    target = root / '.account-audit/events' / (key + '.json')
    if not target.exists():
        atomic_json(target, event)


def events(root, files=(), run_ids=()):
    result = []
    fields = {'stage', 'run_id', 'source_file', 'note_id', 'keyword', 'creator_hash', 'nickname', 'status', 'reason', 'evidence', 'recorded_at'}
    for path in (Path(root) / '.account-audit/events').glob('*.json'):
        row = json.loads(path.read_text(encoding='utf-8'))
        if row.get('source_file') in files or row.get('run_id') in run_ids:
            result.append({k: row.get(k) for k in fields})
    return sorted(result, key=lambda row: row.get('recorded_at') or '', reverse=True)

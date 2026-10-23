"""Recheck saved Weibo authors; never rewrite collected workbooks or human labels."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import shutil
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from account_audit import record_event
from api.services.data_browser import load_dataset
from api.services.manual_review import annotations
from collection_tasks import atomic_json
from weibo_account_filter import account_record_identity, IDENTITY_RULE


def audit(root, report_dir):
    root, report_dir = Path(root), Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    # Back up annotations before migrating automatic defaults. Human marks are
    # retained in their original records, even when a hard policy gate overrides them.
    backup = report_dir / 'annotations-backup'
    backup.mkdir(exist_ok=True)
    for path in (root / '.manual-review').glob('*.json'):
        shutil.copy2(path, backup / path.name)
    results = []
    for path in sorted((root / 'weibo').glob('*')):
        if not path.is_file() or path.suffix.lower() not in {'.xlsx', '.json', '.csv'} or any(word in path.name for word in ('comment', 'creator', 'checkpoint')):
            continue
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        notes, _ = load_dataset(path)
        counts = Counter()
        exclusions = []
        for note in notes:
            identity = account_record_identity(note)
            counts[identity['status']] += 1
            if identity['status'] in {'excluded', 'review'}:
                record_event(note, identity, root=root, source_file=path.relative_to(root).as_posix(), stage='historical')
            if identity['status'] == 'excluded':
                exclusions.append({'note_id': str(note.get('note_id')), 'nickname': note.get('nickname'), **identity})
        review = annotations(root, path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original, 'Collected source changed'
        results.append({'file': path.relative_to(root).as_posix(), 'posts': len(notes), 'identities': dict(counts),
                        'effective_outcomes': dict(Counter(str(entry['decision']) for entry in review['entries'].values())),
                        'exclusions': exclusions, 'source_sha256': original})
    report = {'rule': IDENTITY_RULE, 'files': results, 'sources_unchanged': True}
    atomic_json(report_dir / 'report.json', report)
    return report


if __name__ == '__main__':
    folder = ROOT / 'artifacts' / ('account-audit-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    print(json.dumps({'report_dir': str(folder), **audit(ROOT / 'data', folder)}, ensure_ascii=True))

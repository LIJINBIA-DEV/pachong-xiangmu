"""Present saved exports as collection tasks without rewriting existing data."""
from collections import Counter
import json
from zipfile import BadZipFile

from collection_tasks import read_task, runs, task_files
from api.services.data_browser import load_dataset, post_id, text, reviewed_notes, collection_status


def collection_catalog(root, files):
    available = {file['path']: file for file in files}
    groups, assigned = [], set()
    for metadata in sorted((root / '.collection-tasks').glob('*/task.json')):
        try:
            task = read_task(root, metadata.parent.name)
            paths = task_files(root, task)
            members = [available[path] for path in paths if path in available]
            if not members:
                continue
            history = [json.loads(path.read_text(encoding='utf-8')) for path in runs(root, task)]
            groups.append((task, members, history, any(path not in available for path in paths)))
            assigned.update(file['path'] for file in members)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    # Legacy exports have no task metadata. Pair only identical stems in the
    # same folder; a timestamp or keyword alone is not a safe association.
    legacy = {}
    for file in files:
        if file['path'] in assigned or any(word in file['name'].lower() for word in ('comment', 'creator', 'guard_replay', 'semantic_checkpoint')):
            continue
        key = file['path'].removesuffix('_semantic.xlsx') + '.xlsx' if file['path'].endswith('_semantic.xlsx') else file['path']
        legacy.setdefault(key, []).append(file)
    groups.extend((None, members, [], False) for members in legacy.values())

    result = []
    for task, members, history, missing in groups:
        primary = next((file for file in members if file['path'] == (task or {}).get('anchor')), None)
        primary = primary or next((file for file in members if file.get('file_kind') != 'semantic'), members[0])
        notes, comments, readable = {}, {}, not missing
        for file in members:
            try:
                rows, by_note = load_dataset(root / file['path'])
                for note in rows:
                    notes.setdefault((post_id(note), text(note.get('source_keyword'))), note)
                for nid, items in by_note.items():
                    comments.setdefault(nid, []).extend(items)
            except (OSError, ValueError, KeyError, TypeError, BadZipFile):
                readable = False
        keywords = list((task or {}).get('targets', {})) or list(dict.fromkeys(text(note.get('source_keyword')) for note in notes.values() if note.get('source_keyword')))
        try:
            effective = reviewed_notes(root, root / primary['path'], list(notes.values()), comments) if readable else []
            counts = dict(Counter(text(collection_status(note)) for note in effective)) if readable else None
        except (OSError, ValueError, KeyError, TypeError):
            counts = None
        result.append({
            'id': task['id'] if task else primary['path'],
            'title': ' / '.join(keywords), 'platform': primary['path'].split('/')[0],
            'primary_file': primary['path'], 'files': members,
            'modified_at': max(file['modified_at'] for file in members),
            'started_at': history[0].get('started_at') if history else None,
            'status': 'incomplete' if missing else history[-1].get('status', 'saved') if history else 'saved',
            'counts': counts, 'rounds': len(history) or 1,
        })
    return sorted(result, key=lambda task: task['modified_at'], reverse=True)

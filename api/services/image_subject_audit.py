"""Back up and verify a full image rerun without replacing human decisions."""
from collections import Counter
import hashlib
import json
import shutil

from collection_tasks import atomic_json
from image_subject import cache_path, cached_prediction, fingerprint, image_catalog
from api.services.manual_review import annotations, read_state, state_lock


def human_marks(state):
    images = {}
    posts = {}
    for key, post in state.get('posts', {}).items():
        for name, value in post.get('images', {}).items():
            if post.get('image_sources', {}).get(name) not in {'model', 'download'}:
                images[key + '\0' + name] = value
        if post.get('post_decision_source') == 'manual':
            posts[key] = post.get('post_decision')
    accounts = {key: value.get('decision') for key, value in state.get('accounts', {}).items()
                if value.get('source', 'manual') == 'manual'}
    return {'images': images, 'posts': posts, 'accounts': accounts}


def prepare_rerun(root, file, audit, options=None):
    audit.mkdir(parents=True, exist_ok=False)
    with state_lock(root, file):
        before = read_state(root, file)
    atomic_json(audit / 'review-before.json', before)
    images, missing = image_catalog(root, [file])
    backup = audit / 'cache-before'
    backup.mkdir()
    for name in images:
        cache = cache_path(root, name)
        if cache.exists():
            shutil.copy2(cache, backup / cache.name)
    atomic_json(audit / 'manifest.json', {
        'file': file.relative_to(root).as_posix(), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
        'fingerprint': fingerprint(provider=(options or {}).get('provider', 'local')), 'images': list(images), 'not_downloaded': missing,
        'manual_before': human_marks(before),
    })


def finish_rerun(root, file, audit, result):
    manifest = json.loads((audit / 'manifest.json').read_text(encoding='utf-8'))
    review = annotations(root, file)
    with state_lock(root, file):
        after = read_state(root, file)
    before = manifest['manual_before']
    current = human_marks(after)
    # Human edits made while inference ran are valid; model defaults must never
    # erase a human entry, including an explicit reset (None).
    preserved = all(key in current[kind] for kind in before for key in before[kind])
    changes = {kind: {key: {'before': value, 'after': current[kind].get(key)}
                      for key, value in before[kind].items() if current[kind].get(key) != value}
               for kind in before}
    unchanged = all(not value for value in changes.values())
    source_unchanged = manifest['sha256'] == hashlib.sha256(file.read_bytes()).hexdigest()
    images, _ = image_catalog(root, [file])
    rows = []
    for name in manifest['images']:
        p = cached_prediction(root, images[name])
        record = json.loads(cache_path(root, name).read_text(encoding='utf-8'))
        if record.get('fingerprint') != manifest['fingerprint']:
            raise AssertionError('An image was not processed by this rerun')
        rows.append({'path': name, 'prediction': p})
    automatic = 0
    for entry in review['entries'].values():
        for image in entry['review_images']:
            if image.get('decision_source') == 'model':
                if entry['images'].get(image['key']) != image['subject'].get('suggestion'):
                    raise AssertionError('Automatic image decision differs from model suggestion')
                automatic += 1
    report = {**result, 'file': manifest['file'], 'types': dict(Counter(row['prediction'].get('image_type') for row in rows)),
              'suggestions': dict(Counter(row['prediction'].get('suggestion') or 'manual_review' for row in rows)),
              'manual_marks_preserved': preserved, 'manual_marks_unchanged': unchanged,
              'manual_changes_during_run': changes, 'manual_counts': {key: len(value) for key, value in current.items()},
              'source_file_unchanged': source_unchanged, 'automatic_marks_verified': automatic, 'rows': rows}
    atomic_json(audit / 'report.json', report)
    if not preserved or not source_unchanged:
        raise AssertionError('Rerun integrity check failed; original backup retained')

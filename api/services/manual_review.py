"""Persist post review decisions independently of optional media."""
import ast
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from urllib.parse import urlsplit

from api.services.data_browser import load_review_dataset, pictures, text, image_urls
from semantic_quality import saved_jev_rejection

_lock = RLock()


@contextmanager
def state_lock(root, path):
    # The crawler writes model defaults while the API may save a human override.
    # Both processes must merge under the same OS lock, not just a thread lock.
    with _lock:
        target = storage_path(root, path).with_suffix('.lock')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a+b') as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def write_state(root, path, state):
    target = storage_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def image_names(note):
    names = note.get('image_names') or []
    if isinstance(names, str):
        if names.lstrip().startswith('['):
            try:
                names = ast.literal_eval(names)
            except (ValueError, SyntaxError):
                names = []
        else:
            names = names.split(',')
    return list(dict.fromkeys(Path(str(name).strip()).name for name in names if str(name).strip())) if isinstance(names, list) else []


def review_images(root, path, note):
    # Names identify the original images even when the download is absent/partial.
    names = image_names(note)
    urls = image_urls(note)
    saved = pictures(root, path, note)
    local = {item['name']: item for item in saved if item['local']}
    if not names:
        names = list(dict.fromkeys(Path(urlsplit(url).path).name or f'image-{i}' for i, url in enumerate(urls, 1)))
    result = []
    for index, name in enumerate(names):
        item = local.pop(name, None)
        result.append({**(item or {'name': name, 'url': urls[index] if index < len(urls) else '', 'local': False}), 'key': name, 'remote_url': urls[index] if index < len(urls) else ''})
    result.extend({**item, 'key': name} for name, item in local.items())
    return result


def account_key(note):
    # Masked nicknames cannot identify an account. Never merge accounts by them.
    creator = text(note.get('creator_hash'))
    if creator:
        return 'creator:' + creator, 'batch_account'
    return 'post:' + text(note.get('note_id') or note.get('aweme_id')), 'post_only'


def storage_path(root, path):
    from collection_tasks import find_task, safe_path
    task = find_task(root, path)
    if task and task.get('anchor'):
        path = safe_path(root, task['anchor'])
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return root / '.manual-review' / (hashlib.sha256(relative.encode()).hexdigest() + '.json')


def read_state(root, path):
    target = storage_path(root, path)
    if not target.exists():
        return {'version': 1, 'posts': {}, 'accounts': {}}
    state = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('posts'), dict) or not isinstance(state.get('accounts'), dict):
        raise ValueError('Invalid manual review file')
    return state


def note_key(note):
    return text(note.get('note_id') or note.get('aweme_id')) + ':' + text(note.get('source_keyword'))


def review_outcome(account, imgs, decisions, *, requires_images=False, screening_passed=False):
    """Media presence and historical image marks never determine a post outcome."""
    if account == 'marketing':
        return 'unqualified', 'marketing'
    if screening_passed:
        return 'qualified', 'semantic_passed'
    return None, 'text_review_pending'


def account_identities(root, path, notes):
    from weibo_account_filter import account_record_identity
    identities = {}
    priority = {'personal': 0, 'review': 1, 'excluded': 2}
    for note in notes:
        source = Path(note.get('_collection_file') or path.relative_to(root))
        if not ({'weibo', 'wb'} & set(source.parts)):
            continue
        aid, _ = account_key(note)
        identity = account_record_identity(note)
        if aid not in identities or priority[identity['status']] > priority[identities[aid]['status']]:
            identities[aid] = identity
    return identities


def apply_account_defaults(root, path, notes, state, identities=None):
    """Default non-excluded Weibo accounts to accepted; retain identity evidence and human marks."""
    identities = account_identities(root, path, notes) if identities is None else identities
    changed = False
    for aid, identity in identities.items():
        reason = identity['reason']
        current = state['accounts'].get(aid)
        # Hard exclusions are applied to the effective outcome below; keep saved
        # human annotations intact, including legacy decisions and explicit resets.
        if current is not None and current.get('source') not in {'blocklist', 'default', 'identity', 'identity_review'}:
            continue
        excluded = identity['status'] == 'excluded'
        desired = {'decision': 'marketing' if excluded else 'non_marketing',
                   'source': 'blocklist' if excluded and reason.startswith('account_blocklist_') else 'identity' if excluded else 'default',
                   'reason': reason if excluded or identity['status'] == 'personal' else 'account_default_non_excluded'}
        if current is None or any(current.get(key) != value for key, value in desired.items()):
            state['accounts'][aid] = {**desired, 'updated_at': datetime.now(timezone.utc).isoformat()}
            changed = True
    return changed


def annotations(root, path, keys=None, *, persist=True, dataset=None):
    notes, comments = dataset if dataset is not None else load_review_dataset(root, path)
    # Aggregate before narrowing a PATCH response so the same author cannot
    # lose a hard exclusion because only one of their posts was requested.
    identities = account_identities(root, path, notes)
    if keys is not None:
        notes = [note for note in notes if note_key(note) in keys]
    prepared = {}
    for note in notes:
        prepared[note_key(note)] = []
        for image in review_images(root, path, note):
            problem = image_download_problem(root, image)
            prepared[note_key(note)].append({**image, 'download_problem': problem})
    with state_lock(root, path) if persist else nullcontext():
        state = read_state(root, path)
        changed = apply_account_defaults(root, path, notes, state, identities)
        if changed and persist:
            state['source_file'] = path.relative_to(root).as_posix()
            write_state(root, path, state)
    entries = {}
    completed = 0
    for note in notes:
        key = note_key(note)
        aid, scope = account_key(note)
        record = state['posts'].get(key, {})
        imgs = [{**image, 'decision_source': record.get('image_sources', {}).get(image['key'], 'manual' if image['key'] in record.get('images', {}) else None)} for image in prepared[key]]
        account_record = state['accounts'].get(aid, {})
        account = account_record.get('decision')
        identity = identities.get(aid, {})
        account_rejection = identity.get('reason') if identity.get('status') == 'excluded' else None
        if account_rejection:
            account = 'marketing'
        decisions = {name: value for name, value in record.get('images', {}).items()
                     if record.get('image_sources', {}).get(name) != 'download'}
        for image in imgs:
            if image['decision_source'] == 'download':
                image['decision_source'] = None
        # Candidate-policy records are unresolved; saved human overrides still win.
        screening_passed = (note.get('semantic_result') == 'matched'
                            and note.get('selection_origin') != 'review_policy'
                            and (note.get('model_original_choice') or note.get('jev_original_choice')) != 'review')
        automatic_decision, automatic_reason = review_outcome(account, imgs, decisions, screening_passed=screening_passed)
        from semantic_quality import saved_collection_rejection
        semantic_rejection = saved_jev_rejection(note) or saved_collection_rejection(note, comments.get(str(note.get('note_id') or note.get('aweme_id')), []))
        if semantic_rejection:
            automatic_decision, automatic_reason = 'unqualified', semantic_rejection
        elif account_rejection:
            automatic_decision, automatic_reason = 'unqualified', account_rejection
        # Only the new, explicit override is authoritative; old removed post
        # labels must not silently become active when this feature is restored.
        post_decision = record.get('post_decision') if record.get('post_decision_source') == 'manual' else None
        if post_decision not in {'qualified', 'unqualified'}:
            post_decision = None
        gated = semantic_rejection or account_rejection
        decision = automatic_decision if gated else post_decision or automatic_decision
        reason = automatic_reason if gated else 'manual_' + post_decision if post_decision else automatic_reason
        entries[key] = {
            'decision': decision, 'decision_reason': reason, 'images': decisions,
            'requires_images': False,
            'screening_passed': screening_passed,
            'post_decision': post_decision, 'post_decision_source': 'manual' if post_decision else None,
            'decision_source': 'manual' if post_decision and not gated else 'automatic',
            'semantic_rejection_reason': semantic_rejection,
            'account_rejection_reason': account_rejection,
            'account_identity_status': identity.get('status'), 'account_identity_evidence': identity.get('evidence'),
            'automatic_decision': automatic_decision, 'automatic_decision_reason': automatic_reason,
            'updated_at': record.get('updated_at'), 'account_key': aid, 'account_scope': scope,
            'source_file': note.get('_collection_file'),
            'account': account, 'account_source': ('blocklist' if account_rejection.startswith('account_blocklist_') else 'identity') if account_rejection else account_record.get('source', 'manual' if aid in state['accounts'] else None),
            'account_reason': account_rejection or account_record.get('reason'), 'review_images': imgs,
        }
        if decision in {'qualified', 'unqualified'}:
            completed += 1
    return {'entries': entries, 'total': len(notes), 'completed': completed}



def image_download_problem(root, image):
    """Only check file availability; never inspect or classify its contents."""
    from api.services.data_browser import local_image_path
    path = local_image_path(root, image)
    if path is None:
        return 'not_downloaded'
    try:
        stat = path.stat()
        return None if stat.st_size else 'download_failed'
    except OSError:
        return 'not_downloaded'


def update_annotation(root, path, key, kind, decision, image_key=None, partial=False):
    if kind not in {'image', 'account', 'post'}:
        raise ValueError('Unknown review kind')
    allowed = {'marketing', 'non_marketing'} if kind == 'account' else {'qualified', 'unqualified'}
    if decision is not None and decision not in allowed:
        raise ValueError('Decision does not match review kind')
    notes, _ = load_review_dataset(root, path)
    note = next((note for note in notes if note_key(note) == key), None)
    if note is None:
        raise LookupError('Post not found in this file')
    if kind == 'image' and image_key not in {image['key'] for image in review_images(root, path, note)}:
        raise LookupError('Image not found in this post')
    with state_lock(root, path):
        state = read_state(root, path)
        record = state['posts'].setdefault(key, {'images': {}})
        now = datetime.now(timezone.utc).isoformat()
        if kind == 'account':
            aid, _ = account_key(note)
            state['accounts'][aid] = {'decision': decision, 'source': 'manual', 'updated_at': now}
        elif kind == 'image':
            record.setdefault('images', {})[image_key] = decision
            record.setdefault('image_sources', {})[image_key] = 'manual'
        elif kind == 'post':
            if decision is None:
                record.pop('post_decision', None)
                record.pop('post_decision_source', None)
            else:
                record['post_decision'] = decision
                record['post_decision_source'] = 'manual'
        record['updated_at'] = now
        history = state.setdefault('events', [])
        history.append({'at': now, 'post_key': key, 'kind': kind, 'decision': decision})
        state['events'] = history[-5000:]
        state['source_file'] = path.relative_to(root).as_posix()
        write_state(root, path, state)
    if partial:
        aid, _ = account_key(note)
        affected = {note_key(item) for item in notes if account_key(item)[0] == aid} if kind == 'account' else {key}
        result = annotations(root, path, keys=affected)
        result['partial'] = True
        return result
    return annotations(root, path)

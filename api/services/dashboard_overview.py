"""Cross-task, read-only overview. Time filters use collection runs, never post dates."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from zipfile import BadZipFile

from api.services.dashboard import SHANGHAI, collect_dataset, date_range, timestamp
from api.services.data_browser import collection_status, paired_comment_files, text
from api.services.data_file_visibility import collection_files
from api.services.manual_review import annotations, note_key
from collection_tasks import read_task, runs, safe_path

READ_ERRORS = (OSError, ValueError, KeyError, TypeError, BadZipFile)
STATES = ('retained', 'review', 'excluded', 'unfiltered', 'processing', 'duplicate')
COUNTS = (*STATES, 'recorded', 'checked', 'comments', 'images', 'downloaded',
          'download_failed', 'online_images', 'missing_images', 'auto_passed', 'manual_retained', 'manual_excluded')


def number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


@lru_cache(maxsize=64)
def cached_dataset(root, signatures):
    return collect_dataset(Path(root), [item[0] for item in signatures])


def read_dataset(root, files, warnings):
    signatures = []
    for relative in dict.fromkeys(files):
        try:
            stat = safe_path(root, relative).stat()
            companions = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                               for path in paired_comment_files(safe_path(root, relative)))
            signatures.append((relative, stat.st_mtime_ns, stat.st_size, companions))
        except READ_ERRORS:
            warnings['missing_files'] += 1
    # Isolate a damaged export so other tasks remain visible.
    notes, comments, checked = {}, {}, 0
    for signature in signatures:
        try:
            rows, by_note, _, inspected = cached_dataset(str(root), (signature,))
            checked += inspected
            for row in rows:
                notes.setdefault(note_key(row), row)
            for nid, values in by_note.items():
                comments.setdefault(nid, []).extend(values)
        except READ_ERRORS:
            warnings['unreadable_files'] += 1
    return list(notes.values()), comments, checked


def legacy_time(root, files):
    for file in files:
        match = re.search(r'(20\d{6})_(\d{6})', Path(file).name)
        if match:
            try:
                return datetime.strptime(''.join(match.groups()), '%Y%m%d%H%M%S').replace(tzinfo=SHANGHAI)
            except ValueError:
                pass
    times = [safe_path(root, file).stat().st_mtime for file in files if safe_path(root, file).is_file()]
    return datetime.fromtimestamp(min(times), timezone.utc) if times else None


def catalog(root, warnings):
    tasks, registered = [], set()
    for metadata in sorted((root / '.collection-tasks').glob('*/task.json')):
        try:
            task = read_task(root, metadata.parent.name)
            records = []
            for path in runs(root, task):
                try:
                    records.append(json.loads(path.read_text(encoding='utf-8')))
                except READ_ERRORS:
                    warnings['unreadable_runs'] += 1
            registered.update(file for run in records for file in run.get('files', []))
            if task.get('anchor'):
                registered.add(task['anchor'])
                if not any(task['anchor'] in run.get('files', []) for run in records):
                    records.insert(0, {'id': 'legacy', 'files': [task['anchor']], 'status': 'historical'})
            tasks.append((task, records))
        except READ_ERRORS:
            warnings['unreadable_tasks'] += 1
    legacy = {}
    for path in collection_files(root):
        file = path.relative_to(root).as_posix()
        if file in registered or 'comment' in path.name.lower():
            continue
        stem = file.removesuffix('_semantic.xlsx') if file.endswith('_semantic.xlsx') else str(Path(file).with_suffix(''))
        legacy.setdefault(stem, []).append(file)
    for stem, files in legacy.items():
        # Pair only an exact main/semantic filename, never similar topics or dates.
        anchor = next((file for file in files if not file.endswith('_semantic.xlsx')), files[0])
        tasks.append(({'id': 'legacy-' + hashlib.sha256(stem.encode()).hexdigest()[:16],
                       'anchor': anchor, 'config': {}, 'targets': {}},
                      [{'id': 'legacy', 'files': files, 'status': 'historical'}]))
    return tasks


def summary_counts(root, task):
    identity = task['anchor'].removesuffix('_semantic.xlsx') if task['id'].startswith('legacy-') else task['id']
    counts = Counter()
    directory = root / '.content-summaries' / hashlib.sha256(identity.encode()).hexdigest()
    if not directory.is_symlink():
        for path in directory.glob('*.json'):
            try:
                counts[json.loads(path.read_text(encoding='utf-8')).get('status')] += 1
            except READ_ERRORS:
                continue
    return {'ready': counts['ready'], 'failed': counts['failed'],
            'running': counts['running'] + counts['queued']}


def timeline(rows, begin, finish, period):
    local = begin.astimezone(SHANGHAI)
    span = (finish - begin).total_seconds()
    hourly = period == 'today' or span <= 86400
    monthly = span > 120 * 86400
    cursor = local.replace(minute=0, second=0, microsecond=0) if hourly else local.replace(hour=0, minute=0, second=0, microsecond=0)
    if monthly:
        cursor = cursor.replace(day=1)
    points = []
    while cursor <= finish and len(points) < 400:
        points.append({'at': cursor.isoformat(), 'recorded': 0, 'retained': 0, 'review': 0, 'rounds': 0})
        cursor = ((cursor.replace(year=cursor.year + 1, month=1) if cursor.month == 12 else cursor.replace(month=cursor.month + 1))
                  if monthly else cursor + timedelta(hours=1) if hourly else cursor + timedelta(days=1))
    for at, metrics in rows:
        if at is None or not points:
            continue
        index = next((i for i in range(len(points) - 1, -1, -1) if timestamp(points[i]['at']) <= at), 0)
        for key in ('recorded', 'retained', 'review'):
            points[index][key] += metrics[key]
        points[index]['rounds'] += 1
    return points, 'month' if monthly else 'hour' if hourly else 'day'


def overview(root, manager, period='week', start=None, end=None, task_id=None, platform=None, *, now=None):
    root = Path(root).resolve()
    now = now or datetime.now(timezone.utc)
    warnings = Counter()
    prepared, all_times, options = [], [], []
    active_run = Path(getattr(manager, 'collection_run', '') or '').stem if manager.status in {'running', 'stopping'} else ''
    for task, records in catalog(root, warnings):
        config = task.get('config', {})
        anchor = task.get('anchor')
        task_platform = config.get('platform') or ('wb' if anchor and ('weibo' in anchor or anchor.startswith('wb/')) else 'xhs' if anchor and 'xhs' in anchor else 'other')
        all_notes, all_comments, batches = {}, {}, []
        for run in records:
            files = run.get('files', [])
            notes, comments, checked = read_dataset(root, files, warnings)
            at = timestamp(run.get('started_at'))
            approximate = not bool(at)
            if not at:
                at = legacy_time(root, files)
            if at:
                all_times.append(at)
            for note in notes:
                all_notes.setdefault(note_key(note), note)
            for nid, values in comments.items():
                all_comments.setdefault(nid, []).extend(values)
            diagnostics = sum(number(item.get('diagnostics', {}).get('evaluated')) for item in run.get('results', {}).values())
            batches.append((run, at, approximate, notes, comments, max(checked, diagnostics, len(notes))))
        title = ' / '.join(task.get('targets', {})) or ' / '.join(dict.fromkeys(text(note.get('source_keyword')) for note in all_notes.values() if note.get('source_keyword'))) or '历史采集'
        options.append({'id': task['id'], 'title': title, 'platform': task_platform,
                        'started_at': max((batch[1] for batch in batches if batch[1]), default=None)})
        if task_id and task['id'] != task_id or platform and task_platform != platform:
            continue
        review = {}
        if anchor and all_notes:
            try:
                review = annotations(root, safe_path(root, anchor), persist=False, dataset=(list(all_notes.values()), all_comments))['entries']
            except READ_ERRORS:
                warnings['unreadable_reviews'] += 1
        prepared.append((task, task_platform, title, batches, review))
    if period == 'all':
        begin, finish = min(all_times, default=now).astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0), now
    else:
        begin, finish = date_range(period, start, end, [], now)
    totals = Counter({key: 0 for key in COUNTS})
    tasks, events, unique_posts = [], [], set()
    for task, task_platform, title, batches, review in prepared:
        metrics = Counter({key: 0 for key in COUNTS})
        seen_notes, seen_comments, seen_images = set(), set(), set()
        selected, durations = [], []
        # Deduplicate supplements against earlier rounds, including rounds outside the filter.
        for run, at, approximate, notes, comments, checked in sorted(batches, key=lambda b: b[1] or datetime.min.replace(tzinfo=timezone.utc)):
            included = period == 'all' if at is None else begin <= at <= finish
            new_notes = [note for note in notes if note_key(note) not in seen_notes]
            seen_notes.update(note_key(note) for note in notes)
            if not included:
                if at is None:
                    warnings['unknown_round_times'] += 1
                for nid, items in comments.items():
                    seen_comments.update((nid, text(item.get('comment_id') or item.get('id')) or text(item.get('content'))) for item in items)
                continue
            selected.append((run, at, approximate))
            if approximate:
                warnings['estimated_round_times'] += 1
            if at is None:
                warnings['unknown_round_times'] += 1
            counts = Counter({key: 0 for key in COUNTS})
            counts['checked'] = checked
            counts['recorded'] = len(new_notes)
            for note in new_notes:
                nid = text(note.get('note_id') or note.get('aweme_id'))
                unique_posts.add((task_platform, nid))
                entry = review.get(note_key(note), {})
                decision = entry.get('decision')
                raw = collection_status(note)
                state = ('retained' if decision == 'qualified' else 'excluded' if decision == 'unqualified'
                         else {'matched': 'retained', 'review': 'review', 'excluded': 'excluded', 'pending': 'processing', 'duplicate': 'duplicate'}.get(raw, 'unfiltered'))
                if entry and decision is None and raw == 'matched':
                    state = 'review'  # Legacy uncertainty must not turn into a pass.
                counts[state] += 1
                counts['auto_passed'] += int(bool(entry.get('screening_passed')) and state == 'retained')
                counts['manual_retained'] += int(entry.get('decision_source') == 'manual' and state == 'retained')
                counts['manual_excluded'] += int(entry.get('decision_source') == 'manual' and state == 'excluded')
                for image in entry.get('review_images', []):
                    identity = (nid, image['key'])
                    if identity in seen_images:
                        continue
                    seen_images.add(identity)
                    counts['images'] += 1
                    availability = ('downloaded' if image.get('local') and not image.get('download_problem')
                                    else 'download_failed' if image.get('local') else 'online_images' if image.get('remote_url') or image.get('url') else 'missing_images')
                    counts[availability] += 1
            for nid, items in comments.items():
                for item in items:
                    identity = (nid, text(item.get('comment_id') or item.get('id')) or text(item.get('content')))
                    if identity not in seen_comments:
                        seen_comments.add(identity)
                        counts['comments'] += 1
            ended = timestamp(run.get('finished_at'))
            if at and (ended or run.get('id') == active_run):
                durations.append(max(0, ((ended or now) - at).total_seconds()))
            events.append((at, counts))
            metrics.update(counts)
        if not selected:
            continue
        latest = selected[-1][0]
        status = latest.get('status', 'historical')
        if status in {'running', 'starting'} and latest.get('id') != active_run:
            status = 'interrupted'
        summaries = summary_counts(root, task) if task.get('anchor') else {'ready': 0, 'failed': 0, 'running': 0}
        totals.update(metrics)
        targets = [number(value) for value in task.get('targets', {}).values()]
        tasks.append({'id': task['id'], 'title': title, 'platform': task_platform, 'file': task.get('anchor'),
                      'status': status, 'started_at': selected[0][1].isoformat() if selected[0][1] else None,
                      'last_at': selected[-1][1].isoformat() if selected[-1][1] else None,
                      'rounds': len(selected), 'target': sum(targets) or None, 'metrics': dict(metrics),
                      'duration_seconds': round(sum(durations)) if len(durations) == len(selected) else None,
                      'estimated_time': any(item[2] for item in selected), 'summaries': summaries})
    points, interval = timeline(events, begin, finish, period)
    tasks.sort(key=lambda task: timestamp(task['last_at']) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    options.sort(key=lambda task: task['started_at'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for option in options:
        option['started_at'] = option['started_at'].isoformat() if option['started_at'] else None
    totals.update(tasks=len(tasks), rounds=sum(task['rounds'] for task in tasks), unique_posts=len(unique_posts),
                  summary_ready=sum(task['summaries']['ready'] for task in tasks))
    return {'updated_at': now.isoformat(), 'range': {'period': period, 'start': begin.isoformat(), 'end': finish.isoformat(), 'interval': interval},
            'metrics': dict(totals), 'timeline': points, 'tasks': tasks, 'task_options': options,
            'warnings': dict(warnings), 'active': manager.status in {'running', 'stopping'},
            'scope': {'task_id': task_id, 'platform': platform, 'time_basis': 'collection_run_start', 'review_basis': 'current'}}

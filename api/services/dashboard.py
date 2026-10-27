"""Read current collection statistics without crawling, inferring or changing saved marks."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from api.services.data_browser import load_dataset, text
from api.services.data_file_visibility import collection_files
from api.services.manual_review import annotations, note_key
from collection_tasks import read_task, runs, safe_path, task_files
from semantic_quality import saved_collection_rejection, saved_jev_rejection

SHANGHAI = ZoneInfo('Asia/Shanghai')
DONE = {'target_reached', 'search_exhausted', 'duplicate_pages', 'page_budget', 'time_range_exhausted'}


def timestamp(value):
    if value is None or value == '':
        return None
    try:
        if isinstance(value, (int, float)) or str(value).replace('.', '', 1).isdigit():
            seconds = float(value)
            return datetime.fromtimestamp(seconds / 1000 if seconds > 1e11 else seconds, timezone.utc)
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value
    except (ValueError, OverflowError, OSError):
        return None


def select_task(root, manager, task_id=None):
    if task_id:
        return read_task(root, task_id)
    current = getattr(manager, 'collection_run', None)
    if manager.status in {'running', 'stopping'} and current and Path(current).is_file():
        return read_task(root, json.loads(Path(current).read_text(encoding='utf-8'))['task_id'])
    candidates = []
    for path in (root / '.collection-tasks').glob('*/task.json'):
        task = read_task(root, path.parent.name)
        run_records = [json.loads(path.read_text(encoding='utf-8')) for path in runs(root, task)]
        if not task_files(root, task):
            continue
        started = max((timestamp(run.get('started_at')) for run in run_records if timestamp(run.get('started_at'))), default=datetime.min.replace(tzinfo=timezone.utc))
        candidates.append((started, task))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def collect_dataset(root, files):
    notes, comments = {}, {}
    missing = []
    checked = 0
    for relative in files:
        path = safe_path(root, relative)
        if not path.is_file():
            missing.append(relative)
            continue
        rows, by_note = load_dataset(path)
        # Include saved exclusions in collected volume, never in qualified/review counts.
        if path.suffix.lower() == '.xlsx':
            book = load_workbook(path, read_only=True, data_only=True)
            try:
                if path.name.endswith('_semantic.xlsx') and 'Summary' in book:
                    summary = {row[0]: row[1] for row in book['Summary'].values if len(row) >= 2}
                    checked += sum(value for key in ('matched', 'review', 'excluded', 'pending', 'duplicate')
                                   if isinstance(value := summary.get(key), int) and not isinstance(value, bool))
                if 'Excluded' in book:
                    values = iter(book['Excluded'].values)
                    headers = next(values, ())
                    rows = [*rows, *[{**dict(zip(headers, row)), 'semantic_result': 'excluded'} for row in values if any(value is not None for value in row)]]
            finally:
                book.close()
        for note in rows:
            if not isinstance(note, dict) or not (note.get('note_id') or note.get('aweme_id')):
                continue
            notes.setdefault(note_key(note), {**note, '_collection_file': relative})
        for nid, items in by_note.items():
            comments.setdefault(nid, []).extend(items)
    return list(notes.values()), comments, missing, checked


def date_range(period, start, end, times, now):
    if period == 'custom':
        begin, finish = timestamp(start), timestamp(end)
        if not begin or not finish or begin >= finish:
            raise ValueError('invalid_date_range')
        return begin, finish
    if period == 'task':
        return (min(times), max(times) + timedelta(seconds=1)) if times else (now - timedelta(hours=1), now)
    local = now.astimezone(SHANGHAI)
    begin = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'week':
        begin -= timedelta(days=begin.weekday())
    elif period == 'month':
        begin = begin.replace(day=1)
    elif period == 'year':
        begin = begin.replace(month=1, day=1)
    return begin, now


def make_trend(events, begin, finish):
    span = max(1, (finish - begin).total_seconds())
    step = next((size for size in [600, 1800, 3600, 21600, 86400, 604800, 2678400] if span / size <= 12), math.ceil(span / 12))
    length = max(1, min(13, math.ceil(span / step)))
    points = [{'at': (begin + timedelta(seconds=index * step)).isoformat(), 'collected': 0, 'qualified': 0, 'images': 0} for index in range(length)]
    for event in events:
        at = event['at']
        if begin <= at <= finish:
            index = min(length - 1, int((at - begin).total_seconds() // step))
            points[index]['collected'] += 1
            points[index]['qualified'] += int(event['qualified'])
            points[index]['images'] += event['images']
    return points


def dashboard_snapshot(root, manager, period='task', start=None, end=None, task_id=None):
    root = Path(root).resolve()
    now = datetime.now(timezone.utc)
    task = select_task(root, manager, task_id)
    run_records = [json.loads(path.read_text(encoding='utf-8')) for path in runs(root, task)] if task else []
    files = task_files(root, task) if task else []
    if not task:
        # Older exports without lineage remain inspectable without inventing a task target.
        legacy = [path for path in collection_files(root) if 'comment' not in path.name.lower()]
        if legacy:
            files = [max(legacy, key=lambda path: path.stat().st_mtime).relative_to(root).as_posix()]
    notes, comments, missing, checked = collect_dataset(root, files)
    review_path = safe_path(root, (task or {}).get('anchor') or files[0]) if files else None
    review = annotations(root, review_path, persist=False, dataset=(notes, comments)) if review_path else {'entries': {}}
    targets = task.get('targets', {}) if task else {}
    keywords = list(dict.fromkeys([*targets, *[text(note.get('source_keyword')) for note in notes]]))
    results = {}
    for run in run_records:
        results.update(run.get('results', {}))
    running = manager.status in {'running', 'stopping'} and bool(task and getattr(manager, 'collection_run', None) and any(Path(manager.collection_run).stem == run.get('id') for run in run_records))
    current = next((keyword for keyword, result in reversed(list(results.items())) if result.get('reason') == 'searching'), '') if running else ''
    groups = {keyword: {'keyword': keyword, 'collected': 0, 'qualified': 0, 'target': targets.get(keyword),
                       'reason': results.get(keyword, {}).get('reason'), 'status': 'pending'} for keyword in keywords}
    images, events = {}, []
    qualified_total = pending_review = unknown_time = 0
    for note in notes:
        nid = text(note.get('note_id') or note.get('aweme_id'))
        entry = review['entries'][note_key(note)]
        keyword = text(note.get('source_keyword'))
        status = note.get('semantic_result')
        rejection = entry.get('semantic_rejection_reason') or entry.get('account_rejection_reason') or saved_jev_rejection(note) or saved_collection_rejection(note, comments.get(nid, []))
        qualified = not rejection and status not in {'excluded', 'duplicate', 'pending'} and (status in {'matched', 'review'} or not (task or {}).get('config', {}).get('semantic_filter'))
        if note.get('semantic_rule') in {'topic', 'evaluation'} and status != 'matched':
            qualified = False
        groups[keyword]['collected'] += 1
        groups[keyword]['qualified'] += int(qualified)
        qualified_total += int(qualified)
        human = entry.get('decision_source') == 'manual'
        pending_review += int(qualified and (entry.get('decision') is None or not human))
        downloaded = 0
        for image in entry['review_images']:
            identity = image.get('url') if image.get('local') else f'{nid}:{image["key"]}'
            if identity in images:
                continue
            prediction = {}
            problem = image.get('download_problem')
            download = 'downloaded' if image.get('local') and not problem else 'failed' if image.get('local') and problem else 'pending'
            suggestion = prediction.get('suggestion')
            recognized = 'qualified' if suggestion == 'qualified' else 'unqualified' if suggestion == 'unqualified' else 'failed' if prediction.get('status') in {'failed', 'error'} else 'pending'
            images[identity] = {'name': image['key'], 'keyword': keyword, 'note_id': nid, 'file': note['_collection_file'],
                                'download': download, 'status': recognized, 'url': image.get('url') if image.get('local') else None,
                                'reason': text(prediction.get('reason') or prediction.get('error') or prediction.get('consistency_reason') or prediction.get('type_reason'))[:500]}
            downloaded += int(download == 'downloaded')
        at = timestamp(note.get('last_modify_ts') or note.get('add_ts'))
        if at:
            events.append({'at': at, 'keyword': keyword, 'qualified': qualified, 'images': downloaded})
        else:
            unknown_time += 1
    for keyword, group in groups.items():
        group['status'] = 'running' if keyword == current else 'completed' if group['reason'] in DONE or (group['target'] and group['qualified'] >= group['target']) else 'interrupted' if keyword in results else 'pending'
    downloaded_images = [image for image in images.values() if image['download'] == 'downloaded']
    counts = Counter(image['status'] for image in downloaded_images)
    completed = counts['qualified'] + counts['unqualified']
    image_counts = {'downloaded': len(downloaded_images), 'download_pending': sum(image['download'] == 'pending' for image in images.values()),
                    'download_failed': sum(image['download'] == 'failed' for image in images.values()),
                    'qualified': counts['qualified'], 'unqualified': counts['unqualified'], 'pending': counts['pending'], 'failed': counts['failed'],
                    'recognized': completed, 'pass_rate': round(100 * counts['qualified'] / completed, 1) if completed else None}
    begin, finish = date_range(period, start, end, [event['at'] for event in events], now)
    selected_events = [event for event in events if begin <= event['at'] <= finish]
    ranking = Counter(event['keyword'] for event in selected_events)
    accepted = Counter(event['keyword'] for event in selected_events if event['qualified'])
    platform = (task or {}).get('config', {}).get('platform') or ('xhs' if files and ('xhs/' in files[0] or Path(files[0]).name.startswith('xhs_')) else 'wb' if files and ('weibo' in files[0] or 'wb/' in files[0]) else '')
    saved_status = run_records[-1].get('status', 'idle') if run_records else 'idle'
    if not running and saved_status in {'running', 'starting'}:
        saved_status = 'interrupted'
    return {'updated_at': now.isoformat(), 'task': {'id': task['id'] if task else None, 'platform': platform,
            'file': (task or {}).get('anchor') or (files[0] if files else None), 'files': files,
            'status': (getattr(manager, 'stage', 'running') if manager.status == 'running' else manager.status) if running else saved_status,
            'started_at': run_records[0].get('started_at') if run_records else None, 'current_keyword': current,
            'completed_groups': sum(group['status'] == 'completed' for group in groups.values()), 'total_groups': len(groups)},
            'metrics': {'collected_posts': len(notes), 'checked_posts': max(len(notes), checked, sum(
                result.get('diagnostics', {}).get('evaluated', 0)
                for run in run_records for result in run.get('results', {}).values())),
                'qualified_posts': qualified_total, 'collected_comments': sum(len({text(c.get('comment_id') or c.get('id')) or text(c.get('content')) for c in items}) for items in comments.values()), 'pending_review': pending_review, 'images': image_counts},
            'groups': list(groups.values()), 'ranking': [{'keyword': key, 'collected': ranking[key], 'qualified': accepted[key]} for key in keywords],
            'trend': make_trend(selected_events, begin, finish),
            'group_trends': {key: make_trend([event for event in selected_events if event['keyword'] == key], begin, finish) for key in keywords},
            'range': {'start': begin.isoformat(), 'end': finish.isoformat(), 'period': period},
            'images': downloaded_images, 'missing_files': missing, 'unknown_time_posts': unknown_time}


def collection_progress(root, manager):
    """Progress for this backend session only; never substitute an older task."""
    run_path = getattr(manager, 'collection_run', None)
    status = manager.status
    stage = getattr(manager, 'stage', 'idle')
    result = {'session_id': manager.log_session_id, 'status': status, 'stage': stage,
              'started_at': manager.started_at.isoformat() if manager.started_at else None,
              'task_id': None, 'current_keyword': '', 'checked': 0, 'saved': 0, 'qualified': 0,
              'target': None, 'percent': None, 'comments': 0, 'images': 0, 'completed_topics': 0,
              'total_topics': 0, 'updated_at': datetime.now(timezone.utc).isoformat()}
    if not run_path or not Path(run_path).is_file():
        return result
    run = json.loads(Path(run_path).read_text(encoding='utf-8'))
    result['run_status'] = run.get('status')
    data = dashboard_snapshot(root, manager, task_id=run['task_id'])
    groups = [group for group in data['groups'] if isinstance(group.get('target'), int) and group['target'] > 0]
    target = sum(group['target'] for group in groups) or None
    achieved = sum(min(group['qualified'], group['target']) for group in groups)
    result.update(task_id=run['task_id'], current_keyword=data['task']['current_keyword'],
                  checked=data['metrics']['checked_posts'], saved=data['metrics']['collected_posts'],
                  qualified=data['metrics']['qualified_posts'], target=target,
                  percent=round(100 * achieved / target) if target else None,
                  comments=data['metrics']['collected_comments'], images=data['metrics']['images']['downloaded'],
                  completed_topics=data['task']['completed_groups'], total_topics=data['task']['total_groups'])
    return result

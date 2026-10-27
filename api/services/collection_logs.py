"""Read durable per-keyword collection diagnostics across initial and supplement runs."""
import json

from collection_tasks import find_task, runs, task_files
from account_audit import events


COUNTERS = ('pages_checked', 'checked_page', 'http_status', 'api_ok', 'cards_count', 'parsed_count',
            'blocked_accounts', 'evaluated', 'not_retained', 'outside_time_range', 'unknown_publish_time')
MESSAGES = {'empty_result', 'success', 'api_error', 'non_json', 'request_failed', 'login_required'}
REASONS = {'target_reached', 'search_exhausted', 'duplicate_pages', 'page_budget',
           'semantic_unavailable', 'request_failed', 'parse_failed', 'searching', 'login_required', 'time_range_exhausted'}


def safe_diagnostics(value):
    value = value if isinstance(value, dict) else {}
    result = {key: value[key] for key in COUNTERS
              if isinstance(value.get(key), int) and not isinstance(value[key], bool)}
    if value.get('message_code') in MESSAGES:
        result['message_code'] = value['message_code']
    return result


def evidence(reason, diagnostics):
    if reason == 'search_exhausted':
        if not diagnostics:
            return 'legacy_unknown'
        if (diagnostics.get('message_code') == 'empty_result'
                and diagnostics.get('api_ok') == 0 and diagnostics.get('cards_count') == 0
                and 200 <= diagnostics.get('http_status', 0) < 300):
            return 'confirmed_empty'
        if diagnostics.get('cards_count', 0) > 0 and diagnostics.get('parsed_count') == 0:
            return 'unparsed_cards'
        return 'no_parsed_posts'
    return reason


def collection_logs(root, path):
    task = find_task(root, path)
    response = {'task_id': task['id'] if task else None, 'rounds': [], 'entries': []}
    run_paths = list(runs(root, task)) if task else []
    account_events = events(root, task_files(root, task) if task else [path.relative_to(root).as_posix()],
                            [item.stem for item in run_paths])
    if account_events:
        response['account_events'] = account_events
    from comment_audit import events as comment_events
    comments = comment_events(root, task_files(root, task) if task else [path.relative_to(root).as_posix()],
                              [item.stem for item in run_paths])
    if comments:
        response['comment_events'] = comments
    if not task:
        return response
    for number, run_path in enumerate(run_paths, 1):
        run = json.loads(run_path.read_text(encoding='utf-8'))
        status = run.get('status', 'unknown')
        response['rounds'].append({'number': number, 'status': status,
            'started_at': run.get('started_at'), 'finished_at': run.get('finished_at')})
        for keyword, target in run.get('quotas', {}).items():
            result = run.get('results', {}).get(keyword, {})
            reason = result.get('reason') if result.get('reason') in REASONS else 'not_recorded'
            if reason == 'searching' and status not in {'starting', 'running'}:
                reason = 'interrupted'
            if not result and status not in {'starting', 'running'}:
                reason = 'not_reached'
            diagnostics = safe_diagnostics(result.get('diagnostics'))
            retained = result.get('retained', 0)
            # Whitelisted fields only: task config and raw responses never leave
            # the service through this endpoint.
            response['entries'].append({'id': f"{run['id']}:{keyword}", 'round': number,
                'keyword': keyword, 'target': target, 'retained': retained,
                'missing': max(0, target - retained), 'reason': reason,
                'evidence': evidence(reason, diagnostics), 'diagnostics': diagnostics,
                'page': diagnostics.get('checked_page', run.get('cursors', {}).get(keyword, {}).get('page')) if result else None,
                'recorded_at': run.get('result_times', {}).get(keyword), 'run_status': status})
    response['entries'].reverse()
    return enrich_logs(root, path, task, response)


def enrich_logs(root, path, task, response):
    from api.services import crawler_manager
    from api.services.dashboard import dashboard_snapshot, timestamp
    from api.services.manual_review import read_state
    from api.services.content_summary import summary_jobs
    from datetime import datetime, timezone
    from pathlib import Path
    import re

    config = task.get('config', {})
    snapshot = dashboard_snapshot(root, crawler_manager, task_id=task['id'])
    overview = {'platform': snapshot['task']['platform'], 'status': snapshot['task']['status'],
                'target': sum(task.get('targets', {}).values()), 'topics': len(task.get('targets', {})),
                'saved': snapshot['metrics']['collected_posts'], 'checked': snapshot['metrics']['checked_posts'],
                'qualified': snapshot['metrics']['qualified_posts'], 'comments': snapshot['metrics']['collected_comments'],
                'images': snapshot['metrics']['images']['downloaded'], 'pending_review': snapshot['metrics']['pending_review'],
                'files': snapshot['task']['files'], 'missing_files': snapshot['missing_files'],
                'filter': ('evaluation' if config.get('semantic_rule') == 'scene' else 'topic') if config.get('semantic_filter') else 'off' if 'semantic_filter' in config else None,
                'comments_enabled': config.get('enable_comments'), 'media_enabled': config.get('enable_media'),
                'publish_range': config.get('publish_time_range'),
                'publish_start': config.get('publish_start_date'), 'publish_end': config.get('publish_end_date')}
    timeline = []
    for run in response['rounds']:
        at, finish = timestamp(run['started_at']), timestamp(run['finished_at'])
        run['elapsed_seconds'] = max(0, int(((finish or datetime.now(timezone.utc)) - at).total_seconds())) if at else None
        entries = [item for item in response['entries'] if item['round'] == run['number']]
        run['target'] = sum(item['target'] for item in entries)
        run['retained'] = sum(item['retained'] for item in entries)
        run['pages'] = sum(item['diagnostics'].get('pages_checked', 0) for item in entries)
        if at:
            timeline.append({'kind': 'run_started', 'at': run['started_at'], 'round': run['number'], 'target': run['target']})
        if finish:
            timeline.append({'kind': 'run_finished', 'at': run['finished_at'], 'round': run['number'], 'status': run['status'], 'retained': run['retained'], 'target': run['target']})
    for item in response['entries']:
        if item['recorded_at']:
            timeline.append({'kind': 'search_progress', 'at': item['recorded_at'], 'round': item['round'],
                             'keyword': item['keyword'], 'retained': item['retained'], 'target': item['target'], 'reason': item['reason']})
    anchor = Path(root) / (task.get('anchor') or path.relative_to(root))
    state = read_state(root, anchor)
    audit = state.get('events', [])
    recorded = set()
    for item in audit[-200:]:
        if item.get('kind') not in {'post', 'account', 'image'} or item.get('decision') not in {None, 'qualified', 'unqualified', 'marketing', 'non_marketing'} or not timestamp(item.get('at')):
            continue
        key = str(item.get('post_key', ''))
        recorded.add(key)
        timeline.append({'kind': 'review_' + item['kind'], 'at': item['at'], 'post_id': key.split(':', 1)[0], 'keyword': key.partition(':')[2], 'decision': item['decision']})
    # Historical state contains only its latest explicit conclusion; do not invent earlier edits.
    for key, item in state['posts'].items():
        if key not in recorded and item.get('post_decision_source') == 'manual' and item.get('post_decision') in {'qualified', 'unqualified'} and timestamp(item.get('updated_at')):
            timeline.append({'kind': 'review_latest', 'at': item['updated_at'], 'post_id': key.split(':', 1)[0], 'keyword': key.partition(':')[2], 'decision': item['post_decision']})
    for job in summary_jobs._history(root, path)[:50]:
        if not timestamp(job.get('created_at')):
            continue
        timeline.append({'kind': 'summary_started', 'at': job['created_at'], 'model': job.get('options', {}).get('model', ''), 'records': job.get('total', 0)})
        if timestamp(job.get('finished_at')):
            code = str(job.get('error') or '')
            timeline.append({'kind': 'summary_finished', 'at': job['finished_at'], 'status': job.get('status'),
                             'model': job.get('options', {}).get('model', ''), 'records': job.get('processed', 0),
                             'error': code if re.fullmatch(r'summary_[a-z_]+', code) else None})
    timeline.sort(key=lambda item: timestamp(item['at']), reverse=True)
    return {**response, 'overview': overview, 'timeline': timeline[:200]}

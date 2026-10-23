"""Read durable per-keyword collection diagnostics across initial and supplement runs."""
import json

from collection_tasks import find_task, runs, task_files
from account_audit import events


COUNTERS = ('pages_checked', 'checked_page', 'http_status', 'api_ok', 'cards_count', 'parsed_count',
            'blocked_accounts', 'evaluated', 'not_retained')
MESSAGES = {'empty_result', 'success', 'api_error', 'non_json', 'request_failed', 'login_required'}
REASONS = {'target_reached', 'search_exhausted', 'duplicate_pages', 'page_budget',
           'semantic_unavailable', 'request_failed', 'parse_failed', 'searching', 'login_required'}


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
    return response

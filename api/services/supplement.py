"""Compute human-approved shortfalls and start bounded replacement rounds."""
import asyncio
import json
import os
from pathlib import Path

from collection_tasks import create_task, find_task, finish_run, prepare_run, runs, task_files
from api.schemas import CrawlerStartRequest
from api.services.data_browser import load_review_dataset
from api.services.manual_review import annotations, note_key
from media_platform.weibo.session import read_session

_start_lock = asyncio.Lock()


def plan(root, path, manager):
    notes, _ = load_review_dataset(root, path)
    task = find_task(root, path)
    review = annotations(root, path)
    groups = {}
    for note in notes:
        keyword = str(note.get('source_keyword') or '').strip()
        group = groups.setdefault(keyword, {'keyword': keyword, 'retained': 0, 'excluded': 0, 'pending': 0})
        decision = review['entries'][note_key(note)]['decision']
        group[{'qualified': 'retained', 'unqualified': 'excluded'}.get(decision, 'pending')] += 1
    for keyword, target in (task['targets'] if task else {}).items():
        groups.setdefault(keyword, {'keyword': keyword, 'retained': 0, 'excluded': 0, 'pending': 0})
    for keyword, group in groups.items():
        group['target'] = task['targets'].get(keyword) if task else None
        group['shortfall'] = max(0, group['target'] - group['retained']) if group['target'] is not None else None
    completed = all(group['pending'] == 0 for group in groups.values()) and bool(groups)
    running = manager.status in {'running', 'stopping'}
    supported = (task['config'].get('platform') == 'wb' if task else
                 path.parent.name in {'weibo', 'wb'} or path.name.startswith('weibo_'))
    last_run = None
    round_count = 1
    if task and task['runs']:
        paths = list(runs(root, task))
        last_run = json.loads(paths[-1].read_text(encoding='utf-8'))
        original_in_round = any(task.get('anchor') in json.loads(item.read_text(encoding='utf-8')).get('files', []) for item in paths)
        round_count = len(paths) + (0 if original_in_round else 1)
    config = task['config'] if task else None
    cache = manager.task_credentials.get(task['id'], {}) if task else {}
    needs_key = bool(config and config.get('semantic_filter') and config.get('semantic_model') == 'jev-1.13.0'
                     and not cache.get('semantic_api_key') and not os.environ.get('TYPESAFE_API_KEY'))
    qr_mode = bool(config and config.get('login_type') == 'qrcode' and not cache.get('cookies'))
    qr_saved = bool(read_session(getattr(manager, '_project_root', Path(__file__).resolve().parents[2])))
    return {'task_id': task['id'] if task else None, 'anchor': task.get('anchor') if task else path.relative_to(root).as_posix(),
            'groups': list(groups.values()), 'review_complete': completed, 'running': running,
            'supported': bool(supported and all(groups)), 'needs_setup': task is None, 'needs_api_key': needs_key,
            'shortfall': sum(group['shortfall'] or 0 for group in groups.values()) if task else None,
            'rounds': round_count, 'files': task_files(root, task) if task else [],
            'last_results': last_run.get('results', {}) if last_run else {},
            'last_status': last_run.get('status') if last_run else None,
            'needs_cookies': os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1' and not qr_mode and not cache.get('cookies'),
            'needs_qr_login': os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1' and qr_mode and not qr_saved,
            'config': config}


async def start_supplement(root, path, manager, target=None, config=None, api_key=None, cookies=None):
    async with _start_lock:
        status = plan(root, path, manager)
        if status['running']:
            raise ValueError('collection_active')
        if not status['supported']:
            raise ValueError('supplement_weibo_only')
        if not status['review_complete']:
            raise ValueError('review_incomplete')
        task = find_task(root, path)
        if task is None:
            if target is None or config is None:
                raise ValueError('supplement_setup_required')
            keywords = [group['keyword'] for group in status['groups']]
            pairs = [tuple(keyword.split(maxsplit=1)) for keyword in keywords]
            config = config.model_copy(update={'platform': config.platform.__class__('wb'),
                'crawler_type': config.crawler_type.__class__('search'), 'save_option': config.save_option.__class__('excel'),
                'keywords': ','.join(keywords), 'keyword_pairs': [pair for pair in pairs if len(pair) == 2],
                'max_notes_count': target})
            if config.semantic_filter and any(len(pair) != 2 for pair in pairs):
                raise ValueError('invalid_keyword_pairs')
            snapshot = config.model_dump(mode='json', exclude={'cookies', 'semantic_api_key'})
            task = create_task(root, snapshot, {keyword: target for keyword in keywords}, path.relative_to(root).as_posix())
        else:
            snapshot = task['config']
            cached = manager.task_credentials.get(task['id'], {})
            config = CrawlerStartRequest(**snapshot, cookies=cached.get('cookies', ''))
        if cookies is not None:
            config = config.model_copy(update={'cookies': cookies.get_secret_value(), 'login_type': config.login_type.__class__('cookie')})
        if os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1':
            if config.cookies.strip():
                config = config.model_copy(update={'login_type': config.login_type.__class__('cookie')})
            elif config.login_type.value == 'qrcode':
                if not read_session(getattr(manager, '_project_root', Path(__file__).resolve().parents[2])):
                    raise ValueError('qr_login_required')
            else:
                raise ValueError('cookies_required')
        cached_key = manager.task_credentials.get(task['id'], {}).get('semantic_api_key')
        supplied = api_key.get_secret_value() if api_key else None
        from pydantic import SecretStr
        if supplied or cached_key:
            config = config.model_copy(update={'semantic_api_key': SecretStr(supplied or cached_key)})
        # Check again using the newly attached task and the latest shared labels.
        status = plan(root, path, manager)
        quotas = {group['keyword']: group['shortfall'] for group in status['groups'] if group['shortfall']}
        if not quotas:
            raise ValueError('target_reached')
        notes, _ = load_review_dataset(root, path)
        state = annotations(root, path)
        blocked = [entry['account_key'].removeprefix('creator:') for entry in state['entries'].values()
                   if entry['account'] == 'marketing' and entry['account_key'].startswith('creator:')]
        seed = [str(note.get('note_id') or '') for note in notes]
        run = prepare_run(root, task, quotas, seed, blocked, supplement=True)
        config = config.model_copy(update={'keywords': ','.join(quotas),
            'keyword_pairs': [tuple(keyword.split(maxsplit=1)) for keyword in quotas if len(keyword.split(maxsplit=1)) == 2],
            'max_notes_count': max(quotas.values())})
        try:
            if not await manager.start(config, collection_run=run):
                raise ValueError('supplement_start_failed')
        except Exception:
            finish_run(run, 'failed')
            raise
        return plan(root, path, manager)

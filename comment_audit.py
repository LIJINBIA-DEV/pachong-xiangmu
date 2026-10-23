"""Persist whitelisted comment request outcomes without credentials or response bodies."""
import json
import os
from pathlib import Path
import re
import uuid

import httpx
from collection_tasks import atomic_json, timestamp

REASONS = {
    'historical_comment_failure': '旧采集记录显示评论抓取失败，但未保存当时的具体错误；本条双关键词未满足，已排除正式结果。',
    'platform_filtered': '微博返回“已过滤部分评论”，未提供可读取的评论数据。',
    'login_required': '微博要求重新登录或验证，采集已暂停。',
    'rate_limited': '微博接口限制请求频率。',
    'http_error': '微博评论接口返回 HTTP 错误。',
    'network_timeout': '连接或读取微博评论接口超时。',
    'network_error': '连接微博评论接口失败。',
    'non_json': '微博评论接口没有返回 JSON 数据。',
    'cursor_missing': '评论响应缺少分页游标，无法确认评论已采集完整。',
    'cursor_repeated': '评论分页游标重复，无法继续读取。',
    'invalid_response': '微博返回的评论数据结构不符合预期。',
    'api_error': '微博评论接口返回业务错误。',
    'unexpected_error': '评论处理发生异常，详见异常类型。',
    'success': '本次评论请求成功。',
}


def safe_message(value):
    text = str(value or '')
    # Only the API's short msg field is passed here, never bodies or headers.
    text = re.sub(r'https?://\S+', '<REDACTED>', text, flags=re.I)
    text = re.sub(r'\bsk-[\w-]+', '<REDACTED>', text, flags=re.I)
    text = re.sub(r'(?:cookie|authorization|bearer|api[_ -]?key|token|SUBP?|XSRF-TOKEN)\s*[:= ]\s*.*', '<REDACTED>', text, flags=re.I)
    return ''.join(char for char in text if char.isprintable())[:160]


def failure_details(exception, diagnostics=None):
    while hasattr(exception, 'last_attempt') and exception.last_attempt.exception() is not None:
        exception = exception.last_attempt.exception()
    details = {}
    for key in ('http_status', 'api_ok', 'request_count', 'page_count'):
        value = (diagnostics or {}).get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            details[key] = value
    details['response_message'] = safe_message((diagnostics or {}).get('response_message'))
    details['exception_type'] = type(exception).__name__
    kind = details['exception_type']
    message = str(exception)
    code = (diagnostics or {}).get('message_code')
    if kind == 'LoginRequired':
        reason = 'login_required'
    elif kind == 'CommentsUnavailable':
        reason = 'platform_filtered'
    elif isinstance(exception, httpx.TimeoutException):
        reason = 'network_timeout'
    elif message.startswith('Missing comment cursor'):
        reason = 'cursor_missing'
    elif message.startswith('Repeated comment cursor'):
        reason = 'cursor_repeated'
    elif message.startswith(('Invalid comment data', 'Invalid comment response')):
        reason = 'invalid_response'
    elif details.get('http_status') == 429:
        reason = 'rate_limited'
    elif details.get('http_status', 0) >= 400:
        reason = 'http_error'
    elif code == 'non_json':
        reason = 'non_json'
    elif kind == 'DataFetchError':
        reason = 'api_error'
    elif isinstance(exception, httpx.RequestError):
        reason = 'network_error'
    else:
        reason = 'unexpected_error'
    return {**details, 'reason': reason, 'explanation': REASONS[reason]}


def record_result(note_id, diagnostics, *, root=None, source_file='', stage='collection', status='failed'):
    run_path = os.environ.get('MEDIACRAWLER_COLLECTION_RUN') if stage == 'collection' else None
    run = json.loads(Path(run_path).read_text(encoding='utf-8')) if run_path else {}
    if root is None:
        if run_path:
            root = Path(run_path).parents[2]
        else:
            import config
            root = Path(config.SAVE_DATA_PATH or 'data')
    reason = diagnostics.get('reason')
    reason = reason if reason in REASONS else 'unexpected_error'
    row = {'id': uuid.uuid4().hex, 'stage': stage, 'run_id': run.get('id'),
           'source_file': source_file, 'note_id': str(note_id), 'status': status,
           'reason': reason, 'explanation': REASONS[reason], 'recorded_at': timestamp(),
           'response_message': safe_message(diagnostics.get('response_message')),
           'exception_type': re.sub(r'[^A-Za-z0-9_]', '', str(diagnostics.get('exception_type') or ''))[:80]}
    for key in ('http_status', 'api_ok', 'request_count', 'page_count', 'returned_comments'):
        value = diagnostics.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            row[key] = value
    target = Path(root) / '.comment-audit/events' / (row['id'] + '.json')
    atomic_json(target, row)
    target.chmod(0o600)
    return row


def events(root, files=(), run_ids=()):
    result = []
    fields = {'id', 'stage', 'run_id', 'source_file', 'note_id', 'status', 'reason', 'explanation',
              'recorded_at', 'response_message', 'exception_type', 'http_status', 'api_ok',
              'request_count', 'page_count', 'returned_comments'}
    for path in (Path(root) / '.comment-audit/events').glob('*.json'):
        row = json.loads(path.read_text(encoding='utf-8'))
        if row.get('source_file') in files or row.get('run_id') in run_ids:
            result.append({key: row[key] for key in fields if key in row})
    return sorted(result, key=lambda row: row['recorded_at'], reverse=True)

"""Evaluate the original 50 samples without modifying production review data.

The cloud credential is read from stdin only; never serialized or logged.
Uses the running local model if available, or starts an isolated local reviewer
only when the production inference lock is free.
"""
import argparse
import asyncio
from collections import Counter
import csv
import hashlib
import getpass
import json
from pathlib import Path
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time

import httpx

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from collection_tasks import atomic_json
from image_subject import (PROMPT, SCHEMA, MAX_TOKENS, MODEL, encode_image,
                           fingerprint, valid_prediction, image_suggestion,
                           LocalImageReviewer, inference_busy, InferenceLease)

CLOUD_MODEL = 'Qwen/Qwen3.5-4B'
QUESTION = 'Identify the main subject and image type. Distinguish physical scene photographs from designed graphics and interface screenshots.'


def running_local():
    command = "Get-CimInstance Win32_Process -Filter \"Name = 'llama-server.exe'\" | Select-Object CommandLine | ConvertTo-Json -Compress"
    raw = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, text=True, encoding='utf-8', timeout=15)
    if raw.returncode or not raw.stdout.strip():
        return None
    processes = json.loads(raw.stdout)
    for process in processes if isinstance(processes, list) else [processes]:
        args = [arg.strip('"') for arg in shlex.split(process.get('CommandLine') or '', posix=False)]
        if '--model' in args and Path(args[args.index('--model') + 1]).resolve() == MODEL.resolve():
            if args[args.index('--host') + 1] not in ('127.0.0.1', 'localhost'):
                continue
            return ('http://127.0.0.1:' + args[args.index('--port') + 1], args[args.index('--api-key') + 1])
    return None


def payload(data, cloud):
    value = {'model': CLOUD_MODEL if cloud else MODEL.name,
             'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': [
                 {'type': 'text', 'text': QUESTION},
                 {'type': 'image_url', 'image_url': {'url': data, **({'detail': 'high'} if cloud else {})}}]}],
             'temperature': 0, 'max_tokens': MAX_TOKENS, 'stream': False,
             'response_format': {'type': 'json_schema', 'json_schema': {'name': 'main_subject_and_type', 'strict': True, 'schema': SCHEMA}}}
    value.update({'enable_thinking': False} if cloud else {'chat_template_kwargs': {'enable_thinking': False}})
    return value


def parse_result(raw):
    content = raw['choices'][0]['message']['content'].strip()
    if content.startswith('```'):
        content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
    result = json.loads(content)
    if not valid_prediction(result):
        raise ValueError('invalid_prediction')
    return {**result, 'status': 'recognized', 'suggestion': image_suggestion(result), 'usage': raw.get('usage'),
            'served_model': raw.get('model'), 'finish_reason': raw['choices'][0].get('finish_reason'), 'raw_output': content}


async def request_prediction(client, url, data, cloud):
    body = payload(data, cloud)
    started = time.perf_counter()
    errors = []
    for attempt in range(4):
        try:
            response = await client.post(url + '/v1/chat/completions', json=body)
            if response.status_code == 400 and cloud and body['response_format']['type'] == 'json_schema':
                # Some deployments do not expose strict structured output.
                errors.append({'status': 400, 'reason': 'schema_request_rejected'})
                body['response_format'] = {'type': 'json_object'}
                continue
            if response.status_code in (401, 403):
                return {'status': 'error', 'error': 'authentication_or_permission', 'http_status': response.status_code}
            response.raise_for_status()
            result = parse_result(response.json())
            return {**result, 'elapsed_seconds': round(time.perf_counter() - started, 3),
                    'attempts': attempt + 1, 'response_format': body['response_format']['type'], 'retry_errors': errors,
                    'trace_id': response.headers.get('x-siliconcloud-trace-id')}
        except httpx.HTTPStatusError as exc:
            errors.append({'status': exc.response.status_code})
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                break
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            errors.append({'error': type(exc).__name__})
        if attempt < 3:
            await asyncio.sleep(2 ** (attempt + 1))
    return {'status': 'error', 'error': 'request_or_response_failed', 'retry_errors': errors,
            'elapsed_seconds': round(time.perf_counter() - started, 3)}


async def run(args, key):
    sample = PROJECT.parent / 'model'
    sources = list(csv.DictReader((sample / '准备记录/50张图片来源.csv').open(encoding='utf-8-sig')))
    historical = {r['filename']: r for r in csv.DictReader((sample / '图片主体识别结果.csv').open(encoding='utf-8-sig'))}
    assert len(sources) == 50
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'results').mkdir(exist_ok=True)
    (out / 'images').mkdir(exist_ok=True)
    version = fingerprint()
    atomic_json(out / 'config.json', {'model_cloud': CLOUD_MODEL, 'model_local': MODEL.name, 'prompt': PROMPT,
        'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(), 'fingerprint_local': version,
        'max_edge': 1024, 'max_tokens': MAX_TOKENS, 'temperature': 0, 'thinking': False,
        'cloud_detail': 'high', 'local_image_max_tokens': 1024, 'cloud_concurrency': 3,
        'note': 'Identical pixels and rules; provider image preprocessing and weights can differ. Agreement is not accuracy.'})
    rows = []
    for index, source in enumerate(sources):
        path = sample / '50张图片' / source['filename']
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        assert sha == source['sha256'], 'Original sample changed'
        shutil.copy2(path, out / 'images' / path.name)
        target = out / 'results' / (path.stem + '.json')
        existing = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
        if existing.get('sha256') != sha or existing.get('fingerprint') != version:
            existing = {}
        rows.append({'index': index + 1, 'filename': path.name, 'path': path, 'sha256': sha,
                     'source': source, 'historical': historical[path.name], 'result_path': target,
                     'cloud': existing.get('cloud'), 'local': existing.get('local')})
    started = time.perf_counter()
    cloud_sem = asyncio.Semaphore(3)
    pace = asyncio.Lock()
    last_sent = 0.0
    def save(row):
        atomic_json(row['result_path'], {k: row[k] for k in ('index', 'filename', 'sha256', 'cloud', 'local', 'historical') } | {'fingerprint': version})
        atomic_json(out / 'progress.json', {'total': 50,
             'cloud_completed': sum(r.get('cloud', {}).get('status') == 'recognized' for r in rows if r.get('cloud')),
             'local_completed': sum(r.get('local', {}).get('status') == 'recognized' for r in rows if r.get('local')),
             'elapsed_seconds': round(time.perf_counter() - started, 1)})
    async def cloud_one(client, row):
        nonlocal last_sent
        if row.get('cloud', {}).get('status') == 'recognized' if row.get('cloud') else False:
            return
        async with cloud_sem:
            async with pace:
                await asyncio.sleep(max(0, 2.5 - (time.monotonic() - last_sent)))
                last_sent = time.monotonic()
            data, size = await asyncio.to_thread(encode_image, row['path'])
            result = await request_prediction(client, 'https://api.siliconflow.cn', data, True)
            row['cloud'] = {**result, 'input_size': size, 'cache_used': False}
            save(row)
            print('cloud', row['index'], result.get('label') or result.get('error'), flush=True)
            if result.get('error') == 'authentication_or_permission':
                raise RuntimeError('cloud_authentication_or_permission_failed')
    async def local_all():
        attached = await asyncio.to_thread(running_local)
        own = None
        lease = None
        if not attached:
            if inference_busy(PROJECT / 'data'):
                raise RuntimeError('local_model_busy_but_not_found')
            lease = InferenceLease(PROJECT / 'data')
            lease.__enter__()
            own = LocalImageReviewer(out)
            await own.start()
            attached = (own.url, own.client.headers['Authorization'][7:])
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=300, headers={'Authorization': 'Bearer ' + attached[1]}) as client:
                for row in rows:
                    if row.get('local', {}).get('status') == 'recognized' if row.get('local') else False:
                        continue
                    cached = PROJECT / 'data/.image-subject/content' / (version + '_' + row['sha256'] + '.json')
                    prediction = json.loads(cached.read_text(encoding='utf-8')) if cached.exists() else {}
                    if valid_prediction(prediction):
                        row['local'] = {**prediction, 'status': 'recognized', 'suggestion': image_suggestion(prediction), 'cache_used': True}
                    else:
                        data, size = await asyncio.to_thread(encode_image, row['path'])
                        row['local'] = {**await request_prediction(client, attached[0], data, False), 'input_size': size, 'cache_used': False,
                                        'shared_with_production_queue': own is None}
                    save(row)
                    print('local', row['index'], row['local'].get('label') or row['local'].get('error'), flush=True)
        finally:
            if own:
                await own.close()
            if lease:
                lease.__exit__(None, None, None)
    async with httpx.AsyncClient(trust_env=False, timeout=180, headers={'Authorization': 'Bearer ' + key}) as client:
        # Verify credential/model/image capability before queuing the other 49.
        await cloud_one(client, rows[0])
        if rows[0]['cloud']['status'] != 'recognized':
            raise RuntimeError('first_cloud_image_failed')
        await asyncio.gather(local_all(), *(cloud_one(client, row) for row in rows[1:]))
    valid = [r for r in rows if r['local'].get('status') == r['cloud'].get('status') == 'recognized']
    summary = {'total': 50, 'paired_success': len(valid), 'cloud_success': sum(r['cloud'].get('status') == 'recognized' for r in rows),
        'local_success': sum(r['local'].get('status') == 'recognized' for r in rows),
        'subject_agreement': sum(r['local']['label'] == r['cloud']['label'] for r in valid),
        'type_agreement': sum(r['local']['image_type'] == r['cloud']['image_type'] for r in valid),
        'decision_agreement': sum(r['local']['suggestion'] == r['cloud']['suggestion'] for r in valid),
        'wall_seconds': round(time.perf_counter() - started, 2),
        'note': 'No human ground truth: agreement is not an accuracy score. Some local timings include production queue wait; others use an isolated service.'}
    for provider in ('cloud', 'local'):
        results = [r[provider] for r in rows if r[provider].get('status') == 'recognized']
        timings = [p['elapsed_seconds'] for p in results if not p.get('cache_used') and 'elapsed_seconds' in p]
        summary[provider] = {'subjects': dict(Counter(p['label'] for p in results)), 'types': dict(Counter(p['image_type'] for p in results)),
            'decisions': dict(Counter(p.get('suggestion') or 'manual_review' for p in results)), 'timed_images': len(timings),
            'mean_seconds': round(statistics.mean(timings), 2) if timings else None,
            'median_seconds': round(statistics.median(timings), 2) if timings else None,
            'total_tokens': sum((p.get('usage') or {}).get('total_tokens', 0) for p in results)}
        if provider == 'local':
            isolated = [p['elapsed_seconds'] for p in results if not p.get('cache_used') and not p.get('shared_with_production_queue')]
            shared = [p['elapsed_seconds'] for p in results if not p.get('cache_used') and p.get('shared_with_production_queue')]
            summary[provider].update(isolated_count=len(isolated), shared_count=len(shared),
                isolated_mean_seconds=round(statistics.mean(isolated), 2) if isolated else None,
                shared_mean_seconds=round(statistics.mean(shared), 2) if shared else None)
    report_rows = [{k: row[k] for k in ('index', 'filename', 'sha256', 'source', 'cloud', 'local', 'historical')} for row in rows]
    atomic_json(out / 'report.json', {'summary': summary, 'rows': report_rows})
    (out / 'report-data.js').write_text('window.REPORT = ' + json.dumps({'summary': summary, 'rows': report_rows}, ensure_ascii=False).replace('</', '<\\/') + ';', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Plain pipe input is not echoed and the key never appears in a process argument.
    key = (getpass.getpass('API key (hidden): ') if sys.stdin.isatty() else sys.stdin.readline()).strip()
    if not key:
        raise SystemExit('API key missing on stdin')
    try:
        asyncio.run(run(args, key))
    except Exception as exc:
        # Avoid accidentally logging request headers or credential-bearing objects.
        print('Comparison failed:', type(exc).__name__, flush=True)
        raise SystemExit(1)

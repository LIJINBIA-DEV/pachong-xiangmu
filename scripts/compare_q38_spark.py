"""Append the resident Spark Q8 model to the immutable Jev-passed comparison."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import time

import httpx
import compare_cute_models as base

SOURCE = base.PROJECT / 'artifacts/model-compare-jev-passed-100-20261019'
OUTPUT = base.PROJECT / 'artifacts/model-compare-q38-spark-100-20261019'
ENDPOINT = 'http://192.168.30.168:18638/v1/chat/completions'
KEY = 'q38local'
base.OUT = OUTPUT
base.MODELS[KEY] = {'name': 'Qwen3.8-27B · 本地 Q8', 'id': 'qwen3.8-27b',
                    'provider': 'Spark · Q8_0 + BF16 视觉投影 · 本次新跑'}


def hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def prepare():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if not (OUTPUT / 'source-before.json').exists():
        base.write_json(OUTPUT / 'source-before.json', hashes(SOURCE))
    for name in ['samples.json', 'images', 'q35', 'q38', 'q36']:
        src, dst = SOURCE / name, OUTPUT / name
        if not dst.exists():
            shutil.copytree(src, dst) if src.is_dir() else shutil.copyfile(src, dst)
    if not (OUTPUT / 'selection-manifest.json').exists():
        manifest = json.loads((SOURCE / 'selection-manifest.json').read_text(encoding='utf-8'))
        previous_key = manifest['annotation_storage_key']
        manifest.update(batch_id=OUTPUT.name, annotation_storage_key='cute-model-compare-v1-' + OUTPUT.name,
                        annotation_legacy_keys=[previous_key, *manifest['annotation_legacy_keys']],
                        models=list(base.MODELS), comparison_source=SOURCE.name,
                        added_model=KEY, rerun_images=100, rerun_posts=18)
        base.write_json(OUTPUT / 'selection-manifest.json', manifest)


class LocalClient:
    def __init__(self, unused):
        self.http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(240, connect=15))
        self.lock = asyncio.Lock()

    async def request(self, model, system, content):
        assert model == KEY, 'Only the newly deployed model may be called'
        body = {'model': base.MODELS[KEY]['id'], 'messages': [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
            'temperature': 0, 'max_tokens': 1400, 'stream': False,
            'response_format': {'type': 'json_object'},
            'chat_template_kwargs': {'enable_thinking': False}, 'reasoning_budget': 0}
        queued = time.monotonic()
        async with self.lock:
            started = time.monotonic()
            for attempt in range(3):
                try:
                    response = await self.http.post(ENDPOINT, json=body)
                    response.raise_for_status()
                    raw = response.json()
                    choice = raw['choices'][0]
                    message = choice['message']
                    answer = message.get('content') or ''
                    reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
                    result = {'status': 'recognized', 'raw_output': answer,
                              'served_model': raw.get('model'), 'usage': raw.get('usage'),
                              'seconds': round(time.monotonic() - started, 2),
                              'queue_seconds': round(started - queued, 2),
                              'attempts': attempt + 1, 'thinking_requested': False,
                              'reasoning_chars': len(reasoning), 'finish_reason': choice.get('finish_reason'),
                              'endpoint': ENDPOINT}
                    if reasoning or '<think>' in answer:
                        result['thinking_warning'] = '接口返回了思考内容，请核对'
                    try:
                        result['parsed'] = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', answer.strip()))
                    except ValueError:
                        result.update(status='error', error='invalid_json')
                    return result
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    if attempt == 2 or isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                        return {'status': 'error', 'error': type(exc).__name__,
                                'seconds': round(time.monotonic() - started, 2), 'attempts': attempt + 1}
                    await asyncio.sleep(5 * (attempt + 1))


def render():
    # Reuse the exact decision and annotation implementation of the prior report.
    path = base.PROJECT / 'scripts/render_cute_model_compare.py'
    code = path.read_text(encoding='utf-8')
    code = code.replace('三模型', '四模型').replace('三个模型', '四个模型').replace('三个结果', '四个结果')
    code = code.replace('max-width:1660px', 'max-width:2200px')
    code = code.replace('repeat(3,minmax(0,1fr))', 'repeat(4,minmax(0,1fr))')
    code = code.replace('repeat(3,1fr)', 'repeat(4,1fr)')
    code = code.replace('Spark 使用原有 Q4_K_M 权重，加独立 F16 视觉投影；与云端的精度和服务环境不同，耗时包含网络、排队及重试。',
        '本次只新增 Spark Qwen3.8-27B Q8_0 + BF16 视觉投影；前三列复用历史结果，3.6 为旧 Q4_K_M 版本。图片与提示词相同；量化、运行程序和服务环境不同，不是同一部署精度的对比。新模型耗时含网络及重试，排队时间另存原始记录。')
    code = code.replace('保留旧样本 {manifest[\'retained_images\']} 张，替换 {manifest[\'new_images\']} 张。',
        '沿用上次完整的 18 帖、100 张图片，本次不换样本，只新增本地 3.8 Q8 结果。')
    code = code.replace('模型标签来自本次实际输出与统一判断规则，没有沿用旧模型分类。',
        '新模型为本次实际输出；原来的三列为历史记录，均按同一判断规则展示。')
    code = code.replace("'<div class=\"model\"><h3>'+esc(report.models[model].name)",
                        "'<div class=\"model\" data-variant=\"'+model+'\"><h3>'+esc(report.models[model].name)")
    code = code.replace("'<div class=\"model\"><div class=\"model-head\">'",
                        "'<div class=\"model\" data-variant=\"'+model+'\"><div class=\"model-head\">'")
    # imagePanel has additional markup in the same literal.
    code = code.replace("'<div class=\"model\"><div class=\"model-head\"><b>'",
                        "'<div class=\"model\" data-variant=\"'+model+'\"><div class=\"model-head\"><b>'")
    code = code.replace("'<div class=\"metric\"><b>'+esc(report.models[s.key].name)",
                        "'<div class=\"metric\" data-variant=\"'+s.key+'\"><b>'+esc(report.models[s.key].name)")
    code = code.replace('<div class="toolbar">', '<div class="toolbar"><button id="pair-view" aria-pressed="false">只看 3.8 云端 / 本地</button>')
    code = code.replace('</style>', '.pair-view [data-variant="q35"],.pair-view [data-variant="q36"]{display:none}.pair-view .models,.pair-view .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}@media(max-width:850px){.pair-view .models,.pair-view .metrics{grid-template-columns:1fr}}</style>')
    code = code.replace("filterMode='all';", "filterMode='all',pairMode=false;function activeKeys(){return pairMode?['q38','q38local']:keys}")
    code = code.replace('const records=keys.map(k=>im.models[k])', 'const records=activeKeys().map(k=>im.models[k])')
    code = code.replace('new Set(keys.map(k=>', 'new Set(activeKeys().map(k=>')
    code = code.replace("document.getElementById('export').addEventListener", "document.getElementById('pair-view').addEventListener('click',()=>{const on=document.body.classList.toggle('pair-view');pairMode=on;document.getElementById('pair-view').setAttribute('aria-pressed',String(on));document.getElementById('pair-view').textContent=on?'显示全部四个模型':'只看 3.8 云端 / 本地';refresh()});\ndocument.getElementById('export').addEventListener")
    code = code.replace('encoded=json.dumps(payload', "if (OUT/'run-configuration.json').exists():payload['method']['local_run']=json.loads((OUT/'run-configuration.json').read_text(encoding='utf-8'))\nencoded=json.dumps(payload")
    exec(compile(code, str(path), 'exec'), {'__name__': '__main__'})
    checkfile = OUTPUT / 'comparison-verification.json'
    if checkfile.exists():
        checks = json.loads(checkfile.read_text(encoding='utf-8'))
        differences = checks.get('cloud_local_image_decision_differences')
        if differences is not None:
            report = json.loads((OUTPUT / 'results.json').read_text(encoding='utf-8'))
            links = []
            for image_id in differences:
                idx = next(i for i,p in enumerate(report['posts']) if p['note_id'] == image_id.split('/')[0])
                links.append(f'<a href="#p{idx}">查看样本 {idx+1} 的分歧图片 {image_id.split("/")[-1]}</a>')
            summary = ('<div class="notice"><b>本次本地 Q8 已完成：18 帖 / 100 张，失败 0，思考输出 0。</b>'
                       f'<br>与历史云端 3.8 的最终图片结论相同 {100-len(differences)} 张、不同 {len(differences)} 张。'
                       f'本地单图请求中位数 {checks["image_request_median_seconds"]} 秒。'
                       '<br>这是一致度，不是人工准确率；主体名称、分类和理由仍可能不同。'
                       '建议点击“只看 3.8 云端 / 本地”，再筛选“图片结论不同”。<br>' + ' · '.join(links) + '</div>')
            path = OUTPUT / 'index.html'
            document = path.read_text(encoding='utf-8').replace('<div class="metrics" id="metrics">', summary + '<div class="metrics" id="metrics">')
            path.write_text(document, encoding='utf-8')


def audit():
    before = json.loads((OUTPUT / 'source-before.json').read_text(encoding='utf-8'))
    current = hashes(SOURCE)
    assert before == current, 'Prior report changed'
    for name in ['q35', 'q38', 'q36', 'images']:
        assert hashes(SOURCE / name) == hashes(OUTPUT / name), name
    samples = json.loads((OUTPUT / 'samples.json').read_text(encoding='utf-8'))
    assert samples == json.loads((SOURCE / 'samples.json').read_text(encoding='utf-8'))
    assert len(samples) == 18 and sum(len(p['images']) for p in samples) == 100
    assert all(p.get('jev_pass', {}).get('choice') == 'keep' for p in samples)
    records = [json.loads(p.read_text(encoding='utf-8')) for p in (OUTPUT / KEY).glob('*/*.json')]
    result = {'same_18_posts_and_100_images': True, 'previous_report_unchanged': True,
              'historical_model_outputs_unchanged': True, 'new_model_records': len(records),
              'recognized': sum(r['status'] == 'recognized' for r in records),
              'errors': sum(r['status'] == 'error' for r in records),
              'thinking_warnings': sum(bool(r.get('thinking_warning')) for r in records),
              'finish_reasons': sorted(set(str(r.get('finish_reason')) for r in records))}
    assert len(records) == 118
    report = json.loads((OUTPUT / 'results.json').read_text(encoding='utf-8'))
    images = [im for post in report['posts'] for im in post['images']]
    local_images = [im['models'][KEY] for im in images]
    result['image_request_median_seconds'] = round(statistics.median(r['seconds'] for r in local_images), 2)
    result['image_request_mean_seconds'] = round(statistics.mean(r['seconds'] for r in local_images), 2)
    result['image_request_range_seconds'] = [min(r['seconds'] for r in local_images), max(r['seconds'] for r in local_images)]
    result['cloud_local_image_decision_differences'] = [im['id'] for im in images if im['models']['q38'].get('image_outcome') != im['models'][KEY].get('image_outcome')]
    result['cloud_local_overall_decision_differences'] = [im['id'] for im in images if im['models']['q38'].get('outcome') != im['models'][KEY].get('outcome')]
    result['cloud_local_text_target_differences'] = [post['note_id'] for post in report['posts'] if
        sorted((t['name'],t['kind']) for t in post['text_models']['q38'].get('validated',{}).get('targets',[])) !=
        sorted((t['name'],t['kind']) for t in post['text_models'][KEY].get('validated',{}).get('targets',[]))]
    result['difference_is_not_accuracy'] = True
    base.write_json(OUTPUT / 'comparison-verification.json', result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run', 'render', 'audit'])
    action = parser.parse_args().action
    if action == 'prepare': prepare(); render()
    elif action == 'run':
        base.Client = LocalClient
        base.runtime_settings = lambda _: {'api_key': ''}
        asyncio.run(base.run([KEY]))
        render()
        audit()
    elif action == 'render': render()
    elif action == 'audit': audit()

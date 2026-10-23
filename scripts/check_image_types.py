"""Rerun an explicit, catalog-bound sample with production inference and HTML evidence."""
import argparse
import asyncio
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from image_subject import recognize_files, image_catalog, cache_path, cached_prediction
from collection_tasks import atomic_json


def human_marks(state):
    # Include explicit resets and legacy human entries, plus all account/post edits.
    posts = {}
    for key, value in state.get('posts', {}).items():
        marks = {name: decision for name, decision in value.get('images', {}).items()
                 if value.get('image_sources', {}).get(name) != 'model'}
        posts[key] = {'images': marks, 'post_decision': value.get('post_decision'),
                      'post_decision_source': value.get('post_decision_source')}
    return {'accounts': state.get('accounts', {}), 'posts': posts}


async def check(args):
    root = PROJECT / 'data'
    file = (root / args.file).resolve()
    samples = json.loads(args.manifest.read_text(encoding='utf-8'))
    paths = [Path(row['path']).resolve() for row in samples]
    catalog, _ = image_catalog(root, [file])
    if not {str(p) for p in paths}.issubset(catalog):
        raise ValueError('Sample paths must belong to the selected collection')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    backup = out / 'backup'
    backup.mkdir(exist_ok=True)
    human_before = {}
    for source in root.glob('.manual-review/*.json'):
        shutil.copy2(source, backup / source.name)
        human_before[source.name] = human_marks(json.loads(source.read_text(encoding='utf-8')))
    for path in paths:
        cache = cache_path(root, path)
        if cache.exists():
            shutil.copy2(cache, backup / ('cache-' + cache.name))
    original = hashlib.sha256(file.read_bytes()).hexdigest()
    result = await recognize_files(root, [file], image_paths=paths)
    rows = []
    for i, sample in enumerate(samples):
        path = paths[i]
        prediction = cached_prediction(root, catalog[str(path)])
        destination = out / 'images' / f'{i:02d}{path.suffix}'
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(path, destination)
        rows.append({**sample, 'prediction': prediction, 'preview': destination.relative_to(out).as_posix()})
    human_after = {source.name: human_marks(json.loads(source.read_text(encoding='utf-8')))
                   for source in root.glob('.manual-review/*.json')}
    # Model synchronization may add empty post records, which are not human edits.
    unchanged = all(after['accounts'] == human_before[name]['accounts'] and
                    all(after['posts'].get(key) == marks for key, marks in human_before[name]['posts'].items())
                    for name, after in human_after.items() if name in human_before)
    file_unchanged = original == hashlib.sha256(file.read_bytes()).hexdigest()
    assert unchanged and file_unchanged, 'Human marks and collection must remain unchanged'
    summary = {'inference': result, 'types': dict(Counter(row['prediction'].get('image_type') for row in rows)),
               'suggestions': dict(Counter(row['prediction'].get('suggestion') or 'manual_review' for row in rows)),
               'human_marks_unchanged': unchanged, 'source_file_unchanged': file_unchanged,
               'file': args.file, 'rows': rows}
    atomic_json(out / 'report.json', summary)
    cards = []
    decisions = {'qualified': '模型建议：合格', 'unqualified': '模型建议：不合格', None: '留给人工审核'}
    for i, row in enumerate(rows):
        p = row['prediction']; esc = lambda text: html.escape(str(text or ''))
        cards.append(f'''<article><a href="{row['preview']}" target="_blank"><img src="{row['preview']}" alt="样本 {i+1}"></a>
        <div class="body"><b>{i+1}. {esc(p.get('image_type') or p.get('status'))}</b>
        <span class="{esc(p.get('suggestion') or 'pending')}">{decisions[p.get('suggestion')]}</span>
        <p>主体：{esc(p.get('label'))}</p><p>{esc(p.get('type_reason'))}</p><p>{esc(p.get('reason'))}</p>
        <details><summary>来源与原判断</summary><p>{esc(row['path'])}</p><p>原主体：{esc(row.get('label'))}；{esc(row.get('reason'))}</p></details></div></article>''')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Qwen 图片类型抽样复核</title><style>body{margin:0;padding:28px;font:15px/1.6 system-ui;background:#f7f9fb;color:#162234}h1{font-size:25px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}article{background:white;border:1px solid #dee5ed;border-radius:12px;overflow:hidden}img{height:330px;width:100%;object-fit:contain;background:#eff3f7}.body{padding:16px}span{display:inline-block;margin:0 10px;padding:2px 8px;border-radius:6px}.qualified{background:#e8f6e5;color:#368122}.unqualified{background:#ffebeb;color:#bd3434}.pending{background:#fff0ce;color:#8f690e}p{overflow-wrap:anywhere;margin:7px 0}details{font-size:12px;color:#667589}summary{cursor:pointer}</style>
    <h1>Qwen 4B：图片主体与图片类型抽样复核</h1>'''
    page += f'<p>本批抽样 {len(rows)} 张，识别成功 {result["completed"]} 张，失败 {result["failed"]} 张。点击图片可放大。</p>'
    page += '<p>海报、广告设计图、聊天／网页截图自动不合格；类型不确定留给人工。实景中的雕塑、墙绘、装置不按海报排除。以下为模型预测，供人工核对，不代表已测出整体准确率。原采集文件和已有人工标记均已保留。</p>'
    page += '<div class="grid">' + ''.join(cards) + '</div></html>'
    (out / 'index.html').write_text(page, encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default='weibo/weibo_search_20261010_084029_3ac7d632.xlsx')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(check(parser.parse_args()))

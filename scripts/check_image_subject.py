"""Run the production image service on the accepted local 50-image sample."""
import argparse
import asyncio
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from image_subject import recognize_files, image_suggestion
from api.services.manual_review import annotations, update_annotation, storage_path
from collection_tasks import atomic_json
from api.services.image_subject import image_subject_jobs


async def check(output):
    sample = PROJECT.parent / 'model'
    sources = list(csv.DictReader((sample / '准备记录/50张图片来源.csv').open(encoding='utf-8-sig')))
    output.mkdir(parents=True, exist_ok=True)
    collection = output / 'weibo/qwen_image_subject_50.json'
    notes = []
    for row in sources:
        folder = output / 'wb/media' / row['post_id']
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / row['filename']
        if not target.exists():
            shutil.copy2(sample / '50张图片' / row['filename'], target)
        notes.append({'note_id': row['post_id'], 'image_names': row['filename'], 'source_keyword': '可爱 公园', 'note_url': row['post_url'], 'nickname': '本地回归样本账号（示例）', 'content': '本地图片识别回归样本，仅用于检查图片结果；此处不是原帖正文。', 'semantic_result': 'matched'})
    collection.parent.mkdir(parents=True, exist_ok=True)
    collection.write_text(json.dumps(notes, ensure_ascii=False), encoding='utf-8')
    first = sources[0]
    key = first['post_id'] + ':可爱 公园'
    # Keep an intentionally contrary HUMAN label to verify precedence.
    update_annotation(output, collection, key, 'image', 'qualified', first['filename'])
    human_before = json.loads(storage_path(output, collection).read_text(encoding='utf-8'))['posts'][key]
    started = time.perf_counter()
    def progress(state):
        atomic_json(image_subject_jobs.state_path(output, collection), state)
    result = await recognize_files(output, [collection], progress)
    assert result['completed'] == result['total'] == 50 and result['failed'] == 0
    human_after = json.loads(storage_path(output, collection).read_text(encoding='utf-8'))['posts'][key]
    assert human_after == human_before
    entries = annotations(output, collection)['entries']
    assert entries[key]['images'][first['filename']] == 'qualified'
    counts = Counter(image['subject']['label'] for entry in entries.values() for image in entry['review_images'])
    auto_checks = Counter()
    for entry in entries.values():
        for image in entry['review_images']:
            if image.get('decision_source') == 'model':
                expected = image_suggestion(image['subject'])
                if expected is None:
                    assert image['key'] not in entry['images']
                    continue
                assert entry['images'][image['key']] == expected
                auto_checks[expected] += 1
    assert sum(auto_checks.values()) <= 49  # Uncertain types remain unchecked.
    resumed = await recognize_files(output, [collection])
    assert resumed['cached'] == 50
    previous = list(csv.DictReader((sample / '图片主体识别结果.csv').open(encoding='utf-8-sig')))
    labels = {image['name']: image['subject']['label'] for entry in entries.values() for image in entry['review_images']}
    differences = [{'filename': row['filename'], 'before': row['label'], 'after': labels[row['filename']]} for row in previous if labels[row['filename']] != row['label']]
    report = {'passed': True, 'counts': dict(counts), 'automatic_checks': dict(auto_checks), 'failed': 0, 'elapsed_seconds': round(time.perf_counter() - started, 2), 'cache_resume': resumed['cached'], 'human_annotation_unchanged': True, 'difference_from_original_experiment': differences}
    atomic_json(output.parent / 'acceptance.json', report)
    print(json.dumps(report, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=PROJECT / 'artifacts/image-subject-20261009/data')
    parser.add_argument('--serve', type=int)
    args = parser.parse_args()
    asyncio.run(check(args.output.resolve()))
    if args.serve:
        import config
        config.SAVE_DATA_PATH = str(args.output.resolve())
        import uvicorn
        uvicorn.run('api.main:app', host='127.0.0.1', port=args.serve)


if __name__ == '__main__':
    main()

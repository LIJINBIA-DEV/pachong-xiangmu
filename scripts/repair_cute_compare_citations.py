"""Revalidate captured text and replay only changed visual inputs; production is read-only."""
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from compare_cute_models import (OUT, PROJECT, MODELS, Client, validate_text, vision_targets,
                                 decision, VISION_PROMPT, protected_files, write_json,
                                 local_image_path, encode_image, runtime_settings)

REPAIR = OUT / 'citation-repair-v2'


async def main():
    assert OUT.is_relative_to(PROJECT / 'artifacts')
    REPAIR.mkdir(exist_ok=True)
    samples = json.loads((OUT / 'samples.json').read_text(encoding='utf-8'))
    before = protected_files(PROJECT / 'data', samples)
    before_path = REPAIR / 'production-before.json'
    if not before_path.exists():
        write_json(before_path, before)
    for name in ('index.html', 'results.json', 'verification.json'):
        if not (REPAIR / name).exists():
            shutil.copyfile(OUT / name, REPAIR / name)
    jobs = []
    text_log = []
    for model in MODELS:
        for post in samples:
            folder = OUT / model / post['note_id']
            text_path = folder / 'text.json'
            saved = REPAIR / model / post['note_id']
            saved.mkdir(parents=True, exist_ok=True)
            if not (saved / 'text.json').exists():
                shutil.copyfile(text_path, saved / 'text.json')
            baseline = json.loads((saved / 'text.json').read_text(encoding='utf-8'))
            current = json.loads(text_path.read_text(encoding='utf-8'))
            assert current['raw_output'] == baseline['raw_output']
            value = validate_text(current['parsed'], post['content'])
            previous_targets = vision_targets(baseline['validated'])
            current['validated'] = value
            write_json(text_path, current)
            text_log.append({'model': model, 'note_id': post['note_id'],
                             'raw_output_sha256': hashlib.sha256(current['raw_output'].encode()).hexdigest(),
                             'before_targets': previous_targets, 'after_targets': vision_targets(value),
                             'citation_states': [t['citation']['status'] for t in value['targets']]})
            if previous_targets == vision_targets(value):
                continue
            for image in post['images']:
                dest = folder / (image['name'] + '.json')
                old_path = saved / dest.name
                if not old_path.exists():
                    shutil.copyfile(dest, old_path)
                old = json.loads(dest.read_text(encoding='utf-8'))
                if old.get('requested_targets') == vision_targets(value) and old.get('citation_replay'):
                    continue
                jobs.append((model, post, image, value, dest))
    write_json(REPAIR / 'plan.json', {'text_revalidation': text_log,
               'replay_count': len(jobs), 'replay': [{'model': m, 'note_id': p['note_id'], 'image': i['name']}
                                                     for m, p, i, _, _ in jobs]})
    print(json.dumps({'replay_count': len(jobs)}, ensure_ascii=False), flush=True)
    client = Client(runtime_settings(PROJECT / 'data')['api_key'])
    async def replay(job):
        model, post, image, value, dest = job
        data, size = await asyncio.to_thread(encode_image, local_image_path(PROJECT / 'data', image))
        targets = vision_targets(value)
        content = [{'type': 'text', 'text': json.dumps({'targets': targets}, ensure_ascii=False)},
                   {'type': 'image_url', 'image_url': {'url': data}}]
        result = await client.request(model, VISION_PROMPT, content)
        result.update(input_size=size, requested_targets=targets,
                      text_validation_version=value['validation_version'],
                      citation_replay={'at': datetime.now().isoformat(),
                                       'original_record': str(dest.relative_to(OUT)),
                                       'archive': 'citation-repair-v2/' + str(dest.relative_to(OUT))})
        assert result['status'] == 'recognized', 'Replay failed; original record preserved'
        result.update(decision(value, result['parsed']))
        assert result['reasoning_chars'] == 0
        write_json(dest, result)
        print(json.dumps({'model': model, 'note': post['note_id'], 'image': image['name'],
                          'outcome': result['outcome']}, ensure_ascii=False), flush=True)
    try:
        # Separate model workers allow cloud work while Spark runs its single request queue.
        async def worker(model):
            for job in jobs:
                if job[0] == model:
                    await replay(job)
        await asyncio.gather(*(worker(m) for m in MODELS))
    finally:
        await client.http.aclose()
        after = protected_files(PROJECT / 'data', samples)
        initial = json.loads(before_path.read_text(encoding='utf-8'))
        write_json(REPAIR / 'production-after.json', after)
        audit = {'unchanged': initial == after,
                 'changed_paths': [p for p in set(initial) | set(after) if initial.get(p) != after.get(p)]}
        write_json(OUT / 'audit-citation-repair-v2.json', audit)
        assert audit['unchanged'], 'Protected production data changed; inspect audit'


if __name__ == '__main__':
    asyncio.run(main())

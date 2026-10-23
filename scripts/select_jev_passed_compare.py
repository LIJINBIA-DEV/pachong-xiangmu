"""Select a reproducible comparison batch from verified historical Jev passes only.

Read-only toward production data. A matched candidate is NOT proof of a Jev pass.
The previous report remains intact; compatible inference records can be reused.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys

import openpyxl
from PIL import Image, ImageOps

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from image_subject import local_image_path

OLD = PROJECT / 'artifacts/model-compare-100-20261013'
DEFAULT_OUT = PROJECT / 'artifacts/model-compare-jev-passed-100-20261019'
CHECKPOINT = PROJECT / 'data/weibo/semantic_checkpoint_5c1cd0488b5b.jsonl'
WORKBOOK = PROJECT / 'data/weibo/weibo_search_20261010_084029_3ac7d632.xlsx'


def passed(state, row):
    """Fail closed on uncertainty, candidate promotion, missing proof or conflicts."""
    note = state.get('note', {})
    for record, status_key in ((state, 'status'), (row, 'semantic_result')):
        if record.get(status_key) != 'matched' or record.get('quality_reason'):
            return False
    if state.get('matched') is not True or state.get('uncertain') is not False:
        return False
    if note.get('jev_original_choice') != 'keep' or row.get('jev_original_choice') != 'keep':
        return False
    if any(record.get(k) for record in (note, row) for k in
           ('original_semantic_source', 'semantic_rejection_reason', 'author_filter_reason')):
        return False
    if state.get('duplicate_of') or state.get('unavailable_reason'):
        return False
    if state.get('object_type') not in {'park_animal', 'wild_animal', 'scene_animal', 'landscape',
                                      'place', 'decoration', 'building', 'facility', 'exhibit'}:
        return False
    if state.get('target_relation') not in {'scene_component', 'target_itself'}:
        return False
    for key in ('confidence', 'verification_confidence'):
        value = state.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.7 <= value <= 1:
            return False
    return all(state.get(k) for k in ('evidence_text', 'target_evidence_text'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def build(out):
    from compare_cute_models import TEXT_PROMPT, VISION_PROMPT
    prior_report = json.loads((OLD/'results.json').read_text(encoding='utf-8'))
    prior_method = prior_report['method']
    compatible = (prior_method['text_prompt'] == TEXT_PROMPT and prior_method['vision_prompt'] == VISION_PROMPT
                  and prior_method['thinking'] is False and prior_method['temperature'] == 0
                  and prior_method['image_max_edge'] == 1024)
    latest = {}
    for line_number, line in enumerate(CHECKPOINT.read_text(encoding='utf-8').splitlines(), 1):
        state = json.loads(line)
        note = state['note']
        latest[(str(note['note_id']), note.get('source_keyword'))] = (line_number, state)
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    rows = workbook['Contents'].iter_rows(values_only=True)
    headers = next(rows)
    notes = {}
    for row_number, values in enumerate(rows, 2):
        row = dict(zip(headers, values))
        notes[(str(row['note_id']), row.get('source_keyword'))] = (row_number, row)
    workbook.close()
    inventory = json.loads((PROJECT / 'artifacts/text-image-match-20261012/local-inventory.json').read_text(encoding='utf-8'))['posts']
    eligible = {}
    rejected = Counter()
    for post in inventory:
        key = (post['note_id'], post['keyword'])
        cp = latest.get(key)
        saved = notes.get(key)
        if not cp or not saved or not passed(cp[1], saved[1]):
            rejected['not_verified_jev_pass'] += 1
            continue
        line, state = cp
        row_number, row = saved
        if post['content'] != row['content'] or post['content'] != state['note']['content']:
            rejected['content_changed'] += 1
            continue
        # This comparison extracts the cute target from BODY, not comments.
        if state['source'] != 'note' or state['evidence_source'] != 'content' or state['target_evidence_source'] != 'content':
            rejected['comment_based_pass_outside_body_trial'] += 1
            continue
        if state['evidence_text'] not in post['content'] or state['target_evidence_text'] not in post['content']:
            rejected['source_evidence_mismatch'] += 1
            continue
        proof = {'choice': 'keep', 'result': 'matched', 'source': 'content',
                 'checkpoint': str(CHECKPOINT.relative_to(PROJECT)), 'checkpoint_line': line,
                 'workbook': str(WORKBOOK.relative_to(PROJECT)), 'sheet': 'Contents', 'row': row_number,
                 'confidence': state['confidence'], 'verification_confidence': state['verification_confidence'],
                 'quality_reason': state['quality_reason'], 'object_type': state['object_type'],
                 'target_relation': state['target_relation'], 'evidence': state['evidence_text'],
                 'target_evidence': state['target_evidence_text'], 'rule_version': state['rule_version']}
        eligible[post['note_id']] = {**post, 'jev_pass': proof}
    old = json.loads((OLD / 'samples.json').read_text(encoding='utf-8'))
    selected, used_hashes, seen_posts = [], set(), set()
    retained = 0
    def choose(post, candidates, limit):
        if limit <= 0:
            return 0
        images = []
        for im in candidates:
            source = local_image_path(PROJECT / 'data', im)
            if source is None or not source.is_file():
                continue
            digest = sha(source)
            if digest in used_hashes:
                continue
            used_hashes.add(digest)
            images.append({**im, 'source_sha256': digest})
            if len(images) == limit:
                break
        if images:
            selected.append({**post, 'images': images})
            seen_posts.add(post['note_id'])
        return len(images)
    for prior in old:
        current = eligible.get(prior['note_id'])
        if current and current['content'] == prior['content'] and current['keyword'] == prior['keyword']:
            retained += choose(current, prior['images'], min(len(prior['images']), 100 - retained))
            if retained == 100:
                break
    pool = [p for p in eligible.values() if p['note_id'] not in seen_posts]
    random.Random(20261019).shuffle(pool)
    count = retained
    for post in pool:
        if count == 100:
            break
        candidates = list(post['images'])
        random.Random(20261019 + int(post['note_id'][-6:])).shuffle(candidates)
        count += choose(post, candidates, min(8, 100 - count))
        if count == 100:
            break
    if count != 100:
        raise ValueError(f'Only {count} eligible unique images; refusing to relax Jev gate')
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'samples.json').exists():
        assert json.loads((out / 'samples.json').read_text(encoding='utf-8')) == selected, 'Existing batch differs; preserve it'
    manifest = {'batch_id': out.name, 'jev_passed_only': True, 'total_posts': len(selected), 'total_images': count,
                'retained_images': retained, 'new_images': count-retained, 'eligible_posts': len(eligible),
                'excluded_inventory_posts': dict(rejected), 'seed': 20261019,
                'sampling': '正文 Jev 原始 keep + matched + 无校验问题 + 两次置信度均至少0.7；排除候选升级、review、reject、缺失或冲突。先保留符合条件的旧样本，再固定种子抽取新帖子，每个新帖最多8张，全批原图SHA256去重；不按Qwen结果挑选。',
                'source_hashes': {str(p.relative_to(PROJECT)): sha(p) for p in (CHECKPOINT, WORKBOOK)},
                'replaced_old_posts': [p['note_id'] for p in old if p['note_id'] not in seen_posts],
                'annotation_storage_key': 'cute-model-compare-v1-'+out.name,
                'annotation_legacy_keys': ['cute-model-compare-v1-20261013'],
                'models': ['q35','q38','q36'],
                'cache_reuse': {'compatible_prompts_and_settings': compatible,
                               'prior_report_sha256': sha(OLD/'results.json'),
                               'text_prompt_sha256': hashlib.sha256(TEXT_PROMPT.encode()).hexdigest(),
                               'vision_prompt_sha256': hashlib.sha256(VISION_PROMPT.encode()).hexdigest()},
                'note': '历史Jev通过是抽样条件，不是人工真值，不代表每张配图合格。旧报告完整保留。'}
    write(out / 'samples.json', selected)
    write(out / 'selection-manifest.json', manifest)
    # Preserve only records with identical post input and selected image identity.
    old_by_id = {p['note_id']: p for p in old}
    reused = Counter()
    for post in selected:
        previous = old_by_id.get(post['note_id'])
        if compatible and previous and (previous['content'], previous['keyword']) == (post['content'], post['keyword']):
            previous_images = {im['name']: im for im in previous['images']}
            for model in ('q35','q38','q36'):
                folder = out / model / post['note_id']
                folder.mkdir(parents=True, exist_ok=True)
                for name in ['text.json'] + [im['name']+'.json' for im in post['images'] if im['name'] in previous_images]:
                    src = OLD / model / post['note_id'] / name
                    if src.exists() and not (folder / name).exists():
                        shutil.copyfile(src, folder / name)
                        reused[model] += 1
        for im in post['images']:
            dest = out / 'images' / post['note_id'] / im['name']
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(local_image_path(PROJECT / 'data', im)) as picture:
                picture = ImageOps.exif_transpose(picture).convert('RGB')
                picture.thumbnail((1280,1280))
                picture.save(dest, 'JPEG', quality=90)
    print(json.dumps({**{k:manifest[k] for k in ('total_posts','total_images','retained_images','new_images','eligible_posts')}, 'reused_records':dict(reused)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    build(parser.parse_args().out.resolve())

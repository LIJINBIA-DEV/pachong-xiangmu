"""Create a private offline annotation page from actual saved Jev decisions."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
from urllib.parse import urlsplit

MODEL_CHOICES = {'keep', 'reject', 'review'}
TEXT_SOURCES = {'note', 'comment', 'model_review', 'semantic_reject', 'pet_not_allowed',
                'comments_unavailable', 'comment_budget_exhausted', 'keyword_miss',
                'review_candidate_accepted', 'body_match'}

def source_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_latest(path):
    latest = {}
    with path.open(encoding='utf-8-sig') as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            note = row.get('note') or {}
            if note.get('note_id') and note.get('source_keyword'):
                latest[(str(note['note_id']), str(note['source_keyword']))] = (row, number)
    return latest

def plain(value):
    return '' if value is None else str(value)

def prepare_row(row, line):
    note = row['note']
    choice = note.get('jev_original_choice')
    pair = plain(note.get('source_keyword')).split(maxsplit=1)
    if choice not in MODEL_CHOICES or len(pair) != 2 or row.get('status') not in {'matched','review','excluded'}:
        return None
    if row.get('source') not in TEXT_SOURCES:
        return None
    note_id = plain(note['note_id'])
    texts = [(name, plain(note.get(name))) for name in ('content','desc','full_text','title')]
    body = next((value for _, value in texts if value.strip()), '')
    extra, seen = [], {body}
    for name, value in texts:
        if value.strip() and value not in seen:
            seen.add(value)
            extra.append({'label': {'desc':'保存的描述','title':'保存的标题','full_text':'保存的全文','content':'保存的正文'}[name], 'text':value})
    comments, comments_seen = [], set()
    raw_comments = list(row.get('comments') or [])
    if isinstance(row.get('matched_comment'), dict):
        raw_comments.append(row['matched_comment'])
    for comment in raw_comments:
        content = plain(comment.get('content')).strip()
        cid = plain(comment.get('comment_id'))
        signature = (cid,content)
        if content and signature not in comments_seen:
            comments_seen.add(signature)
            comments.append({'id':cid,'author':plain(comment.get('nickname')),'content':content})
    # The page links to a clean public URL, never a saved user_token/Cookie URL.
    url = f'https://m.weibo.cn/detail/{note_id}' if note_id.isdigit() else ''
    choice_by_status = {'matched':'keep','excluded':'reject','review':'review'}
    identity = hashlib.sha256((note_id+'\n'+plain(note['source_keyword'])).encode()).hexdigest()[:20]
    full_flag = note.get('full_text_available')
    return {'id':identity,'noteId':note_id,'keywords':pair,'title':plain(note.get('title')),
        'content':body,'extraText':extra,'nickname':plain(note.get('nickname')),
        'published':plain(note.get('create_date_time') or note.get('create_time')),
        'url':url,'comments':comments,
        'fullTextStatus':'已取得' if full_flag is True else '未取得' if full_flag is False else '记录未注明',
        'modelChoice':choice,'pipelineChoice':choice_by_status[row['status']],
        'source':plain(row.get('source')),'ruleVersion':plain(row.get('rule_version')),
        'originalObject':plain(note.get('jev_original_object_type')),
        'objectType':plain(row.get('object_type')),'targetRelation':plain(row.get('target_relation')),
        'confidence':row.get('confidence'),'evidence':plain(row.get('evidence_text')),
        'targetEvidence':plain(row.get('target_evidence_text')),
        'reason':plain(row.get('quality_reason') or row.get('rejection_reason')),'checkpointLine':line}

def build(checkpoint, output, count=100, seed=20261012):
    if count != 100:
        raise ValueError('This page is designed for exactly 100 posts.')
    original_hash = source_sha(checkpoint)
    records = read_latest(checkpoint)
    candidates = [item for row,line in records.values() if (item := prepare_row(row,line))]
    versions = Counter(item['ruleVersion'] for item in candidates)
    eligible_versions = [v for v,n in versions.items() if n >= count]
    if not eligible_versions:
        raise ValueError('Fewer than 100 actual Jev decisions in any one rule version; do not fabricate judgments.')
    version = max(eligible_versions, key=lambda v:int(v.rsplit('v',1)[-1]) if v.rsplit('v',1)[-1].isdigit() else 0)
    rng = random.Random(seed)
    pool = sorted([item for item in candidates if item['ruleVersion']==version],key=lambda item:item['id'])
    rng.shuffle(pool)
    unique, note_ids, body_signatures = [], set(), set()
    for item in pool:
        content = ''.join(item['content'].split())
        if item['noteId'] in note_ids or (len(content)>30 and content in body_signatures):
            continue
        unique.append(item); note_ids.add(item['noteId']); body_signatures.add(content)
    if len(unique)<count:
        raise ValueError('Fewer than 100 independent posts after deduplication.')
    sampled = rng.sample(unique,count)
    rng.shuffle(sampled)
    dataset_id = hashlib.sha256(json.dumps(sampled,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    manifest = {'datasetId':dataset_id,'model':'jev-1.13.0','ruleVersion':version,'sampleSize':count,
        'seed':seed,'sampling':'simple_random_from_saved_actual_jev_decisions_after_post_and_exact_text_deduplication',
        'sourceFile':checkpoint.name,'sourceSha256':original_hash,'eligiblePosts':len(unique),
        'rawJudgmentField':'note.jev_original_choice','modelCalls':0,
        'sampleClassCounts':dict(Counter(item['modelChoice'] for item in sampled)),
        'poolClassCounts':dict(Counter(item['modelChoice'] for item in unique))}
    dataset = {'datasetId':dataset_id,'manifest':manifest,'items':sampled}
    assets = Path(__file__).parent/'jev_annotation'
    page = (assets/'template.html').read_text(encoding='utf-8')
    payload = json.dumps(dataset,ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    for key, value in [('__STYLE__',(assets/'style.css').read_text(encoding='utf-8')),
                       ('__DATA__',payload),('__CORE__',(assets/'core.js').read_text(encoding='utf-8')),
                       ('__APP__',(assets/'app.js').read_text(encoding='utf-8'))]:
        page = page.replace(key,value)
    output.mkdir(parents=True,exist_ok=True)
    (output/'index.html').write_text(page,encoding='utf-8')
    (output/'dataset.json').write_text(json.dumps(dataset,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    assert source_sha(checkpoint)==original_hash, 'Source data changed during sampling'
    print(json.dumps({'output':str(output/'index.html'),'eligiblePosts':len(unique),'ruleVersion':version,
                     'sampleCounts':manifest['sampleClassCounts'],'sourceUnchanged':True},ensure_ascii=False))
    return dataset

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=20261012)
    args=parser.parse_args()
    build(args.checkpoint,args.output,seed=args.seed)

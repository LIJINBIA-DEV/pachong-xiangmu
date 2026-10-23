"""Audit the Jev-only batch and inference records without touching source data."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from image_subject import local_image_path
from image_subject_settings import runtime_settings
from select_jev_passed_compare import DEFAULT_OUT, passed
import openpyxl


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(out, allow_pending=False):
    report = json.loads((out/'results.json').read_text(encoding='utf-8'))
    samples = json.loads((out/'samples.json').read_text(encoding='utf-8'))
    manifest = report['selection_manifest']
    assert manifest['jev_passed_only'] is True
    assert manifest['total_images'] == report['sample_count'] == sum(len(p['images']) for p in samples) == 100
    for name, expected in manifest['source_hashes'].items():
        assert digest(PROJECT/name) == expected, 'Jev source changed: '+name
    workbooks, checkpoints = {}, {}
    hashes = set()
    for post in samples:
        proof = post['jev_pass']
        source = proof['checkpoint']
        if source not in checkpoints:
            checkpoints[source] = [json.loads(line) for line in (PROJECT/source).read_text(encoding='utf-8').splitlines()]
        state = checkpoints[source][proof['checkpoint_line']-1]
        source = proof['workbook']
        if source not in workbooks:
            w = openpyxl.load_workbook(PROJECT/source,read_only=True,data_only=True)
            workbooks[source] = {s.title: list(s.iter_rows(values_only=True)) for s in w}
            w.close()
        sheet = workbooks[source][proof['sheet']]
        row = dict(zip(sheet[0], sheet[proof['row']-1]))
        assert str(row['note_id']) == str(state['note']['note_id']) == post['note_id']
        assert row['content'] == state['note']['content'] == post['content']
        assert passed(state, row), 'Not a verified Jev pass: '+post['note_id']
        assert proof['evidence'] == state['evidence_text'] and proof['target_evidence'] == state['target_evidence_text']
        for im in post['images']:
            source = local_image_path(PROJECT/'data', im)
            actual = digest(source)
            assert actual == im['source_sha256'] and actual not in hashes
            hashes.add(actual)
            assert (out/'images'/post['note_id']/im['name']).is_file()
    models = {}
    for key in report['models']:
        texts = [p['text_models'][key] for p in report['posts']]
        images = [im['models'][key] for p in report['posts'] for im in p['images']]
        models[key] = {'images':dict(Counter(r['status'] for r in images)), 'texts':dict(Counter(r['status'] for r in texts))}
        # A malformed model answer is an observed failure, not a missing run.
        # Preserve it in the comparison instead of resampling until it succeeds.
        complete = all(r['status'] in {'recognized','error'} for r in texts+images)
        assert allow_pending or complete, 'Incomplete model: '+key
        for record in texts+images:
            if record['status']=='recognized':
                assert record.get('thinking_requested') is False and record.get('reasoning_chars') == 0 and not record.get('thinking_warning')
    document = (out/'index.html').read_text(encoding='utf-8')
    key = runtime_settings(PROJECT/'data')['api_key']
    assert key and key not in document and key not in (out/'results.json').read_text(encoding='utf-8')
    assert '保留原 49 张' not in document and 'Jev 已通过' in document
    assert '+jevPanel(p)+' in document
    ui = subprocess.run(['node',str(PROJECT/'scripts/verify_cute_compare_ui.cjs'),str(out)],capture_output=True,text=True,encoding='utf-8',check=True)
    subprocess.run(['node','--check',str(out/'ui-check.js')],capture_output=True,check=True)
    production = {p.name:json.loads(p.read_text(encoding='utf-8')) for p in out.glob('audit-q*.json')}
    preserved = bool(production) and all(v['unchanged'] for v in production.values())
    previous = json.loads((out/'previous-report-sha256.json').read_text(encoding='utf-8'))
    previous_unchanged = all(digest(PROJECT/'artifacts/model-compare-100-20261013'/name)==expected for name,expected in previous.items())
    assert previous_unchanged, 'Previous report or inference records changed'
    if not allow_pending:
        assert preserved, 'Source snapshot changes require investigation'
    result = {'jev_passed_only':True,'source_proofs_checked':len(samples),'unique_original_images':len(hashes),
              'models':models,'complete':all(sum(v['images'].get(s,0) for s in ('recognized','error'))==100
                  and sum(v['texts'].get(s,0) for s in ('recognized','error'))==len(samples) for v in models.values()),
              'review_model_cache_excel_unchanged':preserved,'production_checks':production,
              'previous_report_and_inference_records_unchanged':previous_unchanged,
              'secrets_absent':True,'ui_logic_verification':json.loads(ui.stdout),'live_browser_verification':False}
    if (out/'service-verification.json').exists():
        result.update(json.loads((out/'service-verification.json').read_text(encoding='utf-8')))
    if not allow_pending:
        assert result.get('original_spark_containers_unchanged') and result.get('temporary_model_port_closed') and result.get('temporary_model_process_gone'), 'Service cleanup not verified'
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--allow-pending',action='store_true')
    args=parser.parse_args()
    audit(args.out,args.allow_pending)

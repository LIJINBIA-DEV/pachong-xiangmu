import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import image_subject as subject
from api.routers import data as data_router
from api.services.manual_review import annotations, read_state, state_lock, storage_path, update_annotation
from api.schemas.crawler import CrawlerStartRequest


@pytest.fixture
def batch(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(data_router, 'DATA_DIR', tmp_path)
    folder = tmp_path / 'weibo'
    folder.mkdir()
    path = folder / 'posts.json'
    path.write_text(json.dumps([{'note_id': '1', 'source_keyword': '可爱 公园', 'image_names': '001.jpg,002.jpg,003.jpg', 'content': '公园里的雕塑真可爱'}]), encoding='utf-8')
    media = tmp_path / 'wb/media/1'
    media.mkdir(parents=True)
    for name in ('001.jpg', '002.jpg'):
        Image.new('RGB', (128, 192), 'red').save(media / name)
    return tmp_path, path, media


class FakeReviewer:
    starts = 0
    calls = 0
    closes = 0

    def __init__(self, root):
        pass

    async def start(self):
        FakeReviewer.starts += 1

    async def classify(self, path):
        FakeReviewer.calls += 1
        return {'label': '人物', 'reason': '人物位于画面中央。', 'image_type': '实景照片', 'type_reason': '现场拍摄人物。'}

    async def close(self):
        FakeReviewer.closes += 1


@pytest.mark.asyncio
async def test_recognition_keeps_human_marks_and_source_and_deduplicates(batch):
    root, path, media = batch
    original = path.read_bytes()
    update_annotation(root, path, '1:可爱 公园', 'image', 'qualified', '001.jpg')
    update_annotation(root, path, '1:可爱 公园', 'account', 'non_marketing')
    human = read_state(root, path)
    FakeReviewer.calls = FakeReviewer.starts = FakeReviewer.closes = 0
    result = await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer)
    assert result['total'] == result['completed'] == 2 and result['not_downloaded'] == 1
    assert FakeReviewer.calls == 1  # Identical bytes share inference, even across names.
    assert FakeReviewer.starts == FakeReviewer.closes == 1
    entry = annotations(root, path)['entries']['1:可爱 公园']
    assert entry['review_images'][0]['subject']['label'] == '人物'
    assert entry['review_images'][0]['subject']['suggestion'] == 'unqualified'
    assert entry['review_images'][2]['subject']['status'] == 'not_downloaded'
    assert entry['images']['001.jpg'] == 'qualified' and entry['decision'] == 'qualified'
    saved = read_state(root, path)
    assert saved['accounts'] == human['accounts']
    assert saved['posts']['1:可爱 公园']['images']['001.jpg'] == human['posts']['1:可爱 公园']['images']['001.jpg']
    assert entry['images']['002.jpg'] == 'unqualified'
    assert entry['review_images'][0]['decision_source'] == 'manual'
    assert entry['review_images'][1]['decision_source'] == 'model'
    assert path.read_bytes() == original
    result = await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer)
    assert result['cached'] == 2 and FakeReviewer.starts == 1  # No model load on resume.
    Image.new('RGB', (300, 400), 'blue').save(media / '001.jpg')
    assert annotations(root, path)['entries']['1:可爱 公园']['review_images'][0]['subject']['status'] == 'unrecognized'


@pytest.mark.asyncio
async def test_auto_checks_all_labels_persist_and_human_override_and_reset_survive(batch):
    root, path, media = batch
    note = json.loads(path.read_text())[0]
    note['image_names'] = '001.jpg,002.jpg,003.jpg,004.jpg,005.jpg'
    path.write_text(json.dumps([note]), encoding='utf-8')
    for name, color in [('002.jpg', 'blue'), ('003.jpg', 'green'), ('004.jpg', 'yellow')]:
        Image.new('RGB', (128, 192), color).save(media / name)
    class Mixed(FakeReviewer):
        async def classify(self, image):
            if image.name == '004.jpg':
                raise ValueError('unreadable model result')
            return {'label': {'001.jpg': '人物', '002.jpg': '食物', '003.jpg': '二者都不是'}[image.name], 'reason': '测试主体。', 'image_type': '实景照片', 'type_reason': '现场照片。'}
    key = '1:可爱 公园'
    result = await subject.recognize_files(root, [path], reviewer_factory=Mixed)
    assert (result['completed'], result['failed'], result['not_downloaded']) == (3, 1, 1)
    saved = read_state(root, path)['posts'][key]
    assert saved['images'] == {'001.jpg': 'unqualified', '002.jpg': 'unqualified', '003.jpg': 'qualified'}
    assert '005.jpg' not in saved['image_sources']
    assert {saved['image_sources'][key] for key in ('001.jpg','002.jpg','003.jpg')} == {'model'}
    update_annotation(root, path, key, 'account', 'non_marketing')
    assert annotations(root, path)['entries'][key]['decision'] == 'qualified'
    update_annotation(root, path, key, 'image', 'unqualified', '003.jpg')
    update_annotation(root, path, key, 'image', 'qualified', '001.jpg')
    update_annotation(root, path, key, 'image', None, '002.jpg')
    await subject.recognize_files(root, [path], reviewer_factory=Mixed)
    entry = annotations(root, path)['entries'][key]
    assert entry['images'] == {'001.jpg': 'qualified', '002.jpg': None, '003.jpg': 'unqualified'}
    assert entry['decision'] == 'qualified'
    assert all(image['decision_source'] == 'manual' for image in entry['review_images'][:3])


@pytest.mark.asyncio
async def test_post_correction_survives_model_defaults_and_retry(batch):
    root, path, _ = batch
    key = '1:可爱 公园'
    update_annotation(root, path, key, 'account', 'non_marketing')
    update_annotation(root, path, key, 'post', 'qualified')
    await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer)
    entry = annotations(root, path)['entries'][key]
    assert entry['images'] == {'001.jpg': 'unqualified', '002.jpg': 'unqualified'}
    assert entry['decision'] == 'qualified' and entry['post_decision_source'] == 'manual'
    assert entry['automatic_decision'] is None  # Missing downloads await review, rather than count as rejected.
    await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer)
    assert annotations(root, path)['entries'][key]['decision'] == 'qualified'
    assert update_annotation(root, path, key, 'post', None)['entries'][key]['decision'] is None


@pytest.mark.asyncio
async def test_stale_auto_marks_are_cleared_but_legacy_human_marks_remain(batch):
    root, path, media = batch
    key = '1:可爱 公园'
    await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer)
    saved = read_state(root, path)
    saved['posts'][key]['image_sources'].pop('001.jpg')
    storage_path(root, path).write_text(json.dumps(saved), encoding='utf-8')
    Image.new('RGB', (100, 100), 'green').save(media / '001.jpg')
    Image.new('RGB', (100, 100), 'green').save(media / '002.jpg')
    entry = annotations(root, path)['entries'][key]
    assert entry['images'] == {'001.jpg': 'unqualified'}
    assert entry['review_images'][0]['decision_source'] == 'manual'
    assert entry['review_images'][1]['subject']['status'] == 'unrecognized'


@pytest.mark.asyncio
async def test_failure_is_not_a_negative_label_and_can_retry(batch):
    root, path, _ = batch
    class Broken(FakeReviewer):
        async def classify(self, path):
            raise httpx.ConnectError('local service disconnected')
    result = await subject.recognize_files(root, [path], reviewer_factory=Broken)
    assert result['failed'] == 2 and result['completed'] == 0
    entry = annotations(root, path)['entries']['1:可爱 公园']
    assert entry['review_images'][0]['subject']['status'] == 'error'
    assert entry['images'] == {} and entry['decision'] is None
    result = await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer)
    assert result['failed'] == 0 and result['completed'] == 2


@pytest.mark.asyncio
async def test_startup_failure_closes_and_releases_lease(batch):
    root, path, _ = batch
    class Broken(FakeReviewer):
        async def start(self):
            raise RuntimeError('model cannot load')
    before = FakeReviewer.closes
    with pytest.raises(RuntimeError, match='cannot load'):
        await subject.recognize_files(root, [path], reviewer_factory=Broken)
    assert FakeReviewer.closes == before + 1 and not subject.inference_busy(root)


def test_path_boundary_and_exclusive_lock(batch):
    root, path, media = batch
    assert subject.local_image_path(root, {'local': True, 'url': '/api/data/media/../outside.jpg'}) is None
    assert subject.local_image_path(root, {'local': True, 'url': 'https://example.com/test.jpg'}) is None
    with subject.InferenceLease(root):
        assert subject.inference_busy(root)
        with pytest.raises(subject.ModelBusyError):
            with subject.InferenceLease(root):
                pass
    assert not subject.inference_busy(root)


@pytest.mark.parametrize('image_type,expected', [
    ('宣传海报', 'unqualified'), ('广告设计图', 'unqualified'),
    ('聊天截图', 'unqualified'), ('网页截图', 'unqualified'),
    ('文字／图文设计卡片', 'unqualified'),
    ('实景照片', 'qualified'), ('不确定', None),
])
@pytest.mark.asyncio
async def test_image_type_drives_auto_marks_and_preserves_human_corrections(batch, image_type, expected):
    root, path, _ = batch
    key = '1:可爱 公园'
    update_annotation(root, path, key, 'image', 'qualified', '001.jpg')
    state = read_state(root, path)
    state['posts'][key]['images']['002.jpg'] = 'qualified'
    state['posts'][key].setdefault('image_sources', {})['002.jpg'] = 'model'
    storage_path(root, path).write_text(json.dumps(state), encoding='utf-8')
    class Typed(FakeReviewer):
        async def classify(self, path):
            return {'label': '二者都不是', 'reason': '公园中的装置或设计画面。',
                    'image_type': image_type, 'type_reason': '依据图片中的现场环境或版式。'}
    await subject.recognize_files(root, [path], reviewer_factory=Typed)
    entry = annotations(root, path)['entries'][key]
    assert entry['images']['001.jpg'] == 'qualified'
    assert entry['review_images'][0]['decision_source'] == 'manual'
    assert entry['images'].get('002.jpg') == expected
    assert entry['review_images'][1]['subject']['image_type'] == image_type
    assert ('002.jpg' in entry['images']) == (expected is not None)


def test_uncertain_type_is_manual_even_when_subject_is_person():
    prediction = {'label': '人物', 'reason': '人物画面。', 'image_type': '不确定', 'type_reason': '无法区分实物与画面。'}
    assert subject.valid_prediction(prediction)
    assert subject.image_suggestion(prediction) is None
    prediction.pop('image_type')
    assert not subject.valid_prediction(prediction)
    assert subject.image_suggestion(prediction) is None


@pytest.mark.parametrize('reason,contradictory', [
    ('画面主体为三只真实的大熊猫，属于动物类人物，符合人物主体定义。', True),
    ('主体为一只猫，背景有游客。', True),
    ('主要拍摄对象是公园里的小鹿。', True),
    ('画面主体为一名饲养员与大熊猫互动。', False),
    ('主体为人物抱着熊猫玩偶，人物居于画面中心。', False),
    ('主体为人与猫的合影。', False),
    ('画面主体为一名儿童，背景有动物雕塑。', False),
])
def test_animal_consistency_gate_keeps_real_people_with_animals(reason, contradictory):
    value = {'label': '人物', 'reason': reason, 'image_type': '实景照片', 'type_reason': '现场拍摄。'}
    assert bool(subject.prediction_consistency_issue(value)) == contradictory
    assert subject.image_suggestion(value) == (None if contradictory else 'unqualified')


@pytest.mark.asyncio
async def test_old_panda_cache_goes_pending_without_overwriting_manual_marks(batch):
    root, file, media = batch
    key = '1:可爱 公园'
    update_annotation(root, file, key, 'image', 'unqualified', '001.jpg')
    for name in ['001.jpg', '002.jpg']:
        p = media / name
        st = p.stat()
        subject.atomic_json(subject.cache_path(root, p), {
            'fingerprint': subject.fingerprint(animal_previous=True),
            'signature': [st.st_mtime_ns, st.st_size], 'status': 'recognized',
            'label': '人物', 'reason': '主体为三只大熊猫，属于动物类人物。',
            'image_type': '实景照片', 'type_reason': '动物园实景。'})
    before = annotations(root, file)['entries'][key]
    assert before['images'].get('002.jpg') is None
    assert before['images']['001.jpg'] == 'unqualified'
    assert before['review_images'][0]['subject']['consistency_status'] == 'pending'
    class Corrected(FakeReviewer):
        async def classify(self, path):
            return {'label': '二者都不是', 'reason': '真实大熊猫为主体。', 'image_type': '实景照片', 'type_reason': '动物园现场照片。'}
    result = await subject.recognize_files(root, [file], reviewer_factory=Corrected)
    assert result['completed'] == 2 and result['cached'] == 0
    after = annotations(root, file)['entries'][key]
    assert after['images']['001.jpg'] == 'unqualified'
    assert after['review_images'][0]['decision_source'] == 'manual'
    assert after['images']['002.jpg'] == 'qualified'


@pytest.mark.asyncio
async def test_retry_does_not_reuse_contradictory_shared_content(batch):
    root, file, media = batch
    calls = []
    class Rechecked(FakeReviewer):
        async def classify(self, path):
            calls.append(path)
            return {'label': '人物' if len(calls) == 1 else '二者都不是',
                    'reason': '主体为三只大熊猫。', 'image_type': '实景照片', 'type_reason': '动物园照片。'}
    await subject.recognize_files(root, [file], reviewer_factory=Rechecked, image_paths=[media / '001.jpg'])
    assert annotations(root, file)['entries']['1:可爱 公园']['images'].get('001.jpg') is None
    result = await subject.recognize_files(root, [file], reviewer_factory=Rechecked, image_paths=[media / '001.jpg'])
    assert len(calls) == 2 and result['cached'] == 0
    assert annotations(root, file)['entries']['1:可爱 公园']['images']['001.jpg'] == 'qualified'


@pytest.mark.parametrize('provider', ['local', 'siliconflow'])
@pytest.mark.asyncio
async def test_text_card_scoped_rerun_preserves_other_cached_scene_marks(batch, provider):
    root, file, media = batch
    key = '1:可爱 公园'
    for name in ('001.jpg', '002.jpg'):
        stat = (media / name).stat()
        subject.atomic_json(subject.cache_path(root, media / name), {
            'fingerprint': subject.fingerprint(text_previous=True, provider=provider),
            'provider': provider, 'signature': [stat.st_mtime_ns, stat.st_size],
            'status': 'recognized', 'label': '二者都不是', 'reason': '环境为主。',
            'image_type': '实景照片', 'type_reason': '现场招牌和墙绘照片。'})
    before = annotations(root, file)['entries'][key]
    assert before['images'] == {'001.jpg': 'qualified', '002.jpg': 'qualified'}
    old_cache = subject.cache_path(root, media / '002.jpg').read_bytes()
    calls = []
    class Cards(FakeReviewer):
        async def classify(self, image):
            calls.append(image.name)
            return {'label': '二者都不是', 'reason': '大字为主的设计切片。',
                    'image_type': '文字／图文设计卡片', 'type_reason': '纯色底配后期排版大字。'}
    result = await subject.recognize_files(root, [file], reviewer_factory=Cards,
        image_paths=[media / '001.jpg'], force=True,
        options={'provider': provider, 'model': 'test', 'api_key': ''})
    assert result['total'] == result['completed'] == 1 and calls == ['001.jpg']
    assert subject.cache_path(root, media / '002.jpg').read_bytes() == old_cache
    after = annotations(root, file)['entries'][key]
    assert after['images'] == {'001.jpg': 'unqualified', '002.jpg': 'qualified'}
    assert after['review_images'][1]['subject']['image_type'] == '实景照片'
    assert subject.fingerprint(text_previous=True, provider=provider) != subject.fingerprint(provider=provider)


@pytest.mark.parametrize('label,image_type,pending', [
    ('二者都不是', '实景照片', False),
    ('人物', '不确定', False),
    ('人物', '聊天截图', False),
    ('二者都不是', '网页截图', False),
    ('人物', '实景照片', True),
    ('食物', '实景照片', True),
    ('二者都不是', '宣传海报', True),
    ('二者都不是', '广告设计图', True),
])
def test_collage_update_rechecks_only_affected_automatic_negatives(batch, label, image_type, pending):
    root, file, media = batch
    path = media / '001.jpg'
    stat = path.stat()
    record = {'fingerprint': subject.fingerprint(previous=True),
              'signature': [stat.st_mtime_ns, stat.st_size], 'status': 'recognized',
              'label': label, 'reason': '旧主体依据。', 'image_type': image_type, 'type_reason': '旧类型依据。'}
    subject.atomic_json(subject.cache_path(root, path), record)
    images, _ = subject.image_catalog(root, [file])
    prediction = subject.cached_prediction(root, images[str(path.resolve())])
    assert (prediction.get('policy_status') == 'pending') == pending
    assert prediction['suggestion'] == (None if pending else subject.image_suggestion(record))


@pytest.mark.asyncio
async def test_collage_reclassification_changes_model_marks_but_keeps_human_override(batch):
    root, file, media = batch
    original = file.read_bytes()
    key = '1:可爱 公园'
    update_annotation(root, file, key, 'image', 'unqualified', '001.jpg')
    for path in (media / '001.jpg', media / '002.jpg'):
        stat = path.stat()
        subject.atomic_json(subject.cache_path(root, path), {
            'fingerprint': subject.fingerprint(previous=True), 'signature': [stat.st_mtime_ns, stat.st_size],
            'status': 'recognized', 'label': '人物', 'reason': '误将局部路人作为主体。',
            'image_type': '宣传海报', 'type_reason': '误将现场招牌当作宣传。'})
    assert annotations(root, file)['entries'][key]['images'] == {'001.jpg': 'unqualified'}
    class Collage(FakeReviewer):
        async def classify(self, path):
            return {'label': '二者都不是', 'reason': '记录环境，人物只是局部细节。',
                    'image_type': '实景照片', 'type_reason': '现场照片拼接，招牌在照片内。'}
    result = await subject.recognize_files(root, [file], reviewer_factory=Collage)
    assert result['completed'] == 2 and result['cached'] == 0
    entry = annotations(root, file)['entries'][key]
    assert entry['images'] == {'001.jpg': 'unqualified', '002.jpg': 'qualified'}
    assert entry['review_images'][0]['decision_source'] == 'manual'
    assert entry['review_images'][1]['decision_source'] == 'model'
    assert file.read_bytes() == original
    resumed = await subject.recognize_files(root, [file], reviewer_factory=Collage)
    assert resumed['cached'] == 2


@pytest.mark.asyncio
async def test_forced_rerun_bypasses_old_content_and_keeps_manual_edits_during_inference(batch):
    root, file, media = batch
    await subject.recognize_files(root, [file], reviewer_factory=FakeReviewer)
    assert annotations(root, file)['entries']['1:可爱 公园']['images']['002.jpg'] == 'unqualified'
    calls = []
    class Updated(FakeReviewer):
        async def classify(self, image):
            calls.append(image)
            update_annotation(root, file, '1:可爱 公园', 'image', 'unqualified', '001.jpg')
            return {'label': '二者都不是', 'reason': '主要记录现场环境。', 'image_type': '实景照片', 'type_reason': '普通实景照片拼接。'}
    result = await subject.recognize_files(root, [file], reviewer_factory=Updated, force=True)
    assert result['completed'] == 2 and result['cached'] == 0 and result['force']
    assert len(calls) == 1  # Fresh inference, deduplicating only within this run.
    entry = annotations(root, file)['entries']['1:可爱 公园']
    assert entry['images'] == {'001.jpg': 'unqualified', '002.jpg': 'qualified'}
    assert entry['review_images'][0]['decision_source'] == 'manual'


@pytest.mark.asyncio
async def test_full_rerun_audit_preserves_resets_accounts_and_post_override(batch):
    from api.services.image_subject_audit import prepare_rerun, finish_rerun
    from api.services.image_subject import ImageSubjectJobs
    root, file, _ = batch
    key = '1:可爱 公园'
    update_annotation(root, file, key, 'image', None, '001.jpg')
    update_annotation(root, file, key, 'account', 'non_marketing')
    update_annotation(root, file, key, 'post', 'qualified')
    audit = root / '.image-subject/reruns/test'
    prepare_rerun(root, file, audit)
    result = await subject.recognize_files(root, [file], reviewer_factory=FakeReviewer, force=True)
    finish_rerun(root, file, audit, result)
    report = json.loads((audit / 'report.json').read_text(encoding='utf-8'))
    assert report['manual_marks_preserved'] and report['manual_marks_unchanged'] and report['source_file_unchanged']
    assert report['manual_counts'] == {'images': 1, 'posts': 1, 'accounts': 1}
    assert report['automatic_marks_verified'] == 1
    jobs = ImageSubjectJobs()
    subject.atomic_json(jobs.state_path(root, file), {**result, 'status': 'running', 'completed': 1, 'audit': str(audit)})
    jobs.task = asyncio.create_task(asyncio.sleep(0.01))
    assert jobs.status(root, file)['completed'] == 1  # Not the two old cached results.
    await jobs.task


@pytest.mark.asyncio
async def test_forced_background_job_retries_failures_and_keeps_full_run_progress(batch, monkeypatch):
    from api.services.image_subject import ImageSubjectJobs
    import api.services.image_subject as jobs_module
    import api.services.image_subject_audit as audit_module
    root, file, _ = batch
    calls = []
    audits = []
    async def recognize(root, files, progress, force=False):
        calls.append(force)
        result = {'status': 'completed_with_errors' if force else 'completed',
                  'total': 2, 'completed': 1 if force else 2,
                  'failed': 1 if force else 0, 'not_downloaded': 1, 'cached': 0 if force else 1}
        progress(result)
        return result
    monkeypatch.setattr(jobs_module, 'recognize_files', recognize)
    monkeypatch.setattr(audit_module, 'prepare_rerun', lambda *args: None)
    monkeypatch.setattr(audit_module, 'finish_rerun', lambda *args: audits.append(args[-1]))
    jobs = ImageSubjectJobs()
    await jobs._run(root, file, force=True)
    saved = json.loads(jobs.state_path(root, file).read_text(encoding='utf-8'))
    assert calls == [True, False]
    assert saved['force'] and saved['completed'] == 2 and saved['failed'] == 0
    assert saved['initial_failed'] == 1 and saved['retry_passes'] == 1
    assert audits[0]['force']


@pytest.mark.asyncio
async def test_type_missing_result_is_retryable_and_not_approved(batch):
    root, path, _ = batch
    class Incomplete(FakeReviewer):
        async def classify(self, path):
            return {'label': '二者都不是', 'reason': '可能是海报。'}
    result = await subject.recognize_files(root, [path], reviewer_factory=Incomplete)
    assert result['failed'] == 2 and result['completed'] == 0
    assert annotations(root, path)['entries']['1:可爱 公园']['images'] == {}


@pytest.mark.asyncio
async def test_sample_is_scoped_and_legacy_positive_needs_new_type(batch):
    root, path, media = batch
    key = '1:可爱 公园'
    for name, label in [('001.jpg', '二者都不是'), ('002.jpg', '人物')]:
        stat = (media / name).stat()
        subject.atomic_json(subject.cache_path(root, media / name), {
            'fingerprint': subject.fingerprint(legacy=True), 'signature': [stat.st_mtime_ns, stat.st_size],
            'status': 'recognized', 'label': label, 'reason': '旧主体判断。', 'suggestion': 'qualified',
        })
    entry = annotations(root, path)['entries'][key]
    assert entry['images'] == {'002.jpg': 'unqualified'}
    assert entry['review_images'][0]['subject']['type_status'] == 'pending'
    from api.services.image_subject import ImageSubjectJobs
    assert ImageSubjectJobs().status(root, path)['completed'] == 0
    result = await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer, image_paths=[media / '001.jpg'])
    assert result['completed'] == result['total'] == 1
    assert annotations(root, path)['entries'][key]['review_images'][1]['subject']['type_status'] == 'pending'
    with pytest.raises(ValueError, match='catalog'):
        await subject.recognize_files(root, [path], reviewer_factory=FakeReviewer, image_paths=[root / 'outside.jpg'])


def test_review_state_lock_is_shared_with_crawler_process(batch):
    root, path, _ = batch
    probe = '''
import os, sys
with open(sys.argv[1], 'r+b') as handle:
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('locked')
    else:
        print('free')
'''
    lock_path = storage_path(root, path).with_suffix('.lock')
    with state_lock(root, path):
        result = subprocess.run([sys.executable, '-c', probe, str(lock_path)], capture_output=True, text=True, timeout=10, check=True)
        assert result.stdout.strip() == 'locked'
    result = subprocess.run([sys.executable, '-c', probe, str(lock_path)], capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == 'free'


def test_model_cache_is_hidden_and_api_requires_collection_file(batch):
    root, path, _ = batch
    hidden = root / '.image-subject/index/test.json'
    hidden.parent.mkdir(parents=True)
    hidden.write_text('{}')
    app = FastAPI()
    app.include_router(data_router.router, prefix='/api')
    with TestClient(app) as client:
        response = client.get('/api/data/image-subject', params={'file': 'weibo/posts.json'})
        assert response.status_code == 200
        assert response.json()['total'] == 2 and response.json()['not_downloaded'] == 1
        assert client.get('/api/data/image-subject', params={'file': '../outside.json'}).status_code == 403
        assert client.get('/api/data/stats').json()['total_files'] == 1
        assert len(client.get('/api/data/files').json()['files']) == 1


@pytest.mark.asyncio
async def test_jobs_block_concurrent_crawl_and_cancel_safely(batch, monkeypatch):
    from api.services.image_subject import ImageSubjectJobs
    import api.services.image_subject as jobs_module
    root, path, _ = batch
    jobs = ImageSubjectJobs()
    manager = SimpleNamespace(_lock=asyncio.Lock(), status='running', process=None)
    with pytest.raises(ValueError, match='collection_active'):
        await jobs.start(root, path, manager)
    manager.status = 'idle'
    monkeypatch.setattr(jobs_module, 'model_ready', lambda: True)
    entered = asyncio.Event()
    released = asyncio.Event()
    async def slow(*args, **kwargs):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            released.set()
    monkeypatch.setattr(jobs_module, 'recognize_files', slow)
    await jobs.start(root, path, manager)
    await entered.wait()
    with pytest.raises(ValueError, match='image_subject_busy'):
        await jobs.start(root, path, manager)
    await jobs.close()
    assert released.is_set() and not jobs.running


@pytest.mark.asyncio
async def test_local_request_contains_pixels_only_and_validates_response(batch):
    root, _, media = batch
    reviewer = subject.LocalImageReviewer(root)
    await reviewer.client.aclose()
    requests = []
    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"label":"未知","reason":"无法判断"}'}}]})
    reviewer.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    reviewer.url = 'http://localhost:9999'
    with pytest.raises(ValueError, match='Invalid image-subject'):
        await reviewer.classify(media / '001.jpg')
    user = requests[0]['messages'][1]['content']
    assert user[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert '可爱 公园' not in str(user) and '001.jpg' not in str(user)
    await reviewer.close()


@pytest.mark.parametrize('platform', ['wb', 'xhs'])
@pytest.mark.parametrize('media', [False, True])
def test_start_command_respects_media_choice_despite_legacy_recognition(platform, media):
    from api.services.crawler_manager import CrawlerManager
    config = CrawlerStartRequest(platform=platform, save_option='excel', enable_media=media, image_subject_recognition=True)
    command = CrawlerManager()._build_command(config)
    assert command[command.index('--get_media') + 1] == str(media).lower()

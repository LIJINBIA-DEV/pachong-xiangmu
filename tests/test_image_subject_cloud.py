import asyncio
import json
import os
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import image_subject as subject
import image_subject_cloud as cloud
import image_subject_settings as settings
from api.routers import data as router
from api.services.image_subject import ImageSubjectJobs
from api.services.manual_review import annotations, update_annotation


PREDICTION = {'label': '二者都不是', 'reason': '现场拍摄的公园装置。', 'image_type': '实景照片', 'type_reason': '有真实场景和实体招牌。'}


@pytest.mark.parametrize('recover', [True, False])
@pytest.mark.asyncio
async def test_panda_person_contradiction_rechecks_and_never_becomes_auto_negative(batch, monkeypatch, recover):
    root, _, media = batch
    async def no_wait(seconds):
        pass
    monkeypatch.setattr(cloud.asyncio, 'sleep', no_wait)
    wrong = {**PREDICTION, 'label': '人物', 'reason': '画面主体为三只真实的大熊猫，属于动物类人物，符合人物主体定义。'}
    corrected = {**PREDICTION, 'reason': '主体为三只真实大熊猫，动物不是人物或食物。'}
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        result = corrected if recover and len(requests) > 1 else wrong
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})
    reviewer = cloud.SiliconFlowImageReviewer(root, 'test-key', httpx.MockTransport(handle))
    result = await reviewer.classify(media / '001.jpg')
    await reviewer.close()
    assert len(requests) == 2
    assert requests[1]['messages'][1]['content'][0]['text'] == subject.CONSISTENCY_RECHECK
    assert result['consistency_status'] == ('verified' if recover else 'pending')
    assert subject.image_suggestion(result) == ('qualified' if recover else None)
    assert result['consistency_rechecks'][0]['raw_output'] == json.dumps(wrong)
    assert result['raw_output'] == json.dumps(corrected if recover else wrong)


@pytest.fixture
def batch(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(router, 'DATA_DIR', tmp_path)
    monkeypatch.delenv('SILICONFLOW_API_KEY', raising=False)
    monkeypatch.delenv('MEDIACRAWLER_IMAGE_PROVIDER', raising=False)
    (tmp_path / 'weibo').mkdir()
    file = tmp_path / 'weibo/posts.json'
    file.write_text(json.dumps([{'note_id': '1', 'source_keyword': '可爱 公园', 'image_names': '001.jpg,002.jpg', 'content': '可爱的公园装置'}]), encoding='utf-8')
    media = tmp_path / 'wb/media/1'
    media.mkdir(parents=True)
    for name, color in [('001.jpg', 'red'), ('002.jpg', 'blue')]:
        Image.new('RGB', (128, 192), color).save(media / name)
    return tmp_path, file, media


@pytest.mark.asyncio
async def test_cloud_request_retries_and_uses_same_rules_and_no_post_context(batch, monkeypatch):
    root, _, media = batch
    requests = []
    async def no_wait(seconds):
        pass
    monkeypatch.setattr(cloud.asyncio, 'sleep', no_wait)
    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, text='service unavailable')
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(PREDICTION)}}], 'usage': {'total_tokens': 123}})
    reviewer = cloud.SiliconFlowImageReviewer(root, 'test-key', httpx.MockTransport(handle))
    await reviewer.start()
    result = await reviewer.classify(media / '001.jpg')
    await reviewer.close()
    assert result['attempts'] == 2 and result['provider'] == 'siliconflow'
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == settings.CLOUD_URL
    assert body['model'] == settings.CLOUD_MODEL and not body['enable_thinking']
    assert body['messages'][0]['content'] == subject.PROMPT
    assert body['response_format']['json_schema']['schema'] == subject.SCHEMA
    user = body['messages'][1]['content']
    assert user[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert user[1]['image_url']['detail'] == 'high'
    assert '001.jpg' not in str(user) and '可爱 公园' not in str(user)


@pytest.mark.asyncio
async def test_invalid_or_uncertain_cloud_result_does_not_approve(batch, monkeypatch):
    root, _, media = batch
    async def no_wait(seconds):
        pass
    monkeypatch.setattr(cloud.asyncio, 'sleep', no_wait)
    reviewer = cloud.SiliconFlowImageReviewer(root, 'test-key', httpx.MockTransport(lambda r: httpx.Response(200, json={'choices': []})))
    with pytest.raises(cloud.CloudImageError, match='image_subject_cloud_invalid_response'):
        await reviewer.classify(media / '001.jpg')
    await reviewer.close()
    assert subject.image_suggestion({**PREDICTION, 'image_type': '不确定'}) is None


@pytest.mark.asyncio
async def test_authentication_error_stops_without_leaking_secret(batch):
    root, _, media = batch
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(401, text='test-secret-must-not-leak')
    reviewer = cloud.SiliconFlowImageReviewer(root, 'test-secret-must-not-leak', httpx.MockTransport(handler))
    with pytest.raises(cloud.CloudImageError) as exc:
        await reviewer.classify(media / '001.jpg')
    await reviewer.close()
    assert len(calls) == 1 and exc.value.fatal
    assert str(exc.value) == 'image_subject_key_rejected'


@pytest.mark.asyncio
async def test_cloud_factory_bypasses_local_and_keeps_human_marks_and_cache_provenance(batch, monkeypatch):
    root, file, media = batch
    key = '1:可爱 公园'
    update_annotation(root, file, key, 'account', 'non_marketing')
    update_annotation(root, file, key, 'image', 'unqualified', '001.jpg')
    update_annotation(root, file, key, 'post', 'unqualified')
    calls = []
    class FakeCloud:
        def __init__(self, root, api_key):
            assert api_key == 'test-key'
        async def start(self):
            pass
        async def classify(self, path):
            calls.append(path)
            return PREDICTION
        async def close(self):
            pass
    monkeypatch.setattr(cloud, 'SiliconFlowImageReviewer', FakeCloud)
    monkeypatch.setattr(subject.LocalImageReviewer, 'start', lambda self: pytest.fail('must not start local inference'))
    options = {'provider': 'siliconflow', 'api_key': 'test-key', 'model': settings.CLOUD_MODEL}
    original = file.read_bytes()
    result = await subject.recognize_files(root, [file], options=options)
    assert result['completed'] == 2 and result['provider'] == 'siliconflow'
    entry = annotations(root, file)['entries'][key]
    assert entry['images'] == {'001.jpg': 'unqualified', '002.jpg': 'qualified'}
    assert entry['decision'] == 'unqualified' and entry['decision_source'] == 'manual'
    assert entry['review_images'][1]['subject']['provider'] == 'siliconflow'
    assert file.read_bytes() == original
    result = await subject.recognize_files(root, [file], options=options)
    assert result['cached'] == 2 and len(calls) == 2
    assert subject.cached_prediction(root, entry['review_images'][1], subject.fingerprint())['status'] == 'unrecognized'
    assert subject.fingerprint(provider='siliconflow') != subject.fingerprint()
    assert 'test-key' not in ''.join(p.read_text(encoding='utf-8') for p in (root / '.image-subject').rglob('*.json'))


def test_settings_api_encrypted_persistence_and_busy_protection(batch, monkeypatch):
    root, _, _ = batch
    from api.services import crawler_manager
    monkeypatch.setattr(crawler_manager, 'status', 'idle')
    monkeypatch.setattr(crawler_manager, 'process', None)
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    with TestClient(app) as client:
        response = client.put('/api/data/image-subject/settings', json={'provider': 'siliconflow', 'api_key': 'test-secret-not-in-browser'})
        assert response.status_code == 200
        assert response.json()['ready'] and response.json()['key_configured']
        assert 'test-secret' not in response.text
        assert 'test-secret' not in settings.settings_path(root).read_text()
        assert settings.runtime_settings(root)['api_key'] == 'test-secret-not-in-browser'
        assert 'api_key' not in client.get('/api/data/image-subject/settings').json()
        client.put('/api/data/image-subject/settings', json={'provider': 'local'})
        assert settings.runtime_settings(root)['api_key'] == 'test-secret-not-in-browser'
        with subject.InferenceLease(root):
            assert client.put('/api/data/image-subject/settings', json={'provider': 'siliconflow'}).status_code == 409
        monkeypatch.setattr(crawler_manager, 'status', 'running')
        assert client.put('/api/data/image-subject/settings', json={'provider': 'siliconflow'}).status_code == 409


@pytest.mark.asyncio
async def test_cloud_background_job_works_without_local_model(batch, monkeypatch):
    root, file, _ = batch
    import api.services.image_subject as jobs_module
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'test-key')
    settings.save_settings(root, 'siliconflow')
    monkeypatch.setattr(jobs_module, 'model_ready', lambda: False)
    calls = []
    async def recognize(root, files, progress, **kwargs):
        calls.append(kwargs['options'])
        result = {'status': 'completed', 'total': 2, 'completed': 2, 'failed': 0, 'not_downloaded': 0}
        progress(result)
        return result
    monkeypatch.setattr(jobs_module, 'recognize_files', recognize)
    jobs = ImageSubjectJobs()
    manager = SimpleNamespace(_lock=asyncio.Lock(), status='idle', process=None)
    await jobs.start(root, file, manager)
    await jobs.task
    assert calls[0]['provider'] == 'siliconflow'
    assert 'api_key' not in jobs.state_path(root, file).read_text()

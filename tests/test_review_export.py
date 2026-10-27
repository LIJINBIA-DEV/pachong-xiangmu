from io import BytesIO
import json
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
import pytest

from api.routers import data as router
from api.services.manual_review import annotations, read_state, update_annotation
from api.services.review_export import HEADERS, _published, _location
from image_subject import atomic_json, cache_path, fingerprint


@pytest.fixture
def collection(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path))
    path = tmp_path / 'weibo/posts.json'
    path.parent.mkdir()
    notes = [
        {'note_id': '5351872649235817', 'source_keyword': '可爱 公园', 'content': '=dangerous text', 'image_names': 'good.jpg,bad.jpg,missing.jpg', 'image_list': ['https://example.org/good.jpg','https://example.org/bad.jpg','https://example.org/missing.jpg']},
        {'note_id': 'excluded', 'content': 'excluded text', 'image_names': 'good.jpg'},
        {'note_id': 'pending', 'content': 'pending text', 'image_names': 'good.jpg'},
    ]
    path.write_text(json.dumps(notes, ensure_ascii=False), encoding='utf-8')
    for note in notes:
        media = tmp_path / 'wb/media' / note['note_id']
        media.mkdir(parents=True)
        Image.new('RGB', (300, 200), 'green').save(media / 'good.jpg')
    media = tmp_path / 'wb/media/5351872649235817'
    Image.new('RGB', (300, 200), 'red').save(media / 'bad.jpg')
    key = '5351872649235817:可爱 公园'
    update_annotation(tmp_path, path, key, 'post', 'qualified')
    update_annotation(tmp_path, path, key, 'image', 'qualified', 'good.jpg')
    update_annotation(tmp_path, path, key, 'image', 'unqualified', 'bad.jpg')
    update_annotation(tmp_path, path, 'excluded:', 'post', 'unqualified')
    app = FastAPI()
    app.include_router(router.router, prefix='/api')
    return tmp_path, path, TestClient(app), key


def test_export_only_retained_posts_and_approved_pictures_preserves_source(collection):
    root, path, client, key = collection
    original = path.read_bytes()
    state = read_state(root, path)
    response = client.post('/api/data/review/export', json={'file':'weibo/posts.json'})
    assert response.status_code == 200
    assert response.headers['x-review-retained'] == '1'
    assert response.headers['x-review-images'] == '2'
    assert response.headers['x-review-pending'] == '1'
    assert 'filename*=UTF-8' in response.headers['content-disposition']
    book = load_workbook(BytesIO(response.content))
    assert book.sheetnames == ['审核结果', '评论明细']
    posts = book['审核结果']
    assert posts.max_row == 2 and posts.max_column == 16
    row = dict(zip([c.value for c in posts[1]], [c.value for c in posts[2]]))
    assert list(row) == HEADERS
    assert row['发布内容'] == '=dangerous text'
    assert posts.cell(2, [c.value for c in posts[1]].index('发布内容') + 1).data_type == 's'
    assert row['编号'] == 1 and row['平台'] == '微博'
    assert row['标题'] == '未采集独立标题' and row['地点（定位优先）'] == '未获取'
    assert 'image_list' not in row and 'image_names' not in row
    assert 'bad.jpg' not in '\n'.join(str(c.value) for s in book for row in s for c in row)
    book.close()
    assert path.read_bytes() == original
    after = read_state(root, path)
    assert after['posts'][key]['images']['good.jpg'] == state['posts'][key]['images']['good.jpg']


def test_export_empty_and_traversal_are_rejected(collection):
    root, path, client, key = collection
    update_annotation(root, path, key, 'post', 'unqualified')
    assert client.post('/api/data/review/export', json={'file':'weibo/posts.json'}).json()['detail'] == 'review_export_empty'
    assert client.post('/api/data/review/export', json={'file':'../outside.json'}).status_code == 403


def test_missing_and_corrupt_images_default_rejected_but_human_marks_survive(collection):
    root, path, client, key = collection
    media = root / 'wb/media/5351872649235817'
    (media / 'bad.jpg').write_bytes(b'corrupt download')
    update_annotation(root, path, key, 'image', None, 'bad.jpg')
    entry = annotations(root, path)['entries'][key]
    assert 'missing.jpg' not in entry['images']
    assert next(i for i in entry['review_images'] if i['key']=='missing.jpg')['decision_source'] is None
    assert entry['images']['bad.jpg'] is None  # Explicit human clear is preserved.
    assert next(i for i in entry['review_images'] if i['key']=='bad.jpg')['download_problem'] is None
    # Missing-only posts receive an automatic excluded conclusion.
    notes=json.loads(path.read_text(encoding='utf-8'))
    notes.append({'note_id':'missing-only','image_names':'cover.jpg'})
    path.write_text(json.dumps(notes),encoding='utf-8')
    entry=annotations(root,path)['entries']['missing-only:']
    assert entry['decision'] is None and entry['images'] == {}
    Image.new('RGB',(32,32)).save(media/'missing.jpg')
    entry=annotations(root,path)['entries'][key]
    assert 'missing.jpg' not in entry['images']  # Later download restores pending recognition.


def test_inference_failure_is_not_download_failure(collection):
    root,path,client,key=collection
    media=root/'wb/media/pending/good.jpg'
    stat=media.stat()
    atomic_json(cache_path(root,media),{'fingerprint':fingerprint(),'signature':[stat.st_mtime_ns,stat.st_size],'status':'error','error':'network'})
    entry=annotations(root,path)['entries']['pending:']
    assert not entry['images'] and entry['decision'] is None


def test_exact_delivery_columns_and_related_comments_preserve_original_text(collection):
    root, path, client, key = collection
    notes=json.loads(path.read_text(encoding='utf-8'))
    notes[0].update(title='公园的猫形雕塑真可爱',semantic_result='matched', semantic_source='note', semantic_object_type='scene_animal',
        semantic_target_relation='scene_component', quality_reason='jev_screening_candidate',
        evidence_source='comment:12345', manual_review_required=True, semantic_comments_available=False,
        jev_original_choice='review', semantic_rule_version='scene-evidence-v10', custom_metric=0.7)
    notes.append({'comment_id':'12345','note_id':'5351872649235817','content':'可爱，Hello world', 'nickname':'原昵称', 'create_date_time':'2026-10-12 09:00:00'})
    notes.append({'comment_id':'unrelated','note_id':'5351872649235817','content':'公园天气很好'})
    notes.append({'comment_id':'same-first-word','note_id':'5351872649235817','content':'看着很可爱'})
    path.write_text(json.dumps(notes,ensure_ascii=False),encoding='utf-8')
    before=path.read_bytes()
    response=client.post('/api/data/review/export',json={'file':'weibo/posts.json'})
    assert response.status_code==200
    book=load_workbook(BytesIO(response.content))
    for sheet in book:
        assert all(not re.search('[A-Za-z]', cell.value.replace('ID', '').replace('IP', '')) for cell in sheet[1])
    sheet=book['审核结果']
    row=dict(zip([c.value for c in sheet[1]],[c.value for c in sheet[2]]))
    assert list(row) == HEADERS and sheet.max_column==16
    assert '【原昵称】可爱，Hello world' in row['与关键词一相关的评论']
    assert '看着很可爱' in row['与关键词一相关的评论']
    assert '公园天气很好' not in row['与关键词一相关的评论']
    detail = list(book['评论明细'].values)[1:]
    assert len(detail) == 3
    assert any('公园天气很好' == item[5] for item in detail)
    assert row['发布内容']=='=dangerous text' and path.read_bytes()==before
    assert row['命中关键词']=='可爱 公园'
    book.close()


def test_comments_for_same_post_are_available_across_keyword_combinations(collection):
    root, path, client, key = collection
    notes=json.loads(path.read_text(encoding='utf-8'))
    notes.append({'comment_id':'shared','note_id':'5351872649235817','source_keyword':'萌 公园','content':'公园的墙绘很可爱','nickname':'评论人'})
    path.write_text(json.dumps(notes,ensure_ascii=False),encoding='utf-8')
    response=client.post('/api/data/review/export',json={'file':'weibo/posts.json'})
    book=load_workbook(BytesIO(response.content))
    assert '公园的墙绘很可爱' in book['审核结果'].cell(2,9).value
    assert book['评论明细'].cell(2,6).value=='公园的墙绘很可爱'
    book.close()


def test_real_posting_location_is_not_inferred_from_ip_or_body():
    assert _location({'ip_location':'江苏','content':'南京公园真可爱'})=='未采集发布地点'
    assert _location({'location':{'name':'江苏南京'}})=='江苏南京'
    assert _published({'create_date_time':'2026-10-12 03:00:00+00:00'})=='2026-10-12 11:00:00'

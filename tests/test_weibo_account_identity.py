import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from account_audit import events
from api.services.manual_review import annotations, read_state, update_annotation
from api.services.collection_logs import collection_logs
from weibo_account_filter import account_identity, account_record_identity, account_filter_reason
from tools.user_hash import anonymize_user_id


@pytest.mark.parametrize('verification,reason', [
    ('资溪县融媒体中心', 'news_media_account'), ('南昌广播电视台', 'news_media_account'),
    ('某市人民政府新闻办公室', 'government_account'), ('某市公安局', 'government_account'),
    ('某县文化和旅游局', 'government_account'), ('某某科技有限公司', 'institution_account'),
    ('某某大学', 'institution_account'), ('某市人民医院官方微博', 'institution_account'),
    ('某市图书馆', 'institution_account'), ('某慈善基金会', 'institution_account'),
])
def test_explicit_organization_verification(verification, reason):
    user = {'screen_name': '普通昵称', 'verified': True, 'verified_reason': verification}
    assert account_identity(user) == {'status': 'excluded', 'reason': reason, 'evidence': verification}
    assert account_filter_reason(user) == reason


@pytest.mark.parametrize('verification', ['某融媒体中心记者', '某市公安局民警个人微博', '某大学教授', '某医院医生', '某科技有限公司工程师'])
def test_personal_roles_are_not_their_employers(verification):
    # Explicit personal role, not organization keywords alone.
    assert account_identity({'screen_name': '小张', 'verified': True, 'verified_reason': verification})['status'] == 'personal'


@pytest.mark.parametrize('user', [{}, {'screen_name': '某地发布'}, {'screen_name': '小张', 'verified': True},
    {'screen_name': '某某文旅', 'verified': False}, {'screen_name': '小张'},
    {'screen_name': '小张', 'verified': False, 'verified_reason': '某某有限公司'},
    {'screen_name': '普***称'}])
def test_uncertain_identity_is_review_not_excluded_or_personal(user):
    assert account_identity(user)['status'] == 'review'
    assert account_filter_reason(user) is None


def test_regular_unverified_and_exact_known_uid():
    assert account_identity({'screen_name': '小张', 'verified': False})['status'] == 'personal'
    assert account_record_identity({'creator_hash': anonymize_user_id('2945394960'), 'nickname': '抚***布'})['reason'] == 'news_media_account'
    assert account_record_identity({'note_id': '2945394960', 'nickname': '小张'})['status'] == 'review'


def dataset(root, notes):
    path = root / 'weibo/posts.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(notes), encoding='utf-8')
    return path


def test_hard_account_gate_preserves_human_marks_and_wins_positive_post(tmp_path):
    path = dataset(tmp_path, [{'note_id': 'n', 'nickname': '普通昵称', 'creator_hash': 'shared', 'author_verified': True,
        'author_verification': '某人民政府', 'image_names': '001.jpg'},
        {'note_id': 'other', 'creator_hash': 'shared', 'image_names': '001.jpg'}])
    update_annotation(tmp_path, path, 'n:', 'account', 'non_marketing')
    update_annotation(tmp_path, path, 'n:', 'image', 'qualified', '001.jpg')
    result = update_annotation(tmp_path, path, 'n:', 'post', 'qualified')
    assert all(item['decision'] == 'unqualified' for item in result['entries'].values())
    assert all(item['account_rejection_reason'] == 'government_account' for item in result['entries'].values())
    state = read_state(tmp_path, path)
    assert state['accounts']['creator:shared']['decision'] == 'non_marketing'
    assert state['posts']['n:']['images']['001.jpg'] == 'qualified'
    assert state['posts']['n:']['post_decision'] == 'qualified'
    partial = update_annotation(tmp_path, path, 'other:', 'image', 'qualified', '001.jpg', partial=True)
    assert partial['entries']['other:']['decision'] == 'unqualified'


def test_manually_cleared_unknown_account_still_requires_account_review(tmp_path):
    path = dataset(tmp_path, [{'note_id': 'n', 'nickname': '某地发布', 'image_names': '001.jpg'}])
    assert annotations(tmp_path, path)['entries']['n:']['account'] == 'non_marketing'
    update_annotation(tmp_path, path, 'n:', 'account', None)
    update_annotation(tmp_path, path, 'n:', 'image', 'qualified', '001.jpg')
    entry = update_annotation(tmp_path, path, 'n:', 'post', 'qualified')['entries']['n:']
    assert entry['decision'] is None and entry['decision_reason'] == 'account_pending'
    assert update_annotation(tmp_path, path, 'n:', 'account', 'non_marketing')['entries']['n:']['decision'] == 'qualified'


@pytest.mark.asyncio
async def test_collection_skips_before_details_models_comments_media_and_logs(tmp_path, monkeypatch):
    from media_platform.weibo import core
    for key, value in {'KEYWORDS': '可爱 公园', 'START_PAGE': 1, 'CRAWLER_MAX_NOTES_COUNT': 1,
        'CRAWLER_MAX_SLEEP_SEC': 0, 'SAVE_DATA_OPTION': 'json', 'SAVE_DATA_PATH': str(tmp_path)}.items():
        monkeypatch.setattr(core.config, key, value)
    monkeypatch.delenv('MEDIACRAWLER_COLLECTION_RUN', raising=False)
    monkeypatch.delenv('MEDIACRAWLER_SEMANTIC_FILTER', raising=False)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    bad = {'mblog': {'id': 'bad', 'user': {'screen_name': '某地发布', 'verified': True, 'verified_reason': '某县融媒体中心'}, 'isLongText': True}}
    good = {'mblog': {'id': 'good', 'user': {'screen_name': '小张', 'verified': False}}}
    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(return_value={'cards': [bad, good]}))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda rows: rows)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.search()
    assert crawler.batch_get_notes_full_text.await_args.args[0] == [good]
    saved.assert_awaited_once()
    assert saved.await_args.args[0]['mblog'] == good['mblog']
    assert saved.await_args.args[0]['_metadata_status']['detail'] == 'unavailable'
    crawler.download_media.assert_awaited_once_with(good['mblog'])
    crawler.batch_get_notes_comments.assert_awaited_once_with(['good'])
    records = list((tmp_path / '.account-audit/events').glob('*.json'))
    row = json.loads(records[0].read_text(encoding='utf-8'))
    assert row['reason'] == 'news_media_account' and row['evidence'] == '某县融媒体中心'


def test_historical_audit_logs_reachable_without_task_and_sources_unchanged(tmp_path, monkeypatch):
    from scripts.audit_weibo_accounts import audit
    path = dataset(tmp_path, [{'note_id': 'n', 'creator_hash': anonymize_user_id('2945394960'), 'nickname': '抚州资溪发布'}])
    before = path.read_bytes()
    report = audit(tmp_path, tmp_path / 'report')
    assert report['files'][0]['identities'] == {'excluded': 1}
    logs = collection_logs(tmp_path, path)['account_events']
    assert logs[0]['reason'] == 'news_media_account' and logs[0]['stage'] == 'historical'
    assert path.read_bytes() == before


def test_live_exclusions_are_durable_and_linked_to_the_correct_collection(tmp_path, monkeypatch):
    from collection_tasks import create_task, prepare_run
    from weibo_account_filter import log_account_exclusion
    path = dataset(tmp_path, [])
    task = create_task(tmp_path, {'platform': 'wb'}, {'可爱 公园': 2}, 'weibo/posts.json')
    run_path = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run_path))
    user = {'id': '999999999', 'screen_name': '某地发布', 'verified': True, 'verified_reason': '某市公安局', 'Cookie': 'do-not-save'}
    log_account_exclusion(user, 'post-id', '可爱 公园')
    log_account_exclusion(user, 'post-id', '可爱 公园')
    logs = collection_logs(tmp_path, path)['account_events']
    assert len(logs) == 1 and logs[0]['run_id'] == run_path.stem
    assert logs[0]['reason'] == 'government_account' and logs[0]['evidence'] == '某市公安局'
    assert 'do-not-save' not in json.dumps(logs) and '999999999' not in json.dumps(logs)

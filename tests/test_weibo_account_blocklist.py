"""UID exclusions must precede expensive requests, evidence and target counts."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import weibo_account_filter as gates
from tools.user_hash import anonymize_user_id
from tests.test_weibo_account_filter import raw_comment, raw_note
from tests.semantic_responses import grounded_response
from semantic_filter import StreamingSemanticFilter


def listed_uid(category):
    return next(uid for uid, reason in gates.load_blocklist()[0].items() if reason == 'account_blocklist_' + category)


def test_downloaded_snapshot_counts_and_checksums():
    manifest = json.loads((gates.BLOCKLIST_DIR / 'manifest.json').read_text(encoding='utf-8'))
    for record in manifest['files']:
        raw = (gates.BLOCKLIST_DIR / record['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record['sha256']
        assert len(raw.decode('utf-8-sig').splitlines()) == record['lines']
    assert gates.load_blocklist()[2] == {'bot.txt': 4994, 'media.txt': 781, 'government.txt': 597, 'unique_accounts': 6338}
    assert manifest['unique_accounts'] == 6338


def test_user_added_media_uid_blocks_raw_and_hashed_records_without_name_matching():
    uid = '2272985297'
    assert gates.blocked_uid_reason(uid) == 'account_blocklist_media'
    assert gates.blocked_uid_reason(int(uid)) == 'account_blocklist_media'
    assert gates.account_filter_reason({'idstr': uid, 'screen_name': '账号改名后'}) == 'account_blocklist_media'
    assert gates.blocklist_record_reason({'creator_hash': anonymize_user_id(uid)}) == 'account_blocklist_media'
    assert gates.account_record_identity({'creator_hash': anonymize_user_id(uid)})['status'] == 'excluded'
    assert gates.blocklist_record_reason({'note_id': uid, 'comment_id': uid}) is None
    assert gates.blocked_uid_reason(float(uid)) is None
    assert gates.account_record_reason({'creator_hash': anonymize_user_id('2272985298'), 'nickname': '北京科教_健康北京粉丝'}) is None


@pytest.mark.parametrize('category', ['bot', 'media', 'government'])
def test_exact_author_uid_before_masking_and_hashed_author_afterward(category):
    uid = listed_uid(category)
    expected = 'account_blocklist_' + category
    assert gates.account_filter_reason({'id': int(uid), 'screen_name': '普通昵称'}) == expected
    assert gates.account_filter_reason({'idstr': uid, 'screen_name': '普***称'}) == expected
    assert gates.account_record_reason({'creator_hash': anonymize_user_id(uid), 'nickname': '普通昵称'}) == expected
    assert gates.account_record_reason({'user': {'id': uid}, 'id': 'comment-id'}) == expected
    assert gates.account_record_reason({'author_filter_reason': expected}) == expected
    # A post/comment's ID must never be mistaken for its author's UID.
    assert gates.account_record_reason({'id': uid, 'note_id': uid, 'comment_id': uid, 'nickname': '普通昵称'}) is None
    assert gates.account_filter_reason({'id': '99999999999999999999', 'screen_name': '普通昵称'}) is None
    assert gates.blocked_uid_reason(float(uid)) is None


@pytest.mark.asyncio
async def test_store_drops_all_three_author_categories_even_in_semantic_mode(monkeypatch):
    import store.weibo as wb
    store = SimpleNamespace(store_content=AsyncMock(), store_comment=AsyncMock())
    monkeypatch.setattr(wb.WeibostoreFactory, 'create_store', lambda: store)
    monkeypatch.setattr(wb.config, 'SAVE_DATA_OPTION', 'excel')
    monkeypatch.setattr(wb.config, 'CRAWLER_TYPE', 'search')
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '1')
    for category in ('bot', 'media', 'government'):
        uid = listed_uid(category)
        note = raw_note(category, '普通昵称')
        note['mblog']['user']['id'] = uid
        comment = raw_comment(category, '普通昵称')
        comment['user']['id'] = uid
        await wb.update_weibo_note(note)
        await wb.update_weibo_note_comment('personal-post', comment)
    store.store_content.assert_not_awaited()
    store.store_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_skips_many_blocked_pages_before_details_and_keeps_target(monkeypatch):
    from media_platform.weibo import core
    for name, value in {'KEYWORDS': '可爱 公园', 'START_PAGE': 1, 'CRAWLER_MAX_NOTES_COUNT': 2,
                        'CRAWLER_MAX_SLEEP_SEC': 0, 'SAVE_DATA_OPTION': 'json', 'ENABLE_WEIBO_FULL_TEXT': True}.items():
        monkeypatch.setattr(core.config, name, value)
    monkeypatch.delenv('MEDIACRAWLER_SEMANTIC_FILTER', raising=False)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    async def page(*, page, **kwargs):
        note = raw_note('blocked-' + str(page), '普通昵称')
        note['mblog']['user']['id'] = listed_uid(('bot', 'media', 'government')[page % 3])
        note['mblog']['isLongText'] = True
        return {'cards': [note] + ([raw_note('good-1', '小张'), raw_note('good-2', '小李')] if page == 6 else [])}
    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=page))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.search()
    assert crawler.wb_client.get_note_by_keyword.await_count == 6
    assert [note['mblog']['id'] for note in crawler.batch_get_notes_full_text.await_args.args[0]] == ['good-1', 'good-2']
    assert [call.args[0]['mblog']['id'] for call in saved.await_args_list] == ['good-1', 'good-2']
    assert [call.args[0]['id'] for call in crawler.download_media.await_args_list] == ['good-1', 'good-2']
    crawler.batch_get_notes_comments.assert_awaited_once_with(['good-1', 'good-2'])


@pytest.mark.asyncio
async def test_specified_posts_and_creators_skip_listed_authors(monkeypatch):
    from media_platform.weibo import core
    blocked = raw_note('blocked', '普通昵称')
    blocked['mblog']['user']['id'] = listed_uid('government')
    crawler = core.WeiboCrawler()
    monkeypatch.setattr(core.config, 'WEIBO_SPECIFIED_ID_LIST', ['blocked', 'good'])
    crawler.wb_client = SimpleNamespace()
    crawler.get_note_info_task = AsyncMock(side_effect=[blocked, raw_note('good', '小张')])
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.get_specified_notes()
    crawler.batch_get_notes_comments.assert_awaited_once_with(['good'])
    assert [call.args[0]['id'] for call in crawler.download_media.await_args_list] == ['good']
    assert saved.await_count == 1
    monkeypatch.setattr(core.config, 'WEIBO_CREATOR_ID_LIST', [listed_uid('bot'), listed_uid('media'), listed_uid('government')])
    crawler.wb_client = SimpleNamespace(get_creator_info_by_id=AsyncMock())
    await crawler.get_creators_and_notes()
    crawler.wb_client.get_creator_info_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_listed_comment_cannot_become_semantic_evidence(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(grounded_response)) as client:
        stream = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        await stream.add_note({'note_id': 'n', 'source_keyword': '可爱 公园', 'content': '公园散步', 'image_names': '001.jpg'})
        await stream.add_comment({'note_id': 'n', 'comment_id': 'listed', 'content': '公园里的花坛真可爱', 'creator_hash': anonymize_user_id(listed_uid('bot')), 'nickname': '小张'})
        await stream.finalize_note('n')
        assert not stream.states[('n', '可爱 公园')].comments
        assert stream.states[('n', '可爱 公园')].status == 'excluded'
        assert stream.reviewer.calls == 0
        await stream.close()


@pytest.mark.asyncio
async def test_listed_author_overrides_previous_match_without_more_model_calls(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(grounded_response)) as client:
        stream = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        note = {'note_id': 'n', 'source_keyword': '可爱 公园', 'content': '公园里的花坛真可爱', 'image_names': '001.jpg'}
        await stream.add_note(note)
        await stream.finalize_note('n', interim=True)
        assert stream.states[('n', '可爱 公园')].status == 'matched'
        calls = stream.reviewer.calls
        await stream.add_note({**note, 'creator_hash': anonymize_user_id(listed_uid('media'))})
        await stream.finalize_note('n')
        assert stream.states[('n', '可爱 公园')].source == 'account_blocklist_media'
        assert stream.states[('n', '可爱 公园')].status == 'excluded'
        assert stream.reviewer.calls == calls
        await stream.close()


@pytest.mark.asyncio
async def test_changed_blocklist_invalidates_semantic_checkpoint_identity(tmp_path, monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(grounded_response)) as client:
        first = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        monkeypatch.setattr('semantic_filter.blocklist_signature', lambda: 'changed-list')
        second = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        assert first.checkpoint_path != second.checkpoint_path
        await first.close()
        await second.close()

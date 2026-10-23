"""Account gates must run before masking, models, exports, and quota counting."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openpyxl
import pytest

from semantic_filter import StreamingSemanticFilter
from tests.semantic_responses import grounded_response
from weibo_account_filter import NEWS_MEDIA_REASON, news_media_account_reason


@pytest.mark.parametrize('name', [
    '央视新闻', '澎湃新闻', '某某媒体', '北京融媒体中心', '新浪新闻',
    '人民日报', '新华社', '中新社', '中国青年报', '人民网', '新京报',
    '上海广播电视台', '某地传媒集团', '某地晚报官方微博', '【某地新闻】',
    '人民日报社', '新华网', '新闻联播', '某地新闻资讯',
])
def test_media_names_excluded(name):
    assert news_media_account_reason({'screen_name': name}) == NEWS_MEDIA_REASON


@pytest.mark.parametrize('name', [
    '爱看新闻的小明', '新闻专业学生', '学新闻', '我是新媒体人', '新媒体打工人',
    '人民日报读者', '央视新闻记者小李', '记者小李', '小明看新闻',
    '不想做媒体', '个人小张', '张三', '', '新***闻', '新闻迷', '媒体人',
])
def test_personal_and_masked_names_not_inferred_as_media(name):
    assert news_media_account_reason({'screen_name': name}) is None


def test_verification_needs_media_organization_and_real_badge():
    assert news_media_account_reason({'screen_name': '海报', 'verified': True,
                                     'verified_reason': '某某新闻传媒有限公司官方微博'}) == NEWS_MEDIA_REASON
    assert news_media_account_reason({'screen_name': '小张', 'verified': True,
                                     'verified_reason': '新闻记者，个人官方微博'}) is None
    assert news_media_account_reason({'screen_name': '小张', 'verified': True}) is None
    assert news_media_account_reason({'screen_name': '小张', 'verified': False,
                                     'verified_reason': '某新闻机构官方微博'}) is None
    assert news_media_account_reason({'screen_name': '小张', 'verified': True,
                                     'verified_reason': '某新闻传媒有限公司董事长'}) is None


def raw_note(nid, name, text='公园里的花坛真可爱'):
    return {'mblog': {'id': nid, 'text': text, 'created_at': 'Thu Oct 08 09:00:00 +0800 2026',
                      'user': {'id': 'raw-private-id', 'screen_name': name},
                      'pics': [{'url': 'https://wx4.sinaimg.cn/large/test.jpg'}]}}


def raw_comment(cid, name, text='公园里的花坛真可爱'):
    return {'id': cid, 'text': text, 'created_at': 'Thu Oct 08 09:00:00 +0800 2026',
            'user': {'id': 'raw-comment-user', 'screen_name': name}}


@pytest.mark.asyncio
async def test_raw_store_filters_media_and_preserves_personal_nickname(monkeypatch):
    import store.weibo as wb
    store = SimpleNamespace(store_content=AsyncMock(), store_comment=AsyncMock())
    monkeypatch.setattr(wb.WeibostoreFactory, 'create_store', lambda: store)
    monkeypatch.setattr(wb.config, 'SAVE_DATA_OPTION', 'json')
    await wb.update_weibo_note(raw_note('media', '某某新闻'))
    await wb.update_weibo_note_comment('personal', raw_comment('media-comment', '某某媒体'))
    store.store_content.assert_not_awaited()
    store.store_comment.assert_not_awaited()
    await wb.update_weibo_note_comment('personal', raw_comment('personal-comment', '爱看新闻的小明'))
    record = store.store_comment.await_args.kwargs['comment_item']
    assert record['comment_id'] == 'personal-comment'
    assert record['nickname'] == '爱看新闻的小明'
    assert 'user' not in record and 'screen_name' not in record


@pytest.mark.asyncio
async def test_only_media_comment_cannot_supply_semantic_evidence(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(grounded_response)) as client:
        stream = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        await stream.add_note({'note_id': 'n', 'source_keyword': '可爱 公园', 'content': '公园散步', 'image_names': '001.jpg'})
        await stream.add_comment({'note_id': 'n', 'comment_id': 'media', 'content': '公园好可爱', 'nickname': '某某新闻'})
        await stream.finalize_note('n')
        state = stream.states[('n', '可爱 公园')]
        assert state.status == 'excluded' and not state.comments
        assert stream.reviewer.calls == 0
        await stream.close()


@pytest.mark.asyncio
async def test_media_only_page_still_exhausts_raw_comment_budget(tmp_path, monkeypatch):
    from media_platform.weibo.client import WeiboClient
    from store.excel_store_base import ExcelStoreBase
    import store.weibo as wb
    from media_platform.weibo import core
    monkeypatch.delenv('MEDIACRAWLER_SEMANTIC_FILTER', raising=False)
    monkeypatch.setattr(wb.config, 'SAVE_DATA_PATH', str(tmp_path))
    store = ExcelStoreBase('weibo', 'search')
    monkeypatch.setattr(core.config, 'SAVE_DATA_OPTION', 'excel')
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '1')
    monkeypatch.setattr(ExcelStoreBase, '_instances', {'weibo_search': store})
    monkeypatch.setattr(wb.WeibostoreFactory, 'create_store', lambda: store)
    monkeypatch.setattr(core.config, 'ENABLE_GET_COMMENTS', True)
    monkeypatch.setattr(core.config, 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES', 2)
    monkeypatch.setattr(core.config, 'CRAWLER_MAX_SLEEP_SEC', 0)
    client = object.__new__(WeiboClient)
    client.get_note_comments = AsyncMock(return_value={'max_id': 9, 'data': [
        raw_comment('a', '某地新闻'), raw_comment('b', '某地媒体'), raw_comment('c', '新华社')]})
    crawler = core.WeiboCrawler()
    crawler.wb_client = client
    async with httpx.AsyncClient(transport=httpx.MockTransport(grounded_response)) as model_client:
        store.semantic_stream = StreamingSemanticFilter(store.filename, [('可爱', '公园')], 'fake', client=model_client, comment_budget=2)
        await store.store_content({'note_id': 'n', 'source_keyword': '可爱 公园', 'content': '公园散步', 'image_names': '001.jpg'})
        await crawler.batch_get_notes_comments(['n'])
        state = store.semantic_stream.states[('n', '可爱 公园')]
        assert state.status == 'excluded' and state.source == 'keyword_miss'
        assert state.note['semantic_comment_stop_reason'] == 'comment_budget_exhausted'
        assert 'selection_origin' not in state.note
        assert not state.comments and not store._semantic_pending_comments
        assert store.semantic_stream.reviewer.calls == 0
        client.get_note_comments.assert_awaited_once()
        await store.semantic_stream.close()


@pytest.mark.asyncio
async def test_search_media_exclusion_quota_model_and_export(tmp_path, monkeypatch):
    import config
    from media_platform.weibo import core
    from media_platform.weibo.client import WeiboClient
    from store.excel_store_base import ExcelStoreBase
    for name, value in {'KEYWORDS': '可爱 公园', 'START_PAGE': 1, 'CRAWLER_TYPE': 'search',
                        'CRAWLER_MAX_NOTES_COUNT': 1, 'CRAWLER_MAX_SLEEP_SEC': 0,
                        'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES': 10, 'ENABLE_GET_COMMENTS': True,
                        'ENABLE_WEIBO_FULL_TEXT': True, 'SAVE_DATA_OPTION': 'excel',
                        'SAVE_DATA_PATH': str(tmp_path)}.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.delenv('MEDIACRAWLER_SEMANTIC_FILTER', raising=False)
    store = ExcelStoreBase('weibo', 'search')
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '1')
    monkeypatch.setattr(ExcelStoreBase, '_instances', {'weibo_search': store})
    monkeypatch.setattr(core.weibo_store.WeibostoreFactory, 'create_store', lambda: store)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    media = raw_note('media-post', '新浪新闻')
    media['mblog']['isLongText'] = True
    client = object.__new__(WeiboClient)
    client.get_note_by_keyword = AsyncMock(return_value={'cards': [media, raw_note('personal-post', '爱看新闻的小明', '公园散步')]})
    client.get_note_info_by_id = AsyncMock()
    client.get_note_comments = AsyncMock(return_value={'max_id': 8, 'data': [
        raw_comment('media-hit', '澎湃新闻'), raw_comment('personal-hit', '小明')]})
    crawler = core.WeiboCrawler()
    crawler.wb_client = client
    crawler.download_media = AsyncMock()
    seen = []
    def respond(request):
        seen.append(request.content.decode())
        return grounded_response(request, source='comment:personal-hit')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as model_client:
        store.semantic_stream = StreamingSemanticFilter(store.filename, [('可爱', '公园')], 'fake', client=model_client)
        await crawler.search()
        states = store.semantic_stream.states
        assert states[('media-post', '可爱 公园')].source == NEWS_MEDIA_REASON
        assert states[('personal-post', '可爱 公园')].status == 'matched'
        assert states[('personal-post', '可爱 公园')].matched_comment['comment_id'] == 'personal-hit'
        assert all('media-hit' not in payload for payload in seen)
        assert all('raw-private-id' not in payload for payload in seen)
        client.get_note_info_by_id.assert_not_awaited()
        assert [call.args[0] for call in client.get_note_comments.await_args_list] == ['personal-post']
        assert [call.args[0]['id'] for call in crawler.download_media.await_args_list] == ['personal-post']
        await store.semantic_stream.close()
    store.flush()
    book = openpyxl.load_workbook(store.filename, read_only=True)
    def rows(name):
        iterator = iter(book[name].values)
        headers = next(iterator)
        return [dict(zip(headers, row)) for row in iterator]
    assert [row['note_id'] for row in rows('Contents')] == ['personal-post']
    assert [row['comment_id'] for row in rows('Comments')] == ['personal-hit']
    book.close()


@pytest.mark.asyncio
async def test_new_media_flag_overrides_same_run_cached_match(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(grounded_response)) as client:
        stream = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        note = {'note_id': 'n', 'source_keyword': '可爱 公园', 'content': '公园里的花坛真可爱', 'image_names': '001.jpg'}
        await stream.add_note(note)
        await stream.finalize_note('n', False, interim=True)
        assert stream.states[('n', '可爱 公园')].status == 'matched'
        calls = stream.reviewer.calls
        await stream.add_note({**note, 'author_filter_reason': NEWS_MEDIA_REASON})
        await stream.finalize_note('n')
        assert stream.states[('n', '可爱 公园')].status == 'excluded'
        assert stream.reviewer.calls == calls
        await stream.close()


@pytest.mark.asyncio
async def test_normal_search_continues_after_many_media_pages(monkeypatch):
    from media_platform.weibo import core
    for name, value in {'KEYWORDS': '可爱 公园', 'START_PAGE': 1,
                        'CRAWLER_MAX_NOTES_COUNT': 1, 'CRAWLER_MAX_SLEEP_SEC': 0,
                        'SAVE_DATA_OPTION': 'json', 'ENABLE_WEIBO_FULL_TEXT': True}.items():
        monkeypatch.setattr(core.config, name, value)
    monkeypatch.setattr(core, 'filter_search_result_card', lambda cards: cards)
    async def page(*, page, **kwargs):
        return {'cards': [raw_note(str(page), '某地新闻' if page < 5 else '小张')]}
    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=page))
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.search()
    assert [call.kwargs['page'] for call in crawler.wb_client.get_note_by_keyword.await_args_list] == [1, 2, 3, 4, 5]
    crawler.batch_get_notes_comments.assert_awaited_once_with(['5'])
    assert [call.args[0]['id'] for call in crawler.download_media.await_args_list] == ['5']


@pytest.mark.asyncio
async def test_specified_posts_skip_media_comments_and_downloads(monkeypatch):
    from media_platform.weibo import core
    monkeypatch.setattr(core.config, 'WEIBO_SPECIFIED_ID_LIST', ['media', 'personal'])
    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace()
    crawler.get_note_info_task = AsyncMock(side_effect=[raw_note('media', '某地媒体'), raw_note('personal', '小张')])
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'update_weibo_note', saved)
    await crawler.get_specified_notes()
    crawler.batch_get_notes_comments.assert_awaited_once_with(['personal'])
    assert [call.args[0]['mblog']['id'] for call in saved.await_args_list] == ['personal']
    assert [call.args[0]['id'] for call in crawler.download_media.await_args_list] == ['personal']


@pytest.mark.asyncio
async def test_creator_mode_skips_media_creator_and_media_posts(monkeypatch):
    from media_platform.weibo import core
    monkeypatch.setattr(core.config, 'WEIBO_CREATOR_ID_LIST', ['media-creator', 'personal-creator'])
    crawler = core.WeiboCrawler()
    notes = [raw_note('media', '某地新闻'), raw_note('personal', '小张')]
    async def fetch_notes(**kwargs):
        await kwargs['callback'](notes)
        return notes
    crawler.wb_client = SimpleNamespace(
        get_creator_info_by_id=AsyncMock(side_effect=[{'userInfo': {'screen_name': '某地媒体'}}, {'userInfo': {'screen_name': '小张'}}]),
        get_all_notes_by_creator_id=AsyncMock(side_effect=fetch_notes))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, 'batch_update_weibo_notes', saved)
    await crawler.get_creators_and_notes()
    assert crawler.wb_client.get_all_notes_by_creator_id.await_count == 1
    assert [note['mblog']['id'] for note in saved.await_args.args[0]] == ['personal']
    crawler.batch_get_notes_comments.assert_awaited_once_with(['personal'])
    assert [call.args[0]['id'] for call in crawler.download_media.await_args_list] == ['personal']

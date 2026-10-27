"""Run the actual streaming decisions with bounded, simulated comment responses."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio

from media_platform.xhs import core
from semantic_filter import StreamingSemanticFilter
from store.excel_store_base import ExcelStoreBase


@pytest_asyncio.fixture
async def sampling(monkeypatch, tmp_path):
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '1')
    monkeypatch.delenv('MEDIACRAWLER_COLLECTION_RUN', raising=False)
    monkeypatch.setattr(core.config, 'SAVE_DATA_OPTION', 'excel')
    monkeypatch.setattr(core.config, 'CRAWLER_MAX_SLEEP_SEC', 0)
    monkeypatch.setattr(core.config, 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES', 10000)
    monkeypatch.setattr(core.config, 'ENABLE_GET_SUB_COMMENTS', True)
    clients = []

    def create(rule='scene', body_choice='review', comment_choice='review', failure=False):
        requests = []
        def respond(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if failure:
                return httpx.Response(503)
            if 'support' in payload['questions']:
                return httpx.Response(200, json={'answers': {'support': {'choice': 'supported', 'confidence': .95}}})
            options = payload['questions']['evidence_text']['criteria']
            keys = [key for key in options if key != 'unclear']
            has_comments = '一级评论' in payload['state']['text']
            choice = comment_choice if has_comments else body_choice
            return httpx.Response(200, json={'answers': {
                'relation': {'choice': choice, 'confidence': .95 if choice != 'review' else .5},
                'evidence_text': {'choice': keys[-1]},
                'target_evidence': {'choice': keys[0]},
            }})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        clients.append(client)
        pair = ('避雷', '武汉') if rule == 'scene' else ('武汉消费体验', '')
        stream = StreamingSemanticFilter(tmp_path/f'{len(clients)}.xlsx', [pair], 'fixture-key', client=client, semantic_rule=rule)
        stream.reviewer.request_attempts = 1
        monkeypatch.setattr(ExcelStoreBase, '_instances', {'xhs_search': SimpleNamespace(
            semantic_stream=stream, _write_retained_semantic_note=Mock())})
        saved = []
        async def save(note_id, comments):
            saved.extend(comments)
            for comment in comments:
                await stream.add_comment({'note_id': note_id, 'comment_id': comment['id'], 'content': comment['content']})
        monkeypatch.setattr(core.xhs_store, 'batch_update_xhs_note_comments', save)
        crawler = core.XiaoHongShuCrawler()
        crawler._semantic_comments_remaining = 30
        crawler.xhs_client = SimpleNamespace(
            get_note_comments=AsyncMock(return_value={'has_more': True, 'cursor': 'next', 'comments': [
                {'id': str(i), 'content': '武汉这次消费体验必须避雷',
                 'sub_comments': [{'content': 'reply'}] * 100} for i in range(20)]}),
            get_note_all_comments=AsyncMock(), get_comments_all_sub_comments=AsyncMock())
        return SimpleNamespace(crawler=crawler, stream=stream, pair=pair, saved=saved, requests=requests)

    yield create
    for client in clients:
        await client.aclose()


async def screen(fixture, note_id='1'):
    await fixture.stream.add_note({'note_id': note_id, 'source_keyword': ' '.join(fixture.pair).strip(),
        'title': f'武汉体验记录{note_id}', 'desc': '武汉这次的消费体验需要避雷'})
    await fixture.crawler.get_comments(note_id, 'fixture-token', asyncio.Semaphore(1))
    return fixture.stream.states[(note_id, ' '.join(fixture.pair).strip())]


@pytest.mark.asyncio
@pytest.mark.parametrize('rule', ['topic', 'scene'])
@pytest.mark.parametrize('choice,status', [('keep', 'matched'), ('reject', 'excluded')])
async def test_body_decision_skips_all_comment_requests(sampling, rule, choice, status):
    fixture = sampling(rule, body_choice=choice)
    state = await screen(fixture)
    assert state.status == status
    fixture.crawler.xhs_client.get_note_comments.assert_not_awaited()
    fixture.crawler.xhs_client.get_note_all_comments.assert_not_awaited()
    assert not fixture.saved


@pytest.mark.asyncio
@pytest.mark.parametrize('rule', ['topic', 'scene'])
async def test_uncertain_body_uses_only_five_top_level_comments_then_can_match(sampling, rule):
    fixture = sampling(rule, comment_choice='keep')
    state = await screen(fixture)
    assert '一级评论' not in fixture.requests[0]['state']['text']
    assert state.status == 'matched'
    assert len(fixture.saved) == len(state.comments) == 5
    assert state.note['comments_collection_complete'] is False
    assert all('sub_comments' not in item for item in fixture.saved)
    fixture.crawler.xhs_client.get_note_comments.assert_awaited_once()
    assert fixture.crawler.xhs_client.get_note_comments.await_args.kwargs['cursor'] == ''
    fixture.crawler.xhs_client.get_note_all_comments.assert_not_awaited()
    fixture.crawler.xhs_client.get_comments_all_sub_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_six_post_goal_never_samples_more_than_thirty_comments(sampling):
    fixture = sampling()
    for i in range(12):
        state = await screen(fixture, str(i))
        assert state.status == 'review'
    assert len(fixture.saved) == 30
    assert fixture.crawler._semantic_comments_remaining == 0
    assert fixture.crawler.xhs_client.get_note_comments.await_count == 6
    assert all(state.status != 'matched' for state in fixture.stream.states.values())


@pytest.mark.asyncio
async def test_empty_first_page_does_not_follow_more_pages(sampling):
    fixture = sampling()
    fixture.crawler.xhs_client.get_note_comments.return_value = {'has_more': True, 'cursor': 'changing', 'comments': []}
    state = await screen(fixture)
    fixture.crawler.xhs_client.get_note_comments.assert_awaited_once()
    assert state.status == 'review'
    assert fixture.crawler._semantic_comments_remaining == 30


@pytest.mark.asyncio
async def test_model_failure_does_not_trigger_comment_collection(sampling):
    fixture = sampling(failure=True)
    state = await screen(fixture)
    assert state.status == 'pending'
    fixture.crawler.xhs_client.get_note_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_sampling_budget_is_reserved_before_network_awaits(sampling):
    fixture = sampling()
    fixture.crawler._semantic_comments_remaining = 3
    await asyncio.gather(*(screen(fixture, str(i)) for i in range(4)))
    assert len(fixture.saved) == 3
    assert fixture.crawler.xhs_client.get_note_comments.await_count == 1


@pytest.mark.asyncio
async def test_normal_collection_keeps_original_comment_behavior(sampling, monkeypatch):
    fixture = sampling()
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER', '0')
    monkeypatch.setattr(ExcelStoreBase, '_instances', {})
    await fixture.crawler.get_comments('1', 'fixture-token', asyncio.Semaphore(1))
    fixture.crawler.xhs_client.get_note_all_comments.assert_awaited_once()
    assert fixture.crawler.xhs_client.get_note_all_comments.await_args.kwargs['max_count'] == 10000
    fixture.crawler.xhs_client.get_note_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_weibo_sample_has_same_page_reply_and_topic_budget_limits(sampling, monkeypatch):
    from media_platform.weibo import core as weibo
    from media_platform.weibo.client import WeiboClient
    fixture = sampling(comment_choice='keep')
    instance = ExcelStoreBase._instances['xhs_search']
    monkeypatch.setattr(ExcelStoreBase, '_instances', {'weibo_search': instance})
    await fixture.stream.add_note({'note_id': '1', 'source_keyword': '避雷 武汉',
                                  'title': '武汉消费体验需要避雷'})
    assert await ExcelStoreBase.review_semantic_note('weibo', '1') is None
    client = WeiboClient.__new__(WeiboClient)
    client.get_note_comments = AsyncMock(return_value={'max_id': 100, 'data': [
        {'id': str(i), 'content': '武汉消费体验需要避雷'} for i in range(20)]})
    client.get_comments_all_sub_comments = AsyncMock()
    captured = []

    async def save(note_id, comments):
        captured.extend(comments)
        for comment in comments:
            await fixture.stream.add_comment({'note_id': note_id, 'comment_id': comment['id'], 'content': comment['content']})

    monkeypatch.setattr(weibo.weibo_store, 'batch_update_weibo_note_comments', save)
    crawler = weibo.WeiboCrawler()
    crawler.wb_client = client
    crawler._semantic_comments_remaining = 3
    await crawler.get_note_comments('1', asyncio.Semaphore(1))
    assert len(captured) == 3
    assert crawler._semantic_comments_remaining == 0
    client.get_note_comments.assert_awaited_once()
    client.get_comments_all_sub_comments.assert_not_awaited()
    assert fixture.stream.states[('1', '避雷 武汉')].status == 'matched'


@pytest.mark.asyncio
async def test_weibo_body_pass_does_not_collect_delivery_comments(sampling, monkeypatch):
    from media_platform.weibo import core as weibo
    fixture = sampling(body_choice='keep')
    instance = ExcelStoreBase._instances['xhs_search']
    monkeypatch.setattr(ExcelStoreBase, '_instances', {'weibo_search': instance})
    monkeypatch.setattr(weibo.config, 'KEYWORDS', '避雷 武汉')
    monkeypatch.setattr(weibo.config, 'START_PAGE', 1)
    monkeypatch.setattr(weibo.config, 'CRAWLER_MAX_NOTES_COUNT', 1)
    monkeypatch.setattr(weibo, 'filter_search_result_card', lambda cards: cards)
    monkeypatch.setattr(weibo.weibo_store, 'account_filter_reason', lambda user: None)
    async def save(item):
        await fixture.stream.add_note({'note_id': item['mblog']['id'], 'source_keyword': '避雷 武汉',
                                      'title': '武汉消费体验需要避雷'})
    monkeypatch.setattr(weibo.weibo_store, 'update_weibo_note', save)
    crawler = weibo.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(return_value={'cards': [{'mblog': {'id': '1'}}]}))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.prepare_note = AsyncMock(side_effect=lambda note: note)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    await crawler.search()
    crawler.batch_get_notes_comments.assert_not_awaited()
    assert fixture.stream.states[('1', '避雷 武汉')].status == 'matched'

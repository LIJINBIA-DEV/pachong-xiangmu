"""Replay failed comments, review media selection and recovery of human marks."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from tenacity import wait_none


@pytest.mark.asyncio
async def test_filtered_comments_are_recorded_once_without_secrets(tmp_path, monkeypatch):
    from media_platform.weibo import core, client as module
    from store.excel_store_base import ExcelStoreBase
    from collection_tasks import create_task, prepare_run
    from api.services.collection_logs import collection_logs

    path=tmp_path/'weibo/posts.json'
    path.parent.mkdir()
    path.write_text('[]')
    task=create_task(tmp_path,{}, {'可爱 公园':1},'weibo/posts.json')
    run=prepare_run(tmp_path,task,task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN',str(run))
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER','1')
    monkeypatch.setattr(core.config,'SAVE_DATA_PATH',str(tmp_path))
    monkeypatch.setattr(core.config,'SAVE_DATA_OPTION','excel')
    monkeypatch.setattr(core.config,'CRAWLER_MAX_SLEEP_SEC',0)
    monkeypatch.setattr(core.config,'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES',20)
    monkeypatch.setattr(module.WeiboClient,'request',module.WeiboClient.request.retry_with(wait=wait_none()))
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'ok':0,'msg':'已过滤部分评论'})
    monkeypatch.setattr(module,'make_async_client',lambda proxy: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    crawler=core.WeiboCrawler()
    crawler.wb_client=module.WeiboClient(headers={'Cookie':'SUB=secret-cookie'},playwright_page=None,cookie_dict={})
    finalize=AsyncMock()
    monkeypatch.setattr(ExcelStoreBase,'finalize_semantic_note',finalize)
    await crawler.get_note_comments('123',asyncio.Semaphore(1))
    assert len(calls)==1  # Filtered comments are unavailable; identical retries cannot fix this.
    event=collection_logs(tmp_path,path)['comment_events'][0]
    assert event['note_id']=='123' and event['reason']=='platform_filtered'
    assert event['http_status']==200 and event['api_ok']==0
    assert event['response_message']=='已过滤部分评论' and event['request_count']==1
    assert event['exception_type']=='CommentsUnavailable'
    assert finalize.await_args.kwargs['comment_stop_reason']=='comments_fetch_failed'
    assert 'secret-cookie' not in ''.join(p.read_text(encoding='utf-8') for p in (tmp_path/'.comment-audit').rglob('*.json'))


@pytest.mark.asyncio
async def test_review_posts_download_without_counting_as_passed(monkeypatch):
    from media_platform.weibo import core
    from store.excel_store_base import ExcelStoreBase
    monkeypatch.delenv('MEDIACRAWLER_COLLECTION_RUN',raising=False)
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER','1')
    for key,value in {'KEYWORDS':'可爱 公园','START_PAGE':1,'CRAWLER_MAX_NOTES_COUNT':1,
                      'CRAWLER_MAX_SLEEP_SEC':0,'SAVE_DATA_OPTION':'excel','ENABLE_GET_COMMENTS':True}.items():
        monkeypatch.setattr(core.config,key,value)
    states={(nid,'可爱 公园'):SimpleNamespace(status=None) for nid in ('review','bad','good')}
    instance=SimpleNamespace(semantic_stream=SimpleNamespace(states=states,active_keys=set(states),note_keys={nid:[(nid,'可爱 公园')] for nid in ('review','bad','good')}))
    monkeypatch.setattr(ExcelStoreBase,'_instances',{'weibo_search':instance})
    monkeypatch.setattr(ExcelStoreBase,'semantic_note_completed',lambda *a:False)
    monkeypatch.setattr(ExcelStoreBase,'review_semantic_note',AsyncMock(return_value=None))
    monkeypatch.setattr(core,'filter_search_result_card',lambda cards:cards)
    monkeypatch.setattr(core.weibo_store,'update_weibo_note',AsyncMock())
    cards=[{'mblog':{'id':nid}} for nid in ('review','bad','good')]
    crawler=core.WeiboCrawler()
    crawler.wb_client=SimpleNamespace(get_note_by_keyword=AsyncMock(return_value={'cards':cards}))
    crawler.batch_get_notes_full_text=AsyncMock(side_effect=lambda rows:rows)
    async def comments(ids):
        for nid in ids:
            states[(nid,'可爱 公园')].status={'review':'review','bad':'excluded','good':'matched'}[nid]
    crawler.batch_get_notes_comments=AsyncMock(side_effect=comments)
    crawler.download_media=AsyncMock()
    await crawler.search()
    assert [call.args[0]['id'] for call in crawler.download_media.await_args_list]==['review','good']
    assert crawler.wb_client.get_note_by_keyword.await_count==1
    assert not ExcelStoreBase.semantic_note_retained('weibo','review','可爱 公园')


def test_diagnostics_distinguish_timeout_cursor_and_redact_messages(tmp_path):
    from comment_audit import failure_details,record_result,events
    from media_platform.weibo.exception import DataFetchError
    timeout=failure_details(httpx.ReadTimeout('Cookie: private-cookie'),{'http_status':None,'request_count':5})
    assert timeout['reason']=='network_timeout' and timeout['exception_type']=='ReadTimeout'
    cursor=failure_details(DataFetchError('Missing comment cursor for note 1; comment collection is incomplete'),{'http_status':200,'api_ok':1})
    assert cursor['reason']=='cursor_missing'
    record_result('1',{**cursor,'response_message':'验证失败 Cookie: secret-cookie sk-abcdefghijk https://example.com/?token=secret-url'},root=tmp_path,source_file='weibo/posts.json')
    rows=events(tmp_path,['weibo/posts.json'])
    assert len(rows)==1 and rows[0]['http_status']==200
    assert all(secret not in json.dumps(rows) for secret in ('secret-cookie','sk-abcdefghijk','secret-url'))


@pytest.mark.asyncio
async def test_login_failure_is_recorded_and_still_pauses(tmp_path,monkeypatch):
    from media_platform.weibo import core
    from media_platform.weibo.exception import LoginRequired
    from store.excel_store_base import ExcelStoreBase
    monkeypatch.delenv('MEDIACRAWLER_COLLECTION_RUN',raising=False)
    monkeypatch.setattr(core.config,'SAVE_DATA_PATH',str(tmp_path))
    monkeypatch.setattr(core.config,'SAVE_DATA_OPTION','excel')
    monkeypatch.setattr(core.config,'CRAWLER_MAX_SLEEP_SEC',0)
    crawler=core.WeiboCrawler()
    crawler.wb_client=SimpleNamespace(get_note_all_comments=AsyncMock(side_effect=LoginRequired()))
    monkeypatch.setattr(ExcelStoreBase,'finalize_semantic_note',AsyncMock())
    with pytest.raises(LoginRequired):
        await crawler.get_note_comments('1',asyncio.Semaphore(1))
    rows=list((tmp_path/'.comment-audit/events').glob('*.json'))
    assert json.loads(rows[0].read_text(encoding='utf-8'))['reason']=='login_required'

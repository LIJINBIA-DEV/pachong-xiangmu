import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from semantic_filter import StreamingSemanticFilter
from tests.semantic_responses import grounded_response


@pytest.mark.asyncio
@pytest.mark.parametrize('full_text', [True, False])
@pytest.mark.parametrize('stop', ['comments_fetch_failed', None])
async def test_missing_pair_is_excluded_even_when_evidence_fetch_failed(tmp_path,full_text,stop):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:pytest.fail('No pair, no Jev call'))) as client:
        stream=StreamingSemanticFilter(tmp_path/'run.xlsx',[('可爱','公园')],'fake',client=client)
        await stream.add_note({'note_id':'n','source_keyword':'可爱 公园','content':'第一张太可爱了',
                               'image_names':'001.jpg','semantic_full_text_available':full_text})
        await stream.finalize_note('n',False,interim=True)
        await stream.add_comment({'note_id':'n','comment_id':'1','content':'可爱'})
        await stream.finalize_note('n',False,comment_stop_reason=stop)
        state=stream.states[('n','可爱 公园')]
        assert state.status=='excluded' and state.source=='keyword_miss'
        assert state.quality_reason=='keyword_miss' and not state.matched
        if stop:assert state.note['semantic_comment_stop_reason']==stop
        await stream.close()
        assert stream.states[('n','可爱 公园')].status=='excluded'


@pytest.mark.asyncio
async def test_previously_written_body_pass_is_removed_after_comment_failure(tmp_path,monkeypatch):
    import config
    from store.excel_store_base import ExcelStoreBase
    monkeypatch.setattr(config,'SAVE_DATA_PATH',str(tmp_path))
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER','0')
    store=ExcelStoreBase('weibo','search')
    monkeypatch.setattr(ExcelStoreBase,'_instances',{'weibo_search':store})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:grounded_response(r))) as client:
        store.semantic_stream=StreamingSemanticFilter(store.filename,[('可爱','公园')],'fake',client=client)
        await store.store_content({'note_id':'n','source_keyword':'可爱 公园','content':'公园雕塑真可爱','image_names':'001.jpg'})
        await ExcelStoreBase.review_semantic_note('weibo','n')
        assert store.contents_sheet.max_row==2
        await store.store_comment({'note_id':'n','comment_id':'1','content':'好看'})
        await ExcelStoreBase.finalize_semantic_note('weibo','n',False,comment_stop_reason='comments_fetch_failed')
        state=store.semantic_stream.states[('n','可爱 公园')]
        assert state.status=='excluded' and state.source=='comments_fetch_failed'
        assert store.contents_sheet.max_row==1
        assert not ExcelStoreBase.semantic_note_retained('weibo','n','可爱 公园')
        await store.semantic_stream.close()


@pytest.mark.asyncio
async def test_real_dual_keyword_review_survives_successful_comment_fetch(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:grounded_response(r,'review',kind='unclear',relation='unclear',confidence=None))) as client:
        stream=StreamingSemanticFilter(tmp_path/'run.xlsx',[('可爱','公园')],'fake',client=client)
        await stream.add_note({'note_id':'n','source_keyword':'可爱 公园','content':'公园也许可爱','image_names':'001.jpg'})
        await stream.finalize_note('n',True,comment_stop_reason='comments_exhausted')
        assert stream.states[('n','可爱 公园')].status=='matched'
        assert stream.states[('n','可爱 公园')].note['manual_review_required']
        await stream.close()

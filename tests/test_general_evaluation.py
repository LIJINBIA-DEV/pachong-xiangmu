"""General evaluation uses grounded relations without spatial/image restrictions."""
import hashlib
import json

import httpx
import pytest

from semantic_filter import StreamingSemanticFilter
from semantic_rules import EVALUATION_RULE_VERSION
from semantic_quality import saved_collection_rejection
from api.services.manual_review import annotations, update_annotation, review_outcome


def responder(*, choice='keep', confidence=.95, evidence=True, support='supported'):
    def respond(request):
        payload = json.loads(request.content)
        assert payload['state']['evaluation']
        assert payload['state']['target']
        assert 'target_scope' not in payload['state']
        if 'support' in payload['questions']:
            return httpx.Response(200, json={'answers': {'support': {'choice': support, 'confidence': .95}}})
        assert 'object_type' not in payload['questions']
        options = [key for key in payload['questions']['evidence_text']['criteria'] if key != 'unclear']
        return httpx.Response(200, json={'answers': {
            'relation': {'choice': choice, 'confidence': confidence},
            'evidence_text': {'choice': options[-1] if evidence else 'invented-id'},
            'target_evidence': {'choice': options[0] if evidence else 'invented-id'},
        }})
    return respond


@pytest.mark.asyncio
@pytest.mark.parametrize(('pair', 'title', 'body'), [
    (('认真', '老师'), '这位老师的课', '他备课非常认真'),
    (('可爱', '宠物狗'), '我家的宠物狗', '它睡觉的样子可爱极了'),
    (('美味', '蛋糕'), '今天的蛋糕', '吃起来特别美味'),
    (('可靠', '服务'), '评价这项服务', '实际用起来很可靠'),
    (('公平', '制度'), '这项制度', '对所有人的安排都很公平'),
    (('不好', '方案'), '试过这个方案', '实际效果不好'),
])
async def test_any_target_can_match_without_images(tmp_path, pair, title, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder())) as client:
        query = ' '.join(pair)
        stream = StreamingSemanticFilter(tmp_path/'posts.xlsx', [pair], 'test-key', client=client, semantic_rule='scene')
        await stream.add_note({'note_id': '1', 'source_keyword': query, 'title': title, 'desc': body, 'image_list': ''})
        await stream.finalize_note('1')
        state = stream.states[('1', query)]
        assert state.status == 'matched'
        assert state.note['semantic_rule_version'] == EVALUATION_RULE_VERSION
        assert saved_collection_rejection({**state.note, 'semantic_result': 'matched'}) is None
        # Reopening preserves the new-rule decision and grounded evidence.
        reopened = StreamingSemanticFilter(tmp_path/'posts.xlsx', [pair], 'test-key', client=client, semantic_rule='scene')
        assert reopened.states[('1', query)].note['evaluation_evidence'] == state.note['evaluation_evidence']
        await stream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('options','status'), [
    ({'choice': 'reject'}, 'excluded'),
    ({'confidence': .4}, 'review'),
    ({'choice': 'review'}, 'review'),
    ({'support': 'contradicted'}, 'excluded'),
    ({'support': 'unclear'}, 'review'),
    ({'evidence': False}, 'review'),
])
async def test_uncertainty_and_unsupported_relations_never_match(tmp_path, options, status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder(**options))) as client:
        stream = StreamingSemanticFilter(tmp_path/'posts.xlsx', [('认真','老师')], 'test-key', client=client, semantic_rule='scene')
        await stream.add_note({'note_id':'1','source_keyword':'认真 老师','content':'这位老师备课很认真'})
        await stream.finalize_note('1')
        assert stream.states[('1','认真 老师')].status == status
        await stream.close()


@pytest.mark.asyncio
async def test_text_only_review_export_and_old_file_preservation(tmp_path):
    from api.services.review_export import export_review
    from api.services.data_browser import load_review_dataset
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder())) as client:
        stream = StreamingSemanticFilter(tmp_path/'posts.xlsx', [('可爱','宠物狗')], 'test-key', client=client, semantic_rule='scene')
        await stream.add_note({'note_id':'1','source_keyword':'可爱 宠物狗','content':'我家的宠物狗真可爱','note_url':'https://www.xiaohongshu.com/explore/1'})
        await stream.finalize_note('1')
        await stream.close()
    path = stream.output_path
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    notes, _ = load_review_dataset(tmp_path,path)
    assert notes[0]['semantic_rule'] == 'evaluation'
    entry = annotations(tmp_path,path)['entries']['1:可爱 宠物狗']
    assert entry['requires_images'] is False
    assert entry['decision'] == 'qualified' and entry['automatic_decision_reason'] == 'semantic_passed'
    update_annotation(tmp_path,path,'1:可爱 宠物狗','post','qualified')
    assert annotations(tmp_path,path)['entries']['1:可爱 宠物狗']['decision'] == 'qualified'
    assert export_review(tmp_path,path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert review_outcome('non_marketing',[],{}) == (None,'text_review_pending')
    assert review_outcome('marketing',[],{},requires_images=False) == ('unqualified','marketing')


def test_forged_saved_evidence_still_fails():
    assert saved_collection_rejection({'semantic_rule':'evaluation','semantic_result':'matched','content':'这只宠物狗真可爱',
        'evaluation_evidence':'凭空生成的评价','evaluation_target_evidence':'这只宠物狗'}) == 'keyword_miss'


@pytest.mark.asyncio
async def test_later_rejected_chunk_does_not_override_grounded_review(tmp_path):
    calls = 0
    def respond(request):
        nonlocal calls
        calls += 1
        return responder(choice='review' if calls == 1 else 'reject')(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        stream = StreamingSemanticFilter(tmp_path/'posts.xlsx',[('认真','老师')],'key',client=client,semantic_rule='scene')
        await stream.add_note({'note_id':'1','source_keyword':'认真 老师','title':'老师的备课很认真', 'desc': '其他记录。'*1200})
        await stream.finalize_note('1')
        state = stream.states[('1','认真 老师')]
        assert calls > 1 and state.status == 'review'
        assert state.note['jev_original_choice'] == 'review'
        stream.save()
        assert annotations(tmp_path,stream.output_path)['entries']['1:认真 老师']['semantic_rejection_reason'] is None
        await stream.close()


@pytest.mark.asyncio
async def test_main_workbook_keeps_general_rule_and_evidence(tmp_path, monkeypatch):
    from store.excel_store_base import ExcelStoreBase
    from api.services.data_browser import load_dataset
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path))
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_FILTER','0')
    monkeypatch.setattr(ExcelStoreBase, '_instances', {})
    store = ExcelStoreBase('xhs','search')
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder())) as client:
        stream = StreamingSemanticFilter(store.filename,[('可靠','服务')],'key',client=client,semantic_rule='scene')
        store.semantic_stream = stream
        note = {'note_id':'1','source_keyword':'可靠 服务','content':'这项服务很可靠','image_list':''}
        await store.store_content(note)
        await stream.finalize_note('1')
        store._write_retained_semantic_note('1')
        store.flush()
        notes, _ = load_dataset(store.filename)
        assert notes[0]['semantic_rule'] == 'evaluation'
        assert notes[0]['semantic_rule_version'] == EVALUATION_RULE_VERSION
        assert saved_collection_rejection(notes[0]) is None
        assert annotations(tmp_path,store.filename)['entries']['1:可靠 服务']['requires_images'] is False
        await stream.close()

"""Topic relevance must not reuse scene or exact co-occurrence gates."""
import json

import httpx
import pytest

from semantic_filter import StreamingSemanticFilter
from semantic_quality import saved_collection_rejection


@pytest.mark.asyncio
@pytest.mark.parametrize(('choice', 'confidence', 'evidence', 'status'), [
    ('keep', .95, True, 'matched'),
    ('keep', .95, False, 'excluded'),
    ('keep', .4, True, 'review'),
    ('reject', .95, True, 'excluded'),
])
async def test_topic_requires_grounded_confident_relevance(tmp_path, choice, confidence, evidence, status):
    sent = []

    def respond(request):
        payload = json.loads(request.content)
        sent.append(payload)
        assert payload['state']['topic'] == '苏州 房价'
        assert 'target_scope' not in payload['state']
        options = payload['questions']['evidence_text']['criteria']
        selected = next(key for key in options if key != 'unclear') if evidence else 'unclear'
        return httpx.Response(200, json={'answers': {
            'relation': {'choice': choice, 'confidence': confidence},
            'evidence_text': {'choice': selected},
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        stream = StreamingSemanticFilter(tmp_path/'xhs.xlsx', [('苏州', '房价')], 'test-key',
                                         client=client, semantic_rule='topic')
        # Related concepts may be spread across fields and need not literally say 房价.
        await stream.add_note({'note_id': '1', 'title': '苏州楼市',
                               'desc': '园区住宅总价约三百万元', 'image_list': '',
                               'source_keyword': '苏州 房价'})
        await stream.finalize_note('1')
        state = stream.states[('1', '苏州 房价')]
        assert state.status == status
        assert len(sent) == 1
        if status == 'matched':
            assert saved_collection_rejection({**state.note, 'semantic_result': 'matched'}) is None
            assert stream.rule_version == 'topic-relevance-v1'
        await stream.close()


@pytest.mark.asyncio
async def test_topic_checkpoint_does_not_reuse_scene_rejections(tmp_path):
    async with httpx.AsyncClient() as client:
        scene = StreamingSemanticFilter(tmp_path/'scene.xlsx', [('苏州', '房价')], 'key', client=client)
        topic = StreamingSemanticFilter(tmp_path/'topic.xlsx', [('苏州', '房价')], 'key', client=client, semantic_rule='topic')
        assert scene.checkpoint_path != topic.checkpoint_path


def test_topic_export_evidence_must_exist_in_original_fields():
    note = {'semantic_rule': 'topic', 'semantic_result': 'matched',
            'title': '今天去苏州旅游', 'topic_evidence': '园区住宅总价三百万元'}
    assert saved_collection_rejection(note) == 'keyword_miss'


@pytest.mark.asyncio
async def test_xhs_topic_progress_is_visible_before_main_export(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from collection_tasks import create_task, prepare_run, SearchProgress
    from api.services.dashboard import dashboard_snapshot

    task = create_task(tmp_path, {'platform': 'xhs', 'semantic_filter': True}, {'苏州 房价': 5})
    run = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))
    progress = SearchProgress()
    progress.record('苏州 房价', 1, ['1'], result={'retained': 1, 'target': 5, 'reason': 'searching', 'diagnostics': {'evaluated': 3}})

    def respond(request):
        payload = json.loads(request.content)
        key = next(key for key in payload['questions']['evidence_text']['criteria'] if key != 'unclear')
        return httpx.Response(200, json={'answers': {'relation': {'choice': 'keep', 'confidence': .95}, 'evidence_text': {'choice': key}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        raw = tmp_path/'xhs/live.xlsx'
        raw.parent.mkdir()
        stream = StreamingSemanticFilter(raw, [('苏州', '房价')], 'test-key', client=client, semantic_rule='topic')
        await stream.add_note({'note_id': '1', 'title': '苏州住宅成交总价三百万元', 'source_keyword': '苏州 房价'})
        await stream.finalize_note('1')
        assert not raw.exists()
        result = dashboard_snapshot(tmp_path, SimpleNamespace(status='running', collection_run=run))
        assert result['task']['id'] == task['id']
        assert result['task']['platform'] == 'xhs'
        assert result['task']['current_keyword'] == '苏州 房价'
        assert result['task']['status'] == 'running'
        assert result['groups'][0]['target'] == 5
        assert result['metrics']['qualified_posts'] == 1
        assert result['metrics']['checked_posts'] == 3
        assert result['missing_files'] == []
        await stream.close()

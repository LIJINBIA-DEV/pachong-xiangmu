"""V7 context and confidence regression; controlled replies are not live accuracy."""
import json
from pathlib import Path

import httpx
import pytest

from semantic_filter import JevReviewer, StreamingSemanticFilter, MIN_KEEP_CONFIDENCE
from semantic_quality import evidence_records
from tests.semantic_responses import grounded_response


def test_context_evidence_keeps_exact_source_offsets_without_joining_fields():
    body = '今天到公园的动物乐园。逛了动物的家。园里的动物慵懒可爱。'
    records = evidence_records([('content', body), ('comment:a', '这个可爱'), ('comment:b', '公园')],
                               context_pair=('可爱', '公园'))
    context = [record for record in records if record.key.startswith('context')]
    assert len(context) == 1 and context[0].source == 'content'
    assert body[context[0].start:context[0].end] == context[0].text == body
    assert not any(record.source.startswith('comment:') for record in context)


def test_context_records_do_not_join_paragraphs_or_expand_specific_elements():
    fields = [('content', '今天去公园。\n买了一个可爱的钥匙扣。')]
    assert not any(record.key.startswith('context') for record in evidence_records(fields, context_pair=('可爱', '公园')))
    fields = [('content', '垃圾桶在门口。附近的松鼠真可爱。')]
    assert not any(record.key.startswith('context') for record in evidence_records(fields, context_pair=('可爱', '垃圾桶')))


@pytest.mark.asyncio
@pytest.mark.parametrize('confidence,expected', [(0.73, 'keep'), (0.7, 'keep'), (0.69, 'review')])
async def test_strict_mode_preserves_confidence_threshold(confidence, expected):
    assert MIN_KEEP_CONFIDENCE == 0.7
    def respond(request):
        payload = json.loads(request.content)
        if 'support' in payload['questions']:
            return httpx.Response(200, json={'answers': {'support': {'choice': 'supported', 'confidence': 0.72}}})
        return grounded_response(request, confidence=confidence)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        decision = await JevReviewer('fake', client, selection_mode='strict').decide(('可爱', '公园'), '公园的花坛真可爱')
    assert decision.choice == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('choice,confidence', [('supported', 0.5), ('unclear', 0.9), ('contradicted', 0.9)])
async def test_strict_mode_preserves_verification_threshold(choice, confidence):
    def respond(request):
        payload = json.loads(request.content)
        if 'support' in payload['questions']:
            return httpx.Response(200, json={'answers': {'support': {'choice': choice, 'confidence': confidence}}})
        return grounded_response(request, confidence=0.73)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        decision = await JevReviewer('fake', client, selection_mode='strict').decide(('可爱', '公园'), '公园的花坛真可爱')
    assert decision.choice == ('reject' if choice == 'contradicted' else 'review')
    assert decision.reason == ('evidence_contradicted' if choice == 'contradicted' else 'evidence_not_verified')


@pytest.mark.asyncio
async def test_two_user_examples_replay_v7_without_modifying_historical_files(tmp_path):
    examples = json.loads((Path(__file__).parent / 'fixtures' / 'weibo_context_20261008.json').read_text(encoding='utf-8'))
    sent = []
    def respond(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if 'support' in payload['questions']:
            # A controlled positive verification under the contextual rules.
            # The old 0.5 answer is not automatically upgraded or accepted.
            assert '必须结合 state.text 的完整上下文' in payload['questions']['support']['instructions']
            assert '逛一些动物的家' in payload['state']['location_evidence']
            return httpx.Response(200, json={'answers': {'support': {'choice': 'supported', 'confidence': 0.72}}})
        result = grounded_response(request, confidence=0.73, kind='park_animal', relation='scene_component')
        answer = json.loads(result.content)
        options = payload['questions']['evidence_text']['criteria']
        evaluation = next(key for key, value in options.items() if key.startswith('e') and '小动物的慵懒可爱' in value)
        location = next(key for key, value in options.items() if key.startswith('context') and '公园' in value)
        answer['answers']['evidence_text']['choice'] = evaluation
        answer['answers']['target_evidence']['choice'] = location
        return httpx.Response(200, json=answer)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        stream = StreamingSemanticFilter(tmp_path / 'run.xlsx', [('可爱', '公园')], 'fake', client=client)
        for sample in examples:
            note = {key: sample[key] for key in ('note_id', 'source_keyword', 'content', 'image_names')}
            await stream.add_note(note)
            await stream.finalize_note(note['note_id'], False, interim=True)
            state = stream.states[(note['note_id'], note['source_keyword'])]
            if sample['expected_text_result'] == 'matched':
                assert state.status == 'matched'
                assert state.note['semantic_comment_stop_reason'] == 'body_match'
                assert state.evidence_text != state.target_evidence_text
                assert '逛一些动物的家' in state.target_evidence_text
                assert state.verification_confidence == 0.72
                assert not state.comments
            else:
                assert state.status is None  # Keep the comment channel before finalization.
                await stream.finalize_note(note['note_id'], True)
                assert state.status == 'excluded' and state.source == 'keyword_miss'
        assert len(sent) == 2  # No model call for the off-topic post.
        await stream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('content,kind,relation', [
    ('带我家可爱的小狗逛公园', 'pet', 'scene_component'),
    ('在公园吃可爱的蛋糕', 'food', 'scene_component'),
    ('带可爱的宝宝逛公园', 'person', 'scene_component'),
    ('垃圾桶旁边的松鼠好可爱', 'wild_animal', 'target_itself'),
])
async def test_looser_confidence_does_not_override_object_boundaries(content, kind, relation):
    pair = ('可爱', '垃圾桶' if '垃圾桶' in content else '公园')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: grounded_response(
        request, confidence=0.73, kind=kind, relation=relation))) as client:
        decision = await JevReviewer('fake', client).decide(pair, content)
    assert decision.choice == ('reject' if kind == 'pet' else 'review')


@pytest.mark.asyncio
async def test_park_zoo_explicit_rejection_cannot_be_repaired_into_acceptance():
    sent = []
    def respond(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if len(sent) == 1:
            return grounded_response(request, 'reject', kind='animal', relation='unrelated')
        return grounded_response(request, kind='park_animal', relation='scene_component', confidence=0.73)
    body = '这次来公园里的动物乐园。逛动物的家，动物们好可爱。'
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        decision = await JevReviewer('fake', client).decide(('可爱', '公园'), body)
    assert decision.choice == 'reject' and not decision.reviewed_twice
    assert len(sent) == 1

"""Provider failures and uncertain decisions must never satisfy collection targets."""
import json

import httpx
import pytest

from semantic_filter import SemanticFilterError, StreamingSemanticFilter, check_semantic_connection
from semantic_quality import saved_collection_rejection
from api.services.data_browser import browse_posts


BODY = '武汉这家店服务很差，需要避雷。'


@pytest.fixture(autouse=True)
def universal_environment(monkeypatch):
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_BASE_URL', 'https://models.example/v1')
    monkeypatch.setenv('AI_MODEL', 'provider-model')
    # An old candidate-mode setting cannot resurrect automatic review promotion.
    monkeypatch.setenv('MEDIACRAWLER_SEMANTIC_SELECTION_MODE', 'candidate')
    monkeypatch.delenv('MEDIACRAWLER_COLLECTION_RUN', raising=False)


def model_response(request, **overrides):
    payload = json.loads(request.content)
    assert request.url == 'https://models.example/v1/chat/completions'
    assert payload['model'] == 'provider-model'
    result = dict(choice='keep', confidence=.95, evidence_text=BODY, target_evidence_text=BODY)
    result.update(overrides)
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)}}]})


def make_stream(tmp_path, client, rule):
    pair = ('避雷', '武汉') if rule == 'scene' else ('武汉消费体验', '')
    return StreamingSemanticFilter(tmp_path/'posts.xlsx', [pair], 'fixture-key',
        model='openai-compatible', client=client, semantic_rule=rule), ' '.join(pair).strip()


async def add_and_finish(stream, query):
    await stream.add_note({'note_id': '1', 'source_keyword': query, 'title': '武汉消费记录', 'desc': BODY})
    await stream.finalize_note('1', interim=True)
    await stream.finalize_note('1')
    return stream.states[('1', query)]


@pytest.mark.asyncio
@pytest.mark.parametrize('rule', ['topic', 'scene'])
@pytest.mark.parametrize('choice,status', [('keep', 'matched'), ('review', 'review'), ('reject', 'excluded')])
async def test_universal_decisions_and_original_evidence_survive_export(tmp_path, rule, choice, status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: model_response(r, choice=choice))) as client:
        stream, query = make_stream(tmp_path, client, rule)
        state = await add_and_finish(stream, query)
        assert state.status == status
        assert state.note['model_original_choice'] == choice
        if status != 'excluded':
            data = browse_posts(tmp_path, stream.output_path, status=status)
            assert data['total'] == 1
            assert state.evidence_text == BODY
            assert state.evidence_source == 'desc'
            assert saved_collection_rejection({**state.note, 'semantic_result': status}) is None
        await stream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('rule', ['topic', 'scene'])
@pytest.mark.parametrize('confidence', [.01, None, True, '0.95', -1, 2, float('nan')])
async def test_low_or_invalid_scores_stay_review_and_do_not_count(tmp_path, rule, confidence):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: model_response(r, confidence=confidence))) as client:
        stream, query = make_stream(tmp_path, client, rule)
        state = await add_and_finish(stream, query)
        assert state.status == 'review' and not state.matched
        assert state.note['model_original_choice'] == 'keep'
        assert not any(s.status == 'matched' for s in stream.states.values())
        assert browse_posts(tmp_path, stream.output_path, status='review')['total'] == 1
        await stream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('rule', ['topic', 'scene'])
async def test_missing_or_invented_quotes_are_not_replaced_by_title(tmp_path, rule):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: model_response(r, evidence_text='不存在的评价证据'))) as client:
        stream, query = make_stream(tmp_path, client, rule)
        state = await add_and_finish(stream, query)
        assert state.status == 'review'
        assert state.evidence_text is None
        assert state.quality_reason == 'missing_evidence'
        assert browse_posts(tmp_path, stream.output_path, status='review')['total'] == 1
        await stream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,reason', [(401, 'authentication_rejected'), (403, 'authentication_rejected'),
    (402, 'billing_or_rate_limit'), (429, 'billing_or_rate_limit'), (500, 'provider_error'), (400, 'request_rejected')])
async def test_connection_check_reports_http_failure(status, reason):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status,
            json={'error': 'PRIVATE_PROVIDER_DETAIL'}))) as client:
        checked = await check_semantic_connection('fixture-key', 'openai-compatible', client)
    assert checked == {'ok': False, 'reason': reason, 'http_status': status}
    assert 'PRIVATE_PROVIDER_DETAIL' not in str(checked)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,reason', [('timeout', 'timeout'), ('network', 'network_error'), ('invalid', 'invalid_response')])
async def test_connection_check_reports_transport_and_response_failure(kind, reason):
    def respond(request):
        if kind == 'timeout':
            raise httpx.ReadTimeout('PRIVATE_DETAIL', request=request)
        if kind == 'network':
            raise httpx.ConnectError('PRIVATE_DETAIL', request=request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'not JSON'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        checked = await check_semantic_connection('fixture-key', 'openai-compatible', client)
    assert checked == {'ok': False, 'reason': reason}


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['keep', 'review', 'reject'])
async def test_successful_api_check_is_independent_of_classification(choice):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: model_response(r, choice=choice))) as client:
        assert (await check_semantic_connection('fixture-key', 'openai-compatible', client))['ok']


@pytest.mark.asyncio
async def test_web_connection_check_exposes_failure_without_provider_details(monkeypatch):
    from fastapi import FastAPI
    from api.routers import crawler as router
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401,
            json={'error': 'PRIVATE_PROVIDER_DETAIL'}))) as model:
        async def check(key, selected_model):
            return await check_semantic_connection(key, selected_model, model)
        monkeypatch.setattr(router, 'check_jev_connection', check)
        app = FastAPI()
        app.include_router(router.router, prefix='/api')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as api:
            response = await api.post('/api/crawler/semantic-key-check', json={
                'model': 'openai-compatible', 'api_key': 'fixture-key'})
    assert response.json() == {'ok': False, 'reason': 'authentication_rejected', 'http_status': 401}
    assert 'PRIVATE_PROVIDER_DETAIL' not in response.text and 'fixture-key' not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize('status,retryable', [(401, False), (429, True), (503, True)])
async def test_provider_failure_preserves_pending_post_without_semantic_decision(tmp_path, status, retryable):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status,
            json={'error': 'PRIVATE_PROVIDER_DETAIL'}))) as client:
        stream, query = make_stream(tmp_path, client, 'scene')
        await stream.add_note({'note_id': '1', 'source_keyword': query, 'title': '武汉消费记录', 'desc': BODY})
        if retryable:
            await stream.finalize_note('1', interim=True)
        else:
            with pytest.raises(SemanticFilterError) as caught:
                await stream.finalize_note('1', interim=True)
            assert not caught.value.retryable
            assert 'PRIVATE_PROVIDER_DETAIL' not in str(caught.value)
        state = stream.states[('1', query)]
        assert state.status == 'pending' and not state.matched and not state.uncertain
        assert state.note['desc'] == BODY and state.note.get('model_original_choice') is None
        assert browse_posts(tmp_path, stream.output_path, status='pending')['total'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('rule', ['topic', 'scene'])
@pytest.mark.parametrize('choice,confidence', [('review', .95), ('keep', .4)])
async def test_jev_candidate_setting_cannot_promote_uncertain_posts(tmp_path, rule, choice, confidence):
    def respond(request):
        payload = json.loads(request.content)
        key = next(k for k in payload['questions']['evidence_text']['criteria'] if k != 'unclear')
        return httpx.Response(200, json={'answers': {'relation': {'choice': choice, 'confidence': confidence},
            'evidence_text': {'choice': key}, 'target_evidence': {'choice': key}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        stream = StreamingSemanticFilter(tmp_path/'posts.xlsx', [('避雷', '武汉')], 'fixture-key',
            client=client, semantic_rule=rule, selection_mode='candidate')
        state = await add_and_finish(stream, '避雷 武汉')
        assert state.status == 'review' and not state.matched
        assert state.note.get('selection_origin') != 'review_policy'
        await stream.close()


@pytest.mark.asyncio
async def test_old_acceptance_checkpoint_is_kept_but_not_reused(tmp_path, monkeypatch):
    import semantic_filter
    async with httpx.AsyncClient() as client:
        with monkeypatch.context() as old_version:
            old_version.setattr(semantic_filter, 'CHECKPOINT_VERSION', 3)
            old, query = make_stream(tmp_path, client, 'scene')
            await old.add_note({'note_id': 'old', 'source_keyword': query, 'desc': BODY})
            state = old.states[('old', query)]
            state.status, state.matched = 'matched', True
            old._checkpoint(state)
        before = old.checkpoint_path.read_bytes()
        fresh, _ = make_stream(tmp_path, client, 'scene')
        assert fresh.checkpoint_path != old.checkpoint_path and not fresh.states
        assert old.checkpoint_path.read_bytes() == before


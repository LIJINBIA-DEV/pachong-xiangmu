import asyncio
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook

from api.services.school_review_profile import aggregate_profile, build_profile
from api.services.school_reviews import extract_posts


def post(nid, body='宿舍有空调，住宿很满意。', relevance='relevant'):
    return {'post_id': nid, 'title': '贵州大学就读体验', 'content': body, 'relevance': relevance,
            'comments': [], 'url': 'https://example.com/' + nid, 'platform': 'zhihu'}


def evidence(nid, quote='宿舍有空调，住宿很满意。', tone='positive'):
    return {'post_id': nid, 'dimension': 'housing', 'field': 'content', 'quote': quote, 'polarity': tone}


def test_no_score_without_two_posts_and_never_turn_missing_into_zero():
    result = aggregate_profile([post('1')], [evidence('1')])
    assert result['dimensions'][0]['sample_count'] == 1
    assert result['dimensions'][0]['score'] is None
    assert all(d['score'] is None for d in result['dimensions'])
    assert result['evidence_posts'] == 1 and result['tags']
    result = aggregate_profile([post('1'), post('2')], [evidence('1', tone='negative'), evidence('2', tone='negative')])
    assert result['dimensions'][0]['score'] == 0
    assert result['dimensions'][1]['score'] is None


def test_exact_originals_user_relevance_and_per_post_weighting():
    result = aggregate_profile([post('1'), post('2'), post('3', relevance='unclear')],
        [evidence('1'), evidence('1'), evidence('2', tone='negative'), evidence('3'),
         evidence('2', quote='模型编造的独立卫浴'), evidence('4')])
    housing = result['dimensions'][0]
    assert housing['sample_count'] == 2 and housing['score'] == 50
    assert len(housing['evidence']) == 2
    assert all(t['text'] != '卫浴' for t in result['tags'])


def test_model_selects_only_original_fragment_and_failure_is_explicit(monkeypatch):
    import api.services.school_review_profile as profile
    async def answer(payload):
        if 'evidence' in payload['state']:
            assert payload['state']['evidence']['p0_housing']['quote'] in post('1')['content']
            assert all(name.endswith('_tone') for name in payload['questions'])
        else:
            assert 'none' in payload['questions']['p0_housing_evidence']['criteria']
            assert all(name.endswith('_evidence') for name in payload['questions'])
        return {name: {'choice': 'e0' if name.endswith('_evidence') else 'positive', 'confidence': .9}
                for name in payload['questions']}
    monkeypatch.setattr(profile, 'ask_jev', answer)
    result = asyncio.run(build_profile('贵州大学', '住宿体验', [post('1'), post('2')]))
    assert result['dimensions'][0]['score'] == 100
    assert result['dimensions'][0]['evidence'][0]['quote'] in post('1')['content']
    monkeypatch.setattr(profile, 'ask_jev', AsyncMock(side_effect=ValueError('private upstream details')))
    result = asyncio.run(build_profile('贵州大学', '住宿体验', [post('1')]))
    assert result['status'] == 'UNAVAILABLE'
    assert all(d['score'] is None for d in result['dimensions'])
    assert 'private' not in str(result)


def test_questions_and_ads_can_be_rejected_without_invented_score(monkeypatch):
    import api.services.school_review_profile as profile
    async def none(payload):
        return {name: {'choice': 'none'} for name in payload['questions']}
    monkeypatch.setattr(profile, 'ask_jev', none)
    result = asyncio.run(build_profile('贵州大学', '住宿', [post('1', '请问宿舍有空调吗？')]))
    assert result['evidence_posts'] == 0
    assert all(d['score'] is None for d in result['dimensions'])


@pytest.mark.parametrize('platform,id_field,url_field,body_field', [
    ('bili', 'video_id', 'video_url', 'desc'), ('zhihu', 'content_id', 'content_url', 'content_text')])
def test_platform_excel_ids_long_body_and_comment_association(tmp_path, platform, id_field, url_field, body_field):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Contents'
    sheet.append([id_field, 'title', body_field, url_field])
    sheet.append(['123', '体验', '<p>宿舍有空调</p><script>private-bad()</script><p>课程很扎实</p>' + '长文' * 3000, 'https://example.com/123'])
    comments = book.create_sheet('Comments')
    comments.append(['comment_id', id_field, 'content'])
    comments.append(['c1', '123', '<p>评论原文</p>'])
    comments.append(['c2', 'other-post', '不能混进来的评论'])
    book.save(tmp_path / 'data.xlsx')
    result = extract_posts(tmp_path, ['data.xlsx'], platform=platform)
    assert len(result) == 1 and result[0]['post_id'] == '123'
    assert len(result[0]['content']) == 5000 and result[0]['content_truncated'] is True
    assert 'private-bad' not in result[0]['content'] and '<p>' not in result[0]['content']
    assert result[0]['comments'] == ['评论原文']
    assert result[0]['url'] == 'https://example.com/123' and result[0]['platform'] == platform

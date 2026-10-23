import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient

from api.services.school_reviews import SchoolReviewJobs, classify_posts, extract_posts
from api.routers.school_reviews import ReviewRequest


def test_extract_only_run_files_and_strip_account_data(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Contents'
    sheet.append(['note_id', 'title', 'desc', 'note_url', 'nickname', 'source_keyword'])
    sheet.append(['n1', '学校体验', '原文内容', 'javascript:bad()', 'private-name', '贵州大学 体验'])
    sheet.append(['n1', '重复', '重复', '', '', ''])
    comments = book.create_sheet('Comments')
    comments.append(['comment_id', 'note_id', 'content'])
    comments.append(['c1', 'n1', '评论原文'])
    book.save(tmp_path / 'test.xlsx')
    posts = extract_posts(tmp_path, ['test.xlsx'])
    assert len(posts) == 1
    assert posts[0]['url'] == '' and posts[0]['comments'] == ['评论原文']
    assert 'private-name' not in json.dumps(posts)
    with pytest.raises(ValueError):
        extract_posts(tmp_path, ['../test.xlsx'])


def test_invalid_keyword_combinations_rejected():
    for school in ['贵州大学,清华大学', '贵州大学\n清华大学']:
        with pytest.raises(ValueError):
            ReviewRequest(owner='u', school=school, topic='体验')


def test_authenticated_bridge_and_user_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('RAGENT_REVIEW_TOKEN', 'private-bridge')
    from api.main import app
    import api.routers.school_reviews as router
    jobs = SchoolReviewJobs(type('Manager', (), {})(), tmp_path)
    monkeypatch.setattr(router, 'jobs', jobs)
    job_id = 'a' * 32
    jobs.save({'job_id': job_id, 'owner': 'u1', 'status': 'COMPLETED', 'run_file': '/private/path'})
    with TestClient(app) as client:
        assert client.get('/api/school-reviews/' + job_id + '?owner=u1').status_code == 401
        headers = {'X-Ragent-Token': 'private-bridge'}
        assert client.get('/api/school-reviews/' + job_id + '?owner=u2', headers=headers).status_code == 404
        result = client.get('/api/school-reviews/' + job_id + '?owner=u1', headers=headers).json()
        assert result['job_id'] == job_id and result['status'] == 'COMPLETED'
        assert 'owner' not in result and 'run_file' not in result


def test_reuses_active_job_and_marks_restart_interrupted(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'data'))
    monkeypatch.setenv('TYPESAFE_API_KEY', 'never-persist-this-key')
    class Process:
        returncode = None
        def poll(self): return self.returncode
    class Manager:
        status = 'idle'
        process = Process()
        collection_run = None
        starts = 0
        async def start(self, request, collection_run):
            assert not request.semantic_filter and not request.image_subject_recognition
            assert request.max_notes_count == 5 and request.max_comments_count == 3
            self.collection_run = collection_run
            self.starts += 1
            self.status = 'running'
            return True
        async def stop(self): self.process.returncode = -15; self.status = 'idle'
    async def run():
        manager = Manager()
        jobs = SchoolReviewJobs(manager, tmp_path)
        first = await jobs.start('u', '贵州大学', '计算机体验', 'xhs')
        again = await jobs.start('u', '贵州大学', '计算机体验', 'xhs')
        assert first['job_id'] == again['job_id'] and again['reused']
        assert manager.starts == 1
        assert (await jobs.start('other', '贵州大学', '体验', 'xhs'))['status'] == 'BUSY'
        cancelled = await jobs.cancel(first['job_id'], 'u')
        assert cancelled['status'] == 'CANCELLED'
        job_id = 'b' * 32
        jobs.save({'job_id': job_id, 'owner': 'u', 'status': 'RUNNING'})
        assert jobs.read(job_id, 'u')['status'] == 'INTERRUPTED'
        assert 'never-persist-this-key' not in jobs.path(first['job_id']).read_text()
    asyncio.run(run())


def test_jev_failure_keeps_originals_without_fake_screening(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    posts = [{'post_id': '1', 'relevance': 'unreviewed', 'content': '原文'}]
    result, status = asyncio.run(classify_posts('贵州大学', '体验', posts))
    assert result == posts and status == 'UNAVAILABLE'


def test_school_specific_jev_decisions_and_invalid_response(monkeypatch):
    import httpx
    import jev_transport
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-key-not-persisted')
    posts = [{'post_id': '1', 'content': '贵州大学计算机学习体验', 'relevance': 'unreviewed'},
             {'post_id': '2', 'content': '其他学校的无关广告', 'relevance': 'unreviewed'}]
    async def run():
        def reply(request):
            payload = json.loads(request.content)
            assert payload['state']['school'] == '贵州大学'
            assert 'object_type' not in payload['questions']
            assert request.headers['Authorization'] == 'Bearer test-key-not-persisted'
            return httpx.Response(200, json={'answers': {'p0': {'choice': 'relevant'}, 'p1': {'choice': 'unrelated'}}})
        monkeypatch.setattr(jev_transport, 'create_semantic_client', lambda _: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
        result, status = await classify_posts('贵州大学', '计算机体验', posts)
        assert status == 'COMPLETED'
        assert [p['relevance'] for p in result] == ['relevant', 'unrelated']
        assert result[0]['content'] == posts[0]['content']
        monkeypatch.setattr(jev_transport, 'create_semantic_client', lambda _: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'answers': {'p0': {'choice': 'invented'}}}))))
        result, status = await classify_posts('贵州大学', '计算机体验', posts)
        assert result == posts and status == 'UNAVAILABLE'
    asyncio.run(run())


def test_timeout_stops_only_own_task(tmp_path):
    class Process:
        returncode = None
        def poll(self): return None
    class Manager:
        process = Process()
        stop = AsyncMock()
    async def run():
        manager = Manager()
        jobs = SchoolReviewJobs(manager, tmp_path, timeout=0)
        job = {'job_id': 'c' * 32, 'status': 'RUNNING'}
        await jobs._watch(job, manager.process, tmp_path)
        assert job['status'] == 'TIMED_OUT'
        manager.stop.assert_awaited_once()
        manager.stop.reset_mock()
        await jobs._watch(job, Process(), tmp_path)
        manager.stop.assert_not_awaited()
    asyncio.run(run())

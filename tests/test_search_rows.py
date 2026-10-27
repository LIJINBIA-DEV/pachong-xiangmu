"""The new row editor must reach the existing crawler as exactly the authored searches."""
import asyncio
import importlib
import json

import pytest

from api.schemas.crawler import CrawlerStartRequest
from api.services.crawler_manager import CrawlerManager


@pytest.mark.asyncio
@pytest.mark.parametrize('platform', ['wb', 'xhs'])
async def test_authored_search_rows_reach_child_and_task_without_cross_pairing(tmp_path, monkeypatch, platform):
    import config
    from collection_tasks import read_task

    monkeypatch.delenv('MEDIACRAWLER_CONTAINER_MODE', raising=False)
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path))
    manager_module = importlib.import_module('api.services.crawler_manager')
    captured = {}

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured.update(command=command, env=kwargs['env'])
        return FakeProcess()

    monkeypatch.setattr(manager_module.subprocess, 'Popen', fake_popen)
    manager = CrawlerManager()
    request = CrawlerStartRequest(
        platform=platform, crawler_type='search', save_option='excel',
        image_subject_recognition=False, semantic_filter=True,
        semantic_rule='topic',
        semantic_api_key='test-only-key', max_notes_count=3,
        keywords='可爱 公园,萌 雕像,萌 公园 雕塑',
        keyword_pairs=[('可爱', '公园'), ('萌', '雕像'), ('萌', '公园 雕塑')],
    )
    assert await manager.start(request)
    try:
        command = captured['command']
        assert command[command.index('--keywords') + 1] == request.keywords
        assert json.loads(captured['env']['MEDIACRAWLER_KEYWORD_PAIRS']) == [list(pair) for pair in request.keyword_pairs]
        run = json.loads(manager.collection_run.read_text(encoding='utf-8'))
        task = read_task(tmp_path, run['task_id'])
        assert task['targets'] == {'可爱 公园': 3, '萌 雕像': 3, '萌 公园 雕塑': 3}
        assert '可爱 雕像' not in task['targets']
        assert task['config']['keywords'] == request.keywords
        assert task['config']['semantic_rule'] == 'topic'
        assert captured['env']['MEDIACRAWLER_SEMANTIC_RULE'] == 'topic'
        assert 'test-only-key' not in manager.collection_run.read_text()
    finally:
        manager._read_task.cancel()
        await asyncio.gather(manager._read_task, return_exceptions=True)

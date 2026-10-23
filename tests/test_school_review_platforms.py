import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_bilibili_respects_five_video_limit(monkeypatch):
    import config
    import media_platform.bilibili.core as core
    monkeypatch.setattr(config, 'CRAWLER_MAX_NOTES_COUNT', 5)
    monkeypatch.setattr(config, 'CRAWLER_MAX_SLEEP_SEC', 0)
    monkeypatch.setattr(config, 'KEYWORDS', '贵州大学 研究生')
    monkeypatch.setattr(config, 'START_PAGE', 1)
    crawler = core.BilibiliCrawler()
    crawler.bili_client = SimpleNamespace(search_video_by_keyword=AsyncMock(return_value={'result': [{'aid': i} for i in range(20)]}))
    async def video(aid, **kwargs): return {'View': {'aid': aid}}
    crawler.get_video_info_task = video
    crawler.download_media = AsyncMock()
    crawler.batch_get_video_comments = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.bilibili_store, 'update_bilibili_video', saved)
    monkeypatch.setattr(core.bilibili_store, 'update_up_info', AsyncMock())
    asyncio.run(crawler.search_by_keywords())
    assert saved.await_count == 5
    assert len(crawler.batch_get_video_comments.await_args.args[0]) == 5
    assert config.CRAWLER_MAX_NOTES_COUNT == 5


def test_zhihu_respects_five_answer_limit(monkeypatch):
    import config
    import media_platform.zhihu.core as core
    monkeypatch.setattr(config, 'CRAWLER_MAX_NOTES_COUNT', 5)
    monkeypatch.setattr(config, 'CRAWLER_MAX_SLEEP_SEC', 0)
    monkeypatch.setattr(config, 'KEYWORDS', '贵州大学 研究生')
    monkeypatch.setattr(config, 'START_PAGE', 1)
    crawler = core.ZhihuCrawler()
    crawler.zhihu_client = SimpleNamespace(get_note_by_keyword=AsyncMock(return_value=[SimpleNamespace(content_id=str(i)) for i in range(20)]))
    crawler.batch_get_content_comments = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.zhihu_store, 'update_zhihu_content', saved)
    asyncio.run(crawler.search())
    assert saved.await_count == 5
    assert len(crawler.batch_get_content_comments.await_args.args[0]) == 5
    assert config.CRAWLER_MAX_NOTES_COUNT == 5


def test_zhihu_root_comments_obey_limit():
    from media_platform.zhihu.client import ZhiHuClient
    client = ZhiHuClient.__new__(ZhiHuClient)
    client.get_root_comments = AsyncMock(return_value={'paging': {'is_end': False}, 'data': []})
    client._extractor = SimpleNamespace(extract_offset=lambda _: 'next', extract_comments=lambda *_: list(range(10)))
    client.get_comments_all_sub_comments = AsyncMock()
    saved = AsyncMock()
    result = asyncio.run(client.get_note_all_comments(SimpleNamespace(content_id='1', content_type='answer'),
        crawl_interval=0, callback=saved, max_count=3))
    assert result == [0, 1, 2]
    assert saved.await_args.args[0] == [0, 1, 2]
    assert client.get_root_comments.await_count == 1


@pytest.mark.parametrize('name', ['zhihu', 'bilibili'])
def test_native_browser_uses_installed_channel(name, monkeypatch):
    import importlib
    import config
    core = importlib.import_module(f'media_platform.{name}.core')
    monkeypatch.setattr(config, 'SAVE_LOGIN_STATE', True)
    monkeypatch.setattr(core, 'web_login_browser_channel', lambda: 'chromium')
    crawler = core.ZhihuCrawler() if name == 'zhihu' else core.BilibiliCrawler()
    chromium = SimpleNamespace(launch_persistent_context=AsyncMock(return_value='context'))
    assert asyncio.run(crawler.launch_browser(chromium, None, 'user-agent', headless=True)) == 'context'
    assert chromium.launch_persistent_context.await_args.kwargs['channel'] == 'chromium'

"""Search limits count candidate posts per keyword, including partial final pages."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_weibo_limit_spans_pages_without_exceeding_count(monkeypatch):
    from media_platform.weibo import core

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 2)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 15)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "json")
    monkeypatch.setattr(core, "filter_search_result_card", lambda cards: cards)

    async def search_page(*, keyword, page, search_type):
        return {"cards": [{"mblog": {"id": f"{page}-{i}"}} for i in range(10)]}

    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search_page))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, "update_weibo_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.wb_client.get_note_by_keyword.await_args_list] == [2, 3]
    assert saved.await_count == 15


@pytest.mark.asyncio
async def test_xhs_processes_last_page_but_respects_smaller_limit(monkeypatch, tmp_path):
    from media_platform.xhs import core
    from collection_tasks import create_task, prepare_run, SearchProgress

    task = create_task(tmp_path, {'platform': 'xhs'}, {'可爱 公园': 5})
    run = prepare_run(tmp_path, task, task['targets'])
    monkeypatch.setenv('MEDIACRAWLER_COLLECTION_RUN', str(run))

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 5)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "json")

    crawler = core.XiaoHongShuCrawler()
    crawler.xhs_client = SimpleNamespace(get_note_by_keyword=AsyncMock(return_value={
        "has_more": False,
        "items": [{"id": str(i), "xsec_source": "search", "xsec_token": "token"} for i in range(20)],
    }))
    crawler.get_note_detail_async_task = AsyncMock(side_effect=lambda note_id, **kwargs: {"note_id": note_id, "xsec_token": "token"})
    crawler.batch_get_note_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.xhs_store, "update_xhs_note", saved)

    await crawler.search()

    assert crawler.xhs_client.get_note_by_keyword.await_count == 1
    assert saved.await_count == 5
    result = SearchProgress().run['results']['可爱 公园']
    assert result['retained'] == 5 and result['reason'] == 'target_reached'
    assert result['diagnostics']['evaluated'] == 5
    assert result['diagnostics']['checked_page'] == 1


@pytest.mark.asyncio
async def test_weibo_semantic_target_counts_retained_posts_across_pages(monkeypatch):
    from media_platform.weibo import core
    from store.excel_store_base import ExcelStoreBase

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 3)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "excel")
    monkeypatch.setenv("MEDIACRAWLER_SEMANTIC_FILTER", "1")
    monkeypatch.setattr(core, "filter_search_result_card", lambda cards: cards)
    monkeypatch.setattr(
        ExcelStoreBase, "semantic_note_retained",
        classmethod(lambda cls, platform, note_id, source_keyword: str(note_id) in {"1", "5", "7"}),
    )

    async def search_page(*, keyword, page, search_type):
        start = (page - 1) * 5 + 1
        return {"cards": [{"mblog": {"id": str(i)}} for i in range(start, start + 5)]}

    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search_page))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, "update_weibo_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.wb_client.get_note_by_keyword.await_args_list] == [1, 2]
    assert [call.args[0]["mblog"]["id"] for call in saved.await_args_list] == [str(i) for i in range(1, 8)]
    assert [call.args[0] for call in crawler.batch_get_notes_comments.await_args_list] == [
        [str(i)] for i in range(1, 8)
    ]
    assert [call.args[0]["id"] for call in crawler.download_media.await_args_list] == ["1", "5", "7"]


@pytest.mark.asyncio
async def test_xhs_semantic_target_counts_retained_posts_across_pages(monkeypatch):
    from media_platform.xhs import core
    from store.excel_store_base import ExcelStoreBase

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 3)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "excel")
    monkeypatch.setenv("MEDIACRAWLER_SEMANTIC_FILTER", "1")
    monkeypatch.setattr(
        ExcelStoreBase, "semantic_note_retained",
        classmethod(lambda cls, platform, note_id, source_keyword: str(note_id) in {"1", "5", "7"}),
    )

    async def search_page(*, keyword, search_id, page, sort):
        start = (page - 1) * 5 + 1
        return {"has_more": page < 2, "items": [
            {"id": str(i), "xsec_source": "search", "xsec_token": "token"}
            for i in range(start, start + 5)
        ]}

    crawler = core.XiaoHongShuCrawler()
    crawler.xhs_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search_page))
    crawler.get_note_detail_async_task = AsyncMock(
        side_effect=lambda note_id, **kwargs: {"note_id": note_id, "xsec_token": "token"}
    )
    crawler.batch_get_note_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.xhs_store, "update_xhs_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.xhs_client.get_note_by_keyword.await_args_list] == [1, 2]
    assert [call.args[0]["note_id"] for call in saved.await_args_list] == [str(i) for i in range(1, 8)]
    assert [call.args[0] for call in crawler.batch_get_note_comments.await_args_list] == [
        ["1", "2", "3"], ["4", "5"], ["6"], ["7"],
    ]
    assert [call.args[0]["note_id"] for call in crawler.download_media.await_args_list] == ["1", "5", "7"]


@pytest.mark.asyncio
async def test_weibo_stops_when_results_end_before_target(monkeypatch):
    from media_platform.weibo import core

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 3)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "json")
    monkeypatch.setenv("MEDIACRAWLER_SEMANTIC_FILTER", "0")
    monkeypatch.setattr(core, "filter_search_result_card", lambda cards: cards)

    async def search_page(*, keyword, page, search_type):
        if page == 1:
            return {"cards": [{"mblog": {"id": "1"}}, {"mblog": {"id": "2"}}]}
        return {"cards": []}

    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search_page))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, "update_weibo_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.wb_client.get_note_by_keyword.await_args_list] == [1, 2]
    assert saved.await_count == 2


@pytest.mark.asyncio
async def test_weibo_skips_duplicate_page_and_reaches_semantic_target(monkeypatch):
    from media_platform.weibo import core
    from store.excel_store_base import ExcelStoreBase

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "excel")
    monkeypatch.setenv("MEDIACRAWLER_SEMANTIC_FILTER", "1")
    monkeypatch.setattr(core, "filter_search_result_card", lambda cards: cards)
    monkeypatch.setattr(
        ExcelStoreBase, "semantic_note_retained",
        classmethod(lambda cls, platform, note_id, source_keyword: str(note_id) == "2"),
    )

    async def search_page(*, keyword, page, search_type):
        note_id = "1" if page in (1, 2) else "2"
        return {"cards": [{"mblog": {"id": note_id}}]}

    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search_page))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, "update_weibo_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.wb_client.get_note_by_keyword.await_args_list] == [1, 2, 3]
    assert [call.args[0]["mblog"]["id"] for call in saved.await_args_list] == ["1", "2"]
    assert crawler.batch_get_notes_full_text.await_count == 2
    assert [call.args[0]["id"] for call in crawler.download_media.await_args_list] == ["2"]


@pytest.mark.asyncio
async def test_weibo_stops_after_repeated_duplicate_pages(monkeypatch):
    from media_platform.weibo import core

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 2)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "json")
    monkeypatch.setenv("MEDIACRAWLER_SEMANTIC_FILTER", "0")
    monkeypatch.setattr(core, "filter_search_result_card", lambda cards: cards)

    crawler = core.WeiboCrawler()
    crawler.wb_client = SimpleNamespace(get_note_by_keyword=AsyncMock(return_value={"cards": [{"mblog": {"id": "1"}}]}))
    crawler.batch_get_notes_full_text = AsyncMock(side_effect=lambda notes: notes)
    crawler.batch_get_notes_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.weibo_store, "update_weibo_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.wb_client.get_note_by_keyword.await_args_list] == [1, 2, 3, 4]
    assert saved.await_count == 1


@pytest.mark.asyncio
async def test_xhs_skips_duplicate_page_when_more_results_exist(monkeypatch):
    from media_platform.xhs import core

    monkeypatch.setattr(core.config, "KEYWORDS", "可爱 公园")
    monkeypatch.setattr(core.config, "START_PAGE", 1)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_NOTES_COUNT", 2)
    monkeypatch.setattr(core.config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.config, "SAVE_DATA_OPTION", "json")

    async def search_page(*, keyword, search_id, page, sort):
        note_id = "1" if page in (1, 2) else "2"
        return {"has_more": page < 3, "items": [{"id": note_id, "xsec_source": "search", "xsec_token": "token"}]}

    crawler = core.XiaoHongShuCrawler()
    crawler.xhs_client = SimpleNamespace(get_note_by_keyword=AsyncMock(side_effect=search_page))
    crawler.get_note_detail_async_task = AsyncMock(side_effect=lambda note_id, **kwargs: {"note_id": note_id, "xsec_token": "token"})
    crawler.batch_get_note_comments = AsyncMock()
    crawler.download_media = AsyncMock()
    saved = AsyncMock()
    monkeypatch.setattr(core.xhs_store, "update_xhs_note", saved)

    await crawler.search()

    assert [call.kwargs["page"] for call in crawler.xhs_client.get_note_by_keyword.await_args_list] == [1, 2, 3]
    assert [call.args[0]["note_id"] for call in saved.await_args_list] == ["1", "2"]

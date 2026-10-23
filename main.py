# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/main.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import sys
import io

# Force UTF-8 encoding for stdout/stderr to prevent encoding errors
# when outputting Chinese characters in non-UTF-8 terminals
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import os
from typing import Optional, Type

import cmd_arg
import config
from database import db
from base.base_crawler import AbstractCrawler
from media_platform.bilibili import BilibiliCrawler
from media_platform.douyin import DouYinCrawler
from media_platform.kuaishou import KuaishouCrawler
from media_platform.tieba import TieBaCrawler
from media_platform.weibo import WeiboCrawler
from media_platform.xhs import XiaoHongShuCrawler
from media_platform.zhihu import ZhihuCrawler
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var


class CrawlerFactory:
    CRAWLERS: dict[str, Type[AbstractCrawler]] = {
        "xhs": XiaoHongShuCrawler,
        "dy": DouYinCrawler,
        "ks": KuaishouCrawler,
        "bili": BilibiliCrawler,
        "wb": WeiboCrawler,
        "tieba": TieBaCrawler,
        "zhihu": ZhihuCrawler,
    }

    @staticmethod
    def create_crawler(platform: str) -> AbstractCrawler:
        crawler_class = CrawlerFactory.CRAWLERS.get(platform)
        if not crawler_class:
            supported = ", ".join(sorted(CrawlerFactory.CRAWLERS))
            raise ValueError(f"Invalid media platform: {platform!r}. Supported: {supported}")
        return crawler_class()


crawler: Optional[AbstractCrawler] = None
_excel_flushed = False


def _flush_excel_if_needed() -> None:
    global _excel_flushed
    if config.SAVE_DATA_OPTION != "excel":
        return

    try:
        from store.excel_store_base import ExcelStoreBase

        ExcelStoreBase.flush_all()
        _excel_flushed = True
        print("[Main] Excel files saved successfully")
    except Exception as e:
        print(f"[Main] Error flushing Excel data: {e}")


async def _finalize_semantics_if_needed() -> None:
    if os.environ.get("MEDIACRAWLER_SEMANTIC_FILTER") != "1":
        return
    if config.SAVE_DATA_OPTION != "excel" or config.CRAWLER_TYPE != "search" or config.PLATFORM not in ("wb", "xhs"):
        raise ValueError("Jev semantic filtering requires Weibo/Xiaohongshu search with Excel output")
    from store.excel_store_base import ExcelStoreBase
    await ExcelStoreBase.finalize_semantics_all()


async def _generate_wordcloud_if_needed() -> None:
    if config.SAVE_DATA_OPTION not in ("json", "jsonl") or not config.ENABLE_GET_WORDCLOUD:
        return

    try:
        file_writer = AsyncFileWriter(
            platform=config.PLATFORM,
            crawler_type=crawler_type_var.get(),
        )
        await file_writer.generate_wordcloud_from_comments()
    except Exception as e:
        print(f"[Main] Error generating wordcloud: {e}")


async def _recognize_saved_images(files) -> None:
    if os.environ.get('MEDIACRAWLER_IMAGE_SUBJECT') != '1' or not files:
        return
    from pathlib import Path
    from image_subject import recognize_files
    from api.services.image_subject import image_subject_jobs
    root = Path(config.SAVE_DATA_PATH or 'data').resolve()
    # Model inference follows text review/Excel flush, so local SemIf has already
    # released its GPU process. Source workbooks and human labels remain intact.
    from image_subject_settings import runtime_settings
    provider_name = '硅基流动' if runtime_settings(root)['provider'] == 'siliconflow' else '本地 Qwen'
    print(f'[ImageSubject] 文本采集已保存，开始{provider_name}图片主体与类型识别。', flush=True)
    def progress(state):
        from collection_tasks import atomic_json
        for file in files:
            atomic_json(image_subject_jobs.state_path(root, file), state)
    try:
        state = await recognize_files(root, files, progress=progress)
        print(f"[ImageSubject] 图片识别完成：{state['completed']}/{state['total']}，失败 {state['failed']}，未下载 {state['not_downloaded']}。", flush=True)
    except Exception as exc:
        progress({'status': 'error', 'error': str(exc) if str(exc).startswith('image_subject_') else type(exc).__name__})
        print(f'[ImageSubject] 图片识别暂未完成（{type(exc).__name__}）；采集数据已保留，可在人工审核页重试。', flush=True)


async def main() -> None:
    global crawler

    args = await cmd_arg.parse_cmd()
    if args.init_db:
        await db.init_db(args.init_db)
        print(f"Database {args.init_db} initialized successfully.")
        return

    # 数据库保存模式下自动建表，避免首次运行时出现 no such table 错误
    if config.SAVE_DATA_OPTION in ("sqlite", "mysql", "db", "postgres"):
        await db.init_db(config.SAVE_DATA_OPTION)

    crawler = CrawlerFactory.create_crawler(platform=config.PLATFORM)
    from collection_tasks import review_progress
    review_progress("OPENING_BROWSER")
    await crawler.start()

    from store.excel_store_base import ExcelStoreBase
    image_files = [instance.filename.resolve() for instance in ExcelStoreBase._instances.values() if instance.platform == 'weibo']

    try:
        await _finalize_semantics_if_needed()
    finally:
        _flush_excel_if_needed()

    await _recognize_saved_images([file for file in image_files if file.is_file()])

    # Generate wordcloud after crawling is complete
    # Only for JSON save mode
    await _generate_wordcloud_if_needed()


async def async_cleanup() -> None:
    global crawler
    if not _excel_flushed:
        try:
            await _finalize_semantics_if_needed()
        except Exception as exc:
            print(f"[Main] Error finalizing semantic results: {exc}")
        finally:
            _flush_excel_if_needed()
    if crawler:
        if getattr(crawler, "cdp_manager", None):
            try:
                await crawler.cdp_manager.cleanup(force=True)
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    print(f"[Main] Error cleaning up CDP browser: {e}")

        elif getattr(crawler, "browser_context", None):
            try:
                await crawler.browser_context.close()
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    print(f"[Main] Error closing browser context: {e}")

    if config.SAVE_DATA_OPTION in ("db", "sqlite"):
        await db.close()

if __name__ == "__main__":
    from tools.app_runner import run

    def _force_stop() -> None:
        c = crawler
        if not c:
            return
        cdp_manager = getattr(c, "cdp_manager", None)
        launcher = getattr(cdp_manager, "launcher", None)
        if not launcher:
            return
        try:
            launcher.cleanup()
        except Exception:
            pass

    run(main, async_cleanup, cleanup_timeout_seconds=15.0, on_first_interrupt=_force_stop)

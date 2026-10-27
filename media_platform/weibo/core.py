# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/weibo/core.py
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

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/23 15:41
# @Desc    : Weibo crawler main workflow code

import asyncio
import os
# import random  # Removed as we now use fixed config.CRAWLER_MAX_SLEEP_SEC intervals
from asyncio import Task
from typing import Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Error as PlaywrightError,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from media_downloader import MediaDownloader
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import weibo as weibo_store
from semantic_filter import SemanticFilterError
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from . import media as weibo_media
from .client import WeiboClient
from .exception import DataFetchError, LoginRequired
from .field import SearchType
from .help import filter_search_result_card
from .login import WeiboLogin


MAX_CONSECUTIVE_DUPLICATE_PAGES = 3


class WeiboCrawler(AbstractCrawler):
    context_page: Page
    wb_client: WeiboClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self):
        self.index_url = "https://www.weibo.com"
        self.mobile_index_url = "https://m.weibo.cn"
        self.cookie_urls = [self.mobile_index_url]
        self.user_agent = utils.get_user_agent()
        self.mobile_user_agent = utils.get_mobile_user_agent()
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh
        self._media_downloader: Optional[MediaDownloader] = None

    async def start(self):
        blocklist_counts = weibo_store.load_blocklist()[2]
        utils.logger.info(f"[AccountFilter] 本地账号排除名单已加载：{blocklist_counts}")
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # Select launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[WeiboCrawler] Launching browser with CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.mobile_user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[WeiboCrawler] Launching browser with standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(chromium, None, self.mobile_user_agent, headless=config.HEADLESS)

                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")


            self.context_page = await self.browser_context.new_page()
            try:
                await self.context_page.goto(self.index_url, wait_until="commit", timeout=15000)
            except PlaywrightError as exc:
                utils.logger.warning(
                    f"[WeiboCrawler] Desktop homepage unavailable ({str(exc).splitlines()[0]}); "
                    "trying mobile homepage"
                )
                await self.context_page.goto(self.mobile_index_url, wait_until="commit", timeout=15000)
            await asyncio.sleep(2)

            container_mode = os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1'
            web_qr = os.environ.get('MEDIACRAWLER_WEB_QR_LOGIN') == '1' and config.LOGIN_TYPE == 'qrcode'
            if container_mode or web_qr:
                # Refresh explicitly supplied credentials even when a prior
                # browser profile is still logged in.
                await self.browser_context.clear_cookies()
                if config.LOGIN_TYPE == 'cookie':
                    login_obj = WeiboLogin(login_type='cookie', login_phone='',
                        browser_context=self.browser_context, context_page=self.context_page, cookie_str=config.COOKIES)
                    await login_obj.login_by_cookies()
                else:
                    from media_platform.weibo.session import restore_session
                    if not await restore_session(self.browser_context, os.getcwd()):
                        raise LoginRequired()

            # Create a client to interact with the xiaohongshu website.
            self.wb_client = await self.create_weibo_client(httpx_proxy_format)
            if container_mode or web_qr:
                if not await self.wb_client.pong():
                    raise LoginRequired()
            elif not await self.wb_client.pong():
                login_obj = WeiboLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()

                # After successful login, redirect to mobile website and update mobile cookies
                utils.logger.info("[WeiboCrawler.start] redirect weibo mobile homepage and update cookies on mobile platform")
                await self.context_page.goto(self.mobile_index_url)
                await asyncio.sleep(3)
                # Only get mobile cookies to avoid confusion between PC and mobile cookies
                await self.wb_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

                if os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1' and not await self.wb_client.pong():
                    raise LoginRequired()

            utils.logger.info('[CrawlerStage] collecting')
            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for video and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass
            utils.logger.info("[WeiboCrawler.start] Weibo Crawler finished ...")

    async def search(self):
        """
        search weibo note with keywords
        :return:
        """
        from collection_tasks import review_progress
        review_progress("SEARCHING")
        utils.logger.info("[WeiboCrawler.search] Begin search weibo keywords")
        start_page = config.START_PAGE
        from collection_tasks import SearchProgress
        from tools.user_hash import anonymize_user_id
        progress_store = SearchProgress()
        from publication_time import PublicationWindow
        publication_window = PublicationWindow.from_environment()
        search_setting = os.environ.get('MEDIACRAWLER_WEIBO_SEARCH_TYPE', config.WEIBO_SEARCH_TYPE)

        # Set the search type based on the configuration for weibo
        if search_setting == "default":
            search_type = SearchType.DEFAULT
        elif search_setting == "real_time":
            search_type = SearchType.REAL_TIME
        elif search_setting == "popular":
            search_type = SearchType.POPULAR
        elif search_setting == "video":
            search_type = SearchType.VIDEO
        else:
            utils.logger.error(f"[WeiboCrawler.search] Invalid WEIBO_SEARCH_TYPE: {config.WEIBO_SEARCH_TYPE}")
            return

        if publication_window.active:
            search_type = SearchType.REAL_TIME
            utils.logger.info('[PublicationTime] 按最新顺序搜索；只保存指定发布时间范围内的帖子，时间缺失的帖子跳过。')

        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[WeiboCrawler.search] Current search keyword: {keyword}")
            page = progress_store.page(keyword, start_page)
            retained_count = 0
            seen_note_ids: set[str] = progress_store.seen(keyword)
            duplicate_pages = 0
            target_count = progress_store.target(keyword, config.CRAWLER_MAX_NOTES_COUNT)
            from semantic_filter import COMMENT_SAMPLE_LIMIT
            self._semantic_comments_remaining = target_count * COMMENT_SAMPLE_LIMIT
            pages_checked = 0
            old_pages = 0
            stop_reason = 'target_reached'
            diagnostics = {'pages_checked': 0, 'blocked_accounts': 0, 'evaluated': 0, 'not_retained': 0, 'outside_time_range': 0, 'unknown_publish_time': 0}
            semantic_mode = config.SAVE_DATA_OPTION == "excel" and os.environ.get("MEDIACRAWLER_SEMANTIC_FILTER") == "1"
            if semantic_mode:
                from store.excel_store_base import ExcelStoreBase
            while retained_count < target_count:
                if progress_store.run.get('max_pages') and pages_checked >= progress_store.run['max_pages']:
                    stop_reason = 'page_budget'
                    break
                pages_checked += 1
                utils.logger.info(f"[WeiboCrawler.search] search weibo keyword: {keyword}, page: {page}")
                diagnostics['pages_checked'] = pages_checked
                diagnostics['checked_page'] = page
                for field in ('http_status', 'api_ok', 'cards_count', 'parsed_count', 'message_code'):
                    diagnostics.pop(field, None)
                try:
                    search_res = await self.wb_client.get_note_by_keyword(keyword=keyword, page=page, search_type=search_type)
                except Exception as exc:
                    diagnostics.update(getattr(self.wb_client, 'last_search_response', {}))
                    diagnostics['error_type'] = type(exc).__name__
                    progress_store.record(keyword, page, result={'retained': retained_count, 'target': target_count,
                        'reason': 'login_required' if isinstance(exc, LoginRequired) else 'request_failed', 'diagnostics': diagnostics})
                    raise
                diagnostics.update(getattr(self.wb_client, 'last_search_response', {}))
                try:
                    cards = (search_res or {}).get('cards') or []
                    if isinstance(cards, list):
                        diagnostics['cards_count'] = len(cards)
                    note_list = filter_search_result_card(cards)
                except Exception:
                    progress_store.record(keyword, page, result={'retained': retained_count, 'target': target_count,
                        'reason': 'parse_failed', 'diagnostics': diagnostics})
                    raise
                diagnostics['parsed_count'] = len(note_list)
                progress_store.record(keyword, page, result={'retained': retained_count, 'target': target_count,
                    'reason': 'searching', 'diagnostics': diagnostics})
                if not note_list:
                    stop_reason = 'search_exhausted'
                    utils.logger.info(f"[WeiboCrawler.search] {keyword}: no posts on page {page}; search exhausted")
                    break
                old_pages = old_pages + 1 if publication_window.older_page([(item.get('mblog') or {}).get('created_at') for item in note_list]) else 0
                if old_pages >= 3:
                    stop_reason = 'time_range_exhausted'
                    utils.logger.info('[PublicationTime] 连续三页均早于开始时间，结束当前搜索。')
                    break
                candidates: List[Dict] = []
                page_ids = set()
                for note_item in note_list:
                    mblog = (note_item or {}).get("mblog")
                    note_id = str((mblog or {}).get("id") or "")
                    if note_id and note_id not in seen_note_ids and note_id not in page_ids:
                        page_ids.add(note_id)
                        time_reason = publication_window.exclusion(mblog.get('created_at'))
                        if time_reason:
                            diagnostics[time_reason] += 1
                            seen_note_ids.add(note_id)
                            progress_store.record(keyword, page, [note_id])
                            utils.logger.info(f'[PublicationTime] {note_id}: skipped ({time_reason})')
                            continue
                        account_reason = weibo_store.account_filter_reason(mblog.get('user'))
                        if account_reason:
                            diagnostics['blocked_accounts'] += 1
                            weibo_store.log_account_exclusion(mblog.get('user') or {}, note_id, keyword)
                            # Keep exclusion evidence in the checkpoint, without details,
                            # comments, media or model requests.
                            if semantic_mode and not account_reason.startswith('account_blocklist_'):
                                await weibo_store.update_weibo_note(note_item)
                            seen_note_ids.add(note_id)
                            progress_store.record(keyword, page, [note_id])
                            continue
                        if progress_store.blocked(anonymize_user_id((mblog.get('user') or {}).get('id'))):
                            diagnostics['blocked_accounts'] += 1
                            seen_note_ids.add(note_id)
                            progress_store.record(keyword, page, [note_id])
                            continue
                        candidates.append(note_item)
                if not candidates:
                    if page_ids:
                        # New posts excluded by account policy are not duplicate
                        # search pages. Continue searching for eligible authors.
                        duplicate_pages = 0
                        utils.logger.info(f"[AccountFilter] {keyword}: page {page} has no eligible posts; continuing search")
                        page += 1
                        progress_store.record(keyword, page)
                        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                        continue
                    duplicate_pages += 1
                    utils.logger.info(
                        f"[WeiboCrawler.search] {keyword}: page {page} contains only previously seen posts "
                        f"({duplicate_pages}/{MAX_CONSECUTIVE_DUPLICATE_PAGES}); trying the next page"
                    )
                    if duplicate_pages >= MAX_CONSECUTIVE_DUPLICATE_PAGES:
                        stop_reason = 'duplicate_pages'
                        utils.logger.info(f"[WeiboCrawler.search] {keyword}: stopped after repeated duplicate-only pages")
                        break
                    page += 1
                    progress_store.record(keyword, page)
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    continue
                duplicate_pages = 0
                # Fetch full text only for posts that have not been processed yet.
                candidates = await self.batch_get_notes_full_text(candidates)
                offset = 0
                while offset < len(candidates) and retained_count < target_count:
                    # A batch cannot produce more retained posts than the remaining target.
                    batch = candidates[offset:offset + target_count - retained_count]
                    offset += len(batch)
                    note_id_list: List[str] = []
                    for note_item in batch:
                        if semantic_mode and retained_count >= target_count:
                            break
                        note_item = await self.prepare_note(note_item)
                        mblog = note_item["mblog"]
                        diagnostics['evaluated'] += 1
                        await weibo_store.update_weibo_note(note_item)
                        if weibo_store.account_filter_reason(mblog.get("user")):
                            diagnostics['blocked_accounts'] += 1
                            seen_note_ids.add(str(mblog['id']))
                            progress_store.record(keyword, page, [str(mblog['id'])])
                            continue
                        if semantic_mode:
                            # Confirm adequate body evidence before spending requests
                            # on comments; inconclusive posts retain the comment channel.
                            if ExcelStoreBase.semantic_note_completed("weibo", mblog["id"], keyword):
                                await ExcelStoreBase.finalize_semantic_note("weibo", mblog["id"])
                                body_stop = True
                            else:
                                body_stop = await ExcelStoreBase.review_semantic_note("weibo", mblog["id"])
                            if not body_stop:
                                await self.batch_get_notes_comments([mblog["id"]])
                            if ExcelStoreBase.semantic_note_retained("weibo", mblog["id"], keyword):
                                retained_count += 1
                            else:
                                diagnostics['not_retained'] += 1
                            if (ExcelStoreBase.semantic_note_retained("weibo", mblog["id"], keyword)
                                    or ExcelStoreBase.semantic_note_media_needed("weibo", mblog["id"], keyword)):
                                await self.download_media(mblog)
                            if progress_store.path:
                                instance = ExcelStoreBase._instances.get('weibo_search')
                                state = instance.semantic_stream.states.get((str(mblog['id']), keyword)) if instance and instance.semantic_stream else None
                                if state and state.status == 'pending':
                                    stop_reason = 'semantic_unavailable'
                                    progress_store.record(keyword, page)
                                    break
                        else:
                            note_id_list.append(mblog["id"])
                            retained_count += 1
                            await self.download_media(mblog)
                        seen_note_ids.add(str(mblog['id']))
                        progress_store.record(keyword, page, [str(mblog['id'])])
                    if note_id_list:
                        await self.batch_get_notes_comments(note_id_list)
                    utils.logger.info(
                        f"[WeiboCrawler.search] {keyword}: retained {retained_count}/{target_count}"
                    )
                    if stop_reason == 'semantic_unavailable':
                        break

                if retained_count >= target_count or stop_reason == 'semantic_unavailable':
                    break
                page += 1
                progress_store.record(keyword, page)
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(
                f"[WeiboCrawler.search] {keyword}: finished with {retained_count}/{target_count} retained posts"
            )
            progress_store.record(keyword, page, result={'retained': retained_count, 'target': target_count,
                'reason': stop_reason, 'diagnostics': diagnostics})
            if semantic_mode:
                progress = ExcelStoreBase.semantic_progress("weibo", keyword)
                utils.logger.info(
                    f"[WeiboCrawler.search] {keyword}: current-run semantic decisions: {progress}. "
                    "Initially accepted posts count toward the target, including Review candidates accepted under the current policy. Final manual review is required; pending and duplicates do not count."
                )
                if retained_count < target_count:
                    if stop_reason == 'search_exhausted':
                        utils.logger.warning(
                            f"[WeiboCrawler.search] {keyword}: 搜索结果已耗尽，本组保留 "
                            f"{retained_count}/{target_count} 条，还缺 {target_count - retained_count} 条；继续下一组关键词。"
                        )
                    else:
                        utils.logger.warning(
                            f"[WeiboCrawler.search] {keyword}: target not reached; "
                            f"shortfall={target_count - retained_count}, pending={progress['pending']}, review={progress['review']}. "
                            "Resume saved pending candidates after the semantic service recovers."
                        )

    async def get_specified_notes(self):
        """
        get specified notes info
        :return:
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_note_info_task(note_id=note_id, semaphore=semaphore) for note_id in config.WEIBO_SPECIFIED_ID_LIST]
        video_details = await asyncio.gather(*task_list)
        eligible_ids = []
        for note_item in video_details:
            if note_item:
                account_reason = weibo_store.account_filter_reason((note_item.get("mblog") or {}).get("user"))
                if account_reason:
                    weibo_store.log_account_exclusion((note_item.get('mblog') or {}).get('user') or {}, (note_item.get('mblog') or {}).get('id'))
                    continue
                note_item = await self.prepare_note(note_item)
                await weibo_store.update_weibo_note(note_item)
                mblog = note_item.get("mblog")
                if mblog:
                    eligible_ids.append(mblog["id"])
                    await self.download_media(mblog)
        await self.batch_get_notes_comments(eligible_ids)

    async def get_note_info_task(self, note_id: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        """
        Get note detail task
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                result = await self.wb_client.get_note_info_by_id(note_id)
                if result and result.get('mblog'):
                    result['_metadata_status'] = {'detail': 'available'}

                # Sleep after fetching note details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.get_note_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}")

                return result
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None

    async def batch_get_notes_comments(self, note_id_list: List[str]):
        """
        batch get notes comments
        :param note_id_list:
        :return:
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[WeiboCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[WeiboCrawler.batch_get_notes_comments] note ids:{note_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_id in note_id_list:
            task = asyncio.create_task(self.get_note_comments(note_id, semaphore), name=note_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_note_comments(self, note_id: str, semaphore: asyncio.Semaphore):
        """
        get comment for note id
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            comments_available = False
            comment_stop_reason = None
            semantic_mode = config.SAVE_DATA_OPTION == "excel" and os.environ.get("MEDIACRAWLER_SEMANTIC_FILTER") == "1"
            options = {}
            limit = max(0, config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES)
            sample_count = 0
            save_comments = weibo_store.batch_update_weibo_note_comments
            if semantic_mode:
                from store.excel_store_base import ExcelStoreBase
                from semantic_filter import COMMENT_SAMPLE_LIMIT
                remaining = getattr(self, '_semantic_comments_remaining', COMMENT_SAMPLE_LIMIT)
                limit = min(limit, COMMENT_SAMPLE_LIMIT, remaining)
                self._semantic_comments_remaining = remaining - limit
                utils.logger.info(f'[SemanticComments] {note_id}: 正文判断不确定，最多补采 {limit} 条一级评论，不采回复')

                async def save_comments(_note_id, comments):
                    nonlocal sample_count
                    sample_count += len(comments)
                    await weibo_store.batch_update_weibo_note_comments(_note_id, comments)

                async def review_page(_note_id, _comments):
                    return await ExcelStoreBase.review_semantic_note("weibo", _note_id)

                async def record_completion(complete, reason):
                    nonlocal comments_available, comment_stop_reason
                    comments_available, comment_stop_reason = complete, reason

                options = {
                    "page_callback": review_page, "completion_callback": record_completion,
                    # Also bound empty pages with changing cursors.
                    "max_pages": 1,
                }
            try:
                utils.logger.info(f"[WeiboCrawler.get_note_comments] begin get note_id: {note_id} comments ...")

                # Sleep before fetching comments
                if not semantic_mode or limit > 0:
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.get_note_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_id}")

                await self.wb_client.get_note_all_comments(
                    note_id=note_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,  # Use fixed interval instead of random
                    callback=save_comments,
                    max_count=limit,
                    include_sub_comments=not semantic_mode,
                    **options,
                )
                if not semantic_mode:
                    comments_available = True
            except SemanticFilterError:
                raise
            except LoginRequired as ex:
                comment_stop_reason = 'comments_fetch_failed'
                self._record_comment_failure(note_id, ex)
                raise
            except DataFetchError as ex:
                comment_stop_reason = 'comments_fetch_failed'
                self._record_comment_failure(note_id, ex)
            except Exception as e:
                comment_stop_reason = 'comments_fetch_failed'
                self._record_comment_failure(note_id, e)
            finally:
                if semantic_mode:
                    self._semantic_comments_remaining += limit - sample_count
                if config.SAVE_DATA_OPTION == "excel":
                    from store.excel_store_base import ExcelStoreBase
                    await ExcelStoreBase.finalize_semantic_note(
                        "weibo", note_id, comments_available, comment_stop_reason=comment_stop_reason,
                    )

    def _record_comment_failure(self, note_id, exception):
        from comment_audit import failure_details, record_result
        details = failure_details(exception, getattr(self.wb_client, 'comment_diagnostics', {}).get(str(note_id)))
        try:
            record_result(note_id, details)
        except (OSError, ValueError) as error:
            utils.logger.error(f'[CommentFetch] Cannot persist failure for note {note_id}: {type(error).__name__}')
        utils.logger.error(f"[CommentFetch] note {note_id}: {details['reason']}; HTTP {details.get('http_status')}; "
                           f"{details['explanation']} {details['response_message']}")

    async def download_media(self, mblog: Dict) -> None:
        """下载微博的媒体资源（配图，或视频 + 封面）

        :param mblog: 微博正文数据
        """
        if not config.ENABLE_GET_MEDIA:
            return
        try:
            items = weibo_media.build_media_items(mblog)
            if items:
                await self._get_media_downloader().download_all(items)
        except Exception as exc:
            # 媒体下载是旁路能力，解析异常/网络异常都不能中断爬取主流程
            utils.logger.error(f"[WeiboCrawler.download_media] 媒体下载异常: {exc}")

    def _get_media_downloader(self) -> MediaDownloader:
        """惰性创建媒体下载器，并同步最新的代理与 UA（代理池是就地刷新的）"""
        if self._media_downloader is None:
            self._media_downloader = MediaDownloader(
                platform="wb",
                proxy=getattr(self.wb_client, "proxy", None),
                extra_headers=self._media_headers(),
            )
        else:
            self._media_downloader.update_credentials(
                proxy=getattr(self.wb_client, "proxy", None),
                extra_headers=self._media_headers(),
            )
        return self._media_downloader

    def _media_headers(self) -> Dict:
        """媒体请求头：平台 Referer（防盗链）+ UA。

        client.headers 里含 Cookie，不能整体透传到 CDN 请求上，因此只取 UA。
        """
        headers = {"Referer": "https://weibo.com/"}
        client_headers = getattr(self.wb_client, "headers", {}) or {}
        if client_headers.get("User-Agent"):
            headers["User-Agent"] = client_headers["User-Agent"]
        return headers

    async def get_creators_and_notes(self) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        utils.logger.info("[WeiboCrawler.get_creators_and_notes] Begin get weibo creators")
        for user_id in config.WEIBO_CREATOR_ID_LIST:
            account_reason = weibo_store.blocked_uid_reason(user_id)
            if account_reason:
                utils.logger.info(f"[AccountFilter] creator skipped ({account_reason})")
                continue
            createor_info_res: Dict = await self.wb_client.get_creator_info_by_id(creator_id=user_id)
            if createor_info_res:
                createor_info: Dict = createor_info_res.get("userInfo", {})
                utils.logger.info(f"[WeiboCrawler.get_creators_and_notes] creator info: {createor_info}")
                if not createor_info:
                    raise DataFetchError("Get creator info error")
                account_reason = weibo_store.account_filter_reason(createor_info)
                if account_reason:
                    weibo_store.log_account_exclusion(createor_info, '')
                    continue
                await weibo_store.save_creator(user_id, user_info=createor_info)

                # Create a wrapper callback to get full text before saving data
                async def save_notes_with_full_text(note_list: List[Dict]):
                    note_list = [item for item in note_list if not weibo_store.account_filter_reason((item.get("mblog") or {}).get("user"))]
                    # If full text fetching is enabled, batch get full text first
                    updated_note_list = await self.batch_get_notes_full_text(note_list)
                    updated_note_list = [await self.prepare_note(item) for item in updated_note_list]
                    await weibo_store.batch_update_weibo_notes(updated_note_list)
                    for note_item in updated_note_list:
                        mblog = (note_item or {}).get("mblog")
                        if mblog and not weibo_store.account_filter_reason(mblog.get("user")):
                            await self.download_media(mblog)

                # Get all note information of the creator
                all_notes_list = await self.wb_client.get_all_notes_by_creator_id(
                    creator_id=user_id,
                    container_id=f"107603{user_id}",
                    crawl_interval=0,
                    callback=save_notes_with_full_text,
                )

                note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes_list if note_item.get("mblog", {}).get("id") and not weibo_store.account_filter_reason(note_item.get("mblog", {}).get("user"))]
                await self.batch_get_notes_comments(note_ids)

            else:
                utils.logger.error(f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_id:{user_id}")

    async def create_weibo_client(self, httpx_proxy: Optional[str]) -> WeiboClient:
        """Create xhs client"""
        utils.logger.info("[WeiboCrawler.create_weibo_client] Begin create weibo API client ...")
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )
        weibo_client_obj = WeiboClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": utils.get_mobile_user_agent(),
                "Cookie": cookie_str,
                "Origin": "https://m.weibo.cn",
                "Referer": "https://m.weibo.cn",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return weibo_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[WeiboCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
                channel=os.environ.get('MEDIACRAWLER_BROWSER_CHANNEL', 'chrome') or None,
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel=os.environ.get('MEDIACRAWLER_BROWSER_CHANNEL', 'chrome') or None)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        Launch browser with CDP mode
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[WeiboCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[WeiboCrawler] CDP mode startup failed, falling back to standard mode: {e}")
            # Fallback to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def prepare_note(self, note_item: Dict) -> Dict:
        """Enrich only newly collected, eligible posts before they are saved."""
        from .metadata import MetadataEnricher
        if weibo_store.account_filter_reason((note_item.get('mblog') or {}).get('user')):
            return note_item
        if not hasattr(self, '_metadata_enricher'):
            self._metadata_enricher = MetadataEnricher(self.wb_client, config.CRAWLER_MAX_SLEEP_SEC)
        return await self._metadata_enricher.enrich(note_item)

    async def get_note_full_text(self, note_item: Dict) -> Dict:
        """
        Get full text content of a post
        If the post content is truncated (isLongText=True), request the detail API to get complete content
        :param note_item: Post data, contains mblog field
        :return: Updated post data
        """
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_item

        mblog = note_item.get("mblog", {})
        if not mblog:
            return note_item
        if weibo_store.account_filter_reason(mblog.get("user")):
            return note_item

        # Check if it's a long text
        is_long_text = mblog.get("isLongText", False)
        if not is_long_text:
            return note_item

        note_id = mblog.get("id")
        if not note_id:
            return note_item

        full_text_available = False
        note_item.setdefault('_metadata_status', {})['detail'] = 'unavailable'
        try:
            utils.logger.info(f"[WeiboCrawler.get_note_full_text] Fetching full text for note: {note_id}")
            full_note = await self.wb_client.get_note_info_by_id(note_id)
            if full_note and full_note.get("mblog"):
                from .metadata import merge_detail
                note_item["mblog"] = merge_detail(mblog, full_note["mblog"])
                full_text_available = (str(full_note['mblog'].get('id')) == str(note_id)
                                       and len(full_note['mblog'].get('text') or '') >= len(mblog.get('text') or ''))
                note_item['_metadata_status']['detail'] = 'available' if full_text_available else 'unavailable'
                utils.logger.info(f"[WeiboCrawler.get_note_full_text] Successfully fetched full text for note: {note_id}")

            # Sleep after request to avoid rate limiting
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
        except DataFetchError as ex:
            note_item['_metadata_status']['detail'] = 'failed'
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Failed to fetch full text for note {note_id}: {ex}")
        except Exception as ex:
            note_item['_metadata_status']['detail'] = 'failed'
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Unexpected error for note {note_id}: {ex}")

        if not full_text_available:
            note_item["_semantic_full_text_incomplete"] = True
        return note_item

    async def batch_get_notes_full_text(self, note_list: List[Dict]) -> List[Dict]:
        """
        Batch get full text content of posts
        :param note_list: List of posts
        :return: Updated list of posts
        """
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_list

        result = []
        for note_item in note_list:
            updated_note = await self.get_note_full_text(note_item)
            result.append(updated_note)
        return result

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[WeiboCrawler.close] Browser context closed ...")

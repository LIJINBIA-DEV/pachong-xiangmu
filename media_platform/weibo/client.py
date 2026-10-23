# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/weibo/client.py
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
# @Time    : 2023/12/23 15:40
# @Desc    : Weibo crawler API request client

import asyncio
import copy
import json
import os
import re
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import httpx
from httpx import Response
from playwright.async_api import BrowserContext, Page
from tools.httpx_util import make_async_client
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_not_exception_type

import config
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import DataFetchError, LoginRequired, CommentsUnavailable
from .field import SearchType


class WeiboClient(ProxyRefreshMixin):

    def __init__(
        self,
        timeout=60,  # If media crawling is enabled, Weibo images need a longer timeout
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://m.weibo.cn"
        self.cookie_urls = [self._host]
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self.last_search_response = {}
        self.comment_diagnostics = {}
        # Initialize proxy pool (from ProxyRefreshMixin)
        self.init_proxy_pool(proxy_ip_pool)

    @retry(stop=stop_after_attempt(5), wait=wait_fixed(3), retry=retry_if_not_exception_type((LoginRequired, CommentsUnavailable)))
    async def request(self, method, url, **kwargs) -> Union[Response, Dict]:
        # Check if proxy is expired before each request
        await self._refresh_proxy_if_expired()

        enable_return_response = kwargs.pop("return_response", False)
        target = urlsplit(url)
        query = parse_qs(target.query)
        is_search = (method.upper() == 'GET' and target.path == '/api/container/getIndex'
                     and query.get('page_type') == ['searchall'])
        is_comments = target.path == '/comments/hotflow'
        comment_info = None
        if is_comments:
            self.comment_diagnostics = getattr(self, 'comment_diagnostics', {})
            comment_info = self.comment_diagnostics.setdefault(str(query.get('id', [''])[0]), {})
            comment_info['request_count'] = comment_info.get('request_count', 0) + 1
            for key in ('http_status', 'api_ok', 'response_message', 'message_code'):
                comment_info.pop(key, None)
        if is_search:
            self.last_search_response = {'message_code': 'request_failed'}
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)
        if is_search:
            self.last_search_response['http_status'] = response.status_code
        if comment_info is not None:
            comment_info['http_status'] = response.status_code

        if enable_return_response:
            return response

        cookie_mode = os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1'
        if cookie_mode and (response.status_code in {401, 403, 432}
                or any(fragment in str(response.url).lower() for fragment in ('passport.weibo', '/sso/signin'))):
            if is_search:
                self.last_search_response['message_code'] = 'login_required'
            raise LoginRequired()

        try:
            data: Dict = response.json()
        except json.decoder.JSONDecodeError:
            if cookie_mode and any(fragment in response.text.lower() for fragment in ('passport.weibo', '登录', '验证码')):
                if is_search:
                    self.last_search_response['message_code'] = 'login_required'
                raise LoginRequired()
            if comment_info is not None:
                comment_info['message_code'] = 'non_json'
                raise DataFetchError(f'Comment response is not JSON; HTTP {response.status_code}')
            if is_search:
                self.last_search_response['message_code'] = 'non_json'
            # issue: #771 Search API returns error 432, retry multiple times + update h5 cookies
            utils.logger.error(f"[WeiboClient.request] request {method}:{url} err code: {response.status_code} res:{response.text}")
            await self.playwright_page.goto(self._host)
            await asyncio.sleep(2)
            await self.update_cookies(browser_context=self.playwright_page.context)
            raise DataFetchError(f"get response code error: {response.status_code}")

        if is_comments and not isinstance(data, dict):
            raise DataFetchError('Invalid comment response: expected an object')
        ok_code = data.get("ok")
        if comment_info is not None:
            from comment_audit import safe_message
            comment_info.update(api_ok=ok_code, response_message=safe_message(data.get('msg', '')))
        if cookie_mode and ok_code != 1 and any(fragment in str(data.get('msg', '')) for fragment in ('登录', '验证', '认证')):
            if is_search:
                self.last_search_response['message_code'] = 'login_required'
            raise LoginRequired()
        if is_search:
            # Persist only counts and recognized platform messages, never raw
            # response bodies, request headers, cookies or credential-bearing URLs.
            payload = data.get('data')
            cards = payload.get('cards') if isinstance(payload, dict) else None
            self.last_search_response.update({
                'api_ok': ok_code if isinstance(ok_code, int) else None,
                'cards_count': len(cards) if isinstance(cards, list) else None,
                'message_code': 'empty_result' if str(data.get('msg', '')).strip() == '这里还没有内容'
                    else 'success' if ok_code == 1 else 'api_error',
            })
        if ok_code == 0:  # response error
            # Search exhaustion is a successful empty page. Restrict this to
            # the search endpoint and its exact empty-result response so login,
            # rate-limit, server and other API errors remain retryable failures.
            target = urlsplit(url)
            query = parse_qs(target.query)
            payload = data.get("data")
            if (method.upper() == "GET" and 200 <= response.status_code < 300
                    and target.path == "/api/container/getIndex"
                    and query.get("page_type") == ["searchall"]
                    and str(data.get("msg", "")).strip() == "这里还没有内容"
                    and isinstance(payload, dict) and payload.get("cards") == []):
                return payload
            # Weibo reports an empty comment section as ok=0. This is a normal
            # completed fetch, not a retryable failure or a missing comment set.
            if "/comments/hotflow" in url and "还没有人评论" in str(data.get("msg", "")):
                return {"max_id": 0, "max_id_type": 0, "data": []}
            if is_comments and '已过滤部分评论' in str(data.get('msg', '')) and not data.get('data'):
                raise CommentsUnavailable('已过滤部分评论')
            if is_comments:
                raise DataFetchError(comment_info.get('response_message') or 'Comment API returned ok=0')
            utils.logger.error(f"[WeiboClient.request] request {method}:{url} err, res:{data}")
            raise DataFetchError(data.get("msg", "response error"))
        elif ok_code != 1:  # unknown error
            if is_comments:
                raise DataFetchError(comment_info.get('response_message') or 'Unknown comment API error')
            utils.logger.error(f"[WeiboClient.request] request {method}:{url} err, res:{data}")
            raise DataFetchError(data.get("msg", "unknown error"))
        else:  # response right
            return data.get("data", {})

    async def get(self, uri: str, params=None, headers=None, **kwargs) -> Union[Response, Dict]:
        final_uri = uri
        if isinstance(params, dict):
            final_uri = (f"{uri}?"
                         f"{urlencode(params)}")

        if headers is None:
            headers = self.headers
        return await self.request(method="GET", url=f"{self._host}{final_uri}", headers=headers, **kwargs)

    async def post(self, uri: str, data: dict) -> Dict:
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        return await self.request(method="POST", url=f"{self._host}{uri}", data=json_str, headers=self.headers)

    async def pong(self) -> bool:
        """get a note to check if login state is ok"""
        utils.logger.info("[WeiboClient.pong] Begin pong weibo...")
        ping_flag = False
        try:
            uri = "/api/config"
            resp_data: Dict = await self.request(method="GET", url=f"{self._host}{uri}", headers=self.headers)
            if resp_data.get("login"):
                ping_flag = True
            else:
                utils.logger.error(f"[WeiboClient.pong] cookie may be invalid and again login...")
        except Exception as e:
            if os.environ.get('MEDIACRAWLER_CONTAINER_MODE') == '1':
                # Do not turn transport/server failures into an invalid-Cookie result.
                raise
            utils.logger.error(f"[WeiboClient.pong] Pong weibo failed: {e}, and try to login again...")
            ping_flag = False
        return ping_flag

    async def update_cookies(self, browser_context: BrowserContext, urls: Optional[List[str]] = None):
        """
        Update cookies from browser context
        :param browser_context: Browser context
        :param urls: Optional list of URLs to filter cookies (e.g., ["https://m.weibo.cn"])
                     If provided, only cookies for these URLs will be retrieved
        """
        cookie_urls = urls or self.cookie_urls
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context,
            urls=cookie_urls,
        )
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict
        utils.logger.info(
            f"[WeiboClient.update_cookies] Cookie updated successfully for {cookie_urls}, total: {len(cookie_dict)} cookies"
        )

    async def get_note_by_keyword(
        self,
        keyword: str,
        page: int = 1,
        search_type: SearchType = SearchType.DEFAULT,
    ) -> Dict:
        """
        search note by keyword
        :param keyword: Search keyword for Weibo
        :param page: Pagination parameter - current page number
        :param search_type: Search type, see SearchType enum in weibo/field.py
        :return:
        """
        uri = "/api/container/getIndex"
        containerid = f"100103type={search_type.value}&q={keyword}"
        params = {
            "containerid": containerid,
            "page_type": "searchall",
            "page": page,
        }
        return await self.get(uri, params)

    async def get_note_comments(self, mid_id: str, max_id: int, max_id_type: int = 0) -> Dict:
        """get notes comments
        :param mid_id: Weibo ID
        :param max_id: Pagination parameter ID
        :param max_id_type: Pagination parameter ID type
        :return:
        """
        uri = "/comments/hotflow"
        params = {
            "id": mid_id,
            "mid": mid_id,
            "max_id_type": max_id_type,
        }
        if max_id > 0:
            params.update({"max_id": max_id})
        referer_url = f"https://m.weibo.cn/detail/{mid_id}"
        headers = copy.copy(self.headers)
        headers["Referer"] = referer_url

        return await self.get(uri, params, headers=headers)

    async def get_note_all_comments(
        self,
        note_id: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int | None = 10,
        include_sub_comments: bool = True,
        page_callback: Optional[Callable] = None,
        completion_callback: Optional[Callable] = None,
        max_pages: int | None = None,
    ):
        """
        get note all comments include sub comments
        :param note_id:
        :param crawl_interval:
        :param callback:
        :param max_count:
        :return:
        """
        result = []
        self.comment_diagnostics = getattr(self, 'comment_diagnostics', {})
        self.comment_diagnostics[str(note_id)] = {'request_count': 0, 'page_count': 0}
        is_end = False
        max_id = -1
        max_id_type = 0
        seen_cursors: set[tuple[int, int]] = set()
        seen_comments: set[str] = set()
        page_count = 0
        stop_reason = "comment_budget_exhausted"
        while not is_end and (max_count is None or len(result) < max_count):
            if max_pages is not None and page_count >= max_pages:
                stop_reason = "comment_page_budget_exhausted"
                break
            cursor = (max_id, max_id_type)
            if cursor in seen_cursors:
                raise DataFetchError(f"Repeated comment cursor for note {note_id}; comment collection is incomplete")
            seen_cursors.add(cursor)
            comments_res = await self.get_note_comments(note_id, max_id, max_id_type)
            page_count += 1
            self.comment_diagnostics[str(note_id)]['page_count'] = page_count
            if not isinstance(comments_res, dict):
                raise DataFetchError('Invalid comment response: expected comment page object')
            next_id = comments_res.get("max_id")
            if next_id is None:
                raise DataFetchError(f"Missing comment cursor for note {note_id}; comment collection is incomplete")
            max_id = int(next_id)
            max_id_type = int(comments_res.get("max_id_type") or 0)
            comment_list: List[Dict] = comments_res.get("data") or []
            if not isinstance(comment_list, list) or any(not isinstance(item, dict) for item in comment_list):
                raise DataFetchError(f"Invalid comment data for note {note_id}; comment collection is incomplete")
            unique = []
            for item in comment_list:
                cid = str(item.get("id") or item.get("idstr") or "")
                if cid and cid in seen_comments:
                    continue
                if cid:
                    seen_comments.add(cid)
                unique.append(item)
            comment_list = unique
            is_end = max_id == 0
            if max_count is not None and len(result) + len(comment_list) > max_count:
                comment_list = comment_list[:max_count - len(result)]
                # The server's final page may itself exceed the remaining budget.
                is_end = False
            if callback:  # If callback function exists, execute it
                await callback(note_id, comment_list)
            result.extend(comment_list)
            if include_sub_comments:
                sub_comment_result = await self.get_comments_all_sub_comments(note_id, comment_list, callback)
                result.extend(sub_comment_result)
            page_stop = await page_callback(note_id, comment_list) if page_callback else None
            if page_stop:
                stop_reason = page_stop if isinstance(page_stop, str) else "evidence_found"
                break
            if is_end:
                stop_reason = "comments_exhausted"
                break
            if max_count is not None and len(result) >= max_count:
                break
            if max_pages is not None and page_count >= max_pages:
                stop_reason = "comment_page_budget_exhausted"
                break
            await asyncio.sleep(crawl_interval)
        if completion_callback:
            await completion_callback(is_end, stop_reason)
        return result

    @staticmethod
    async def get_comments_all_sub_comments(
        note_id: str,
        comment_list: List[Dict],
        callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Get all sub-comments of comments
        Args:
            note_id:
            comment_list:
            callback:

        Returns:

        """
        if not config.ENABLE_GET_SUB_COMMENTS:
            utils.logger.info(f"[WeiboClient.get_comments_all_sub_comments] Crawling sub_comment mode is not enabled")
            return []

        res_sub_comments = []
        for comment in comment_list:
            sub_comments = comment.get("comments")
            if sub_comments and isinstance(sub_comments, list):
                await callback(note_id, sub_comments)
                res_sub_comments.extend(sub_comments)
        return res_sub_comments

    async def get_note_info_by_id(self, note_id: str) -> Dict:
        """
        Get note details by note ID
        :param note_id:
        :return:
        """
        url = f"{self._host}/detail/{note_id}"
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request("GET", url, timeout=self.timeout, headers=self.headers)
            if response.status_code != 200:
                raise DataFetchError(f"get weibo detail err: {response.text}")
            match = re.search(r'var \$render_data = (\[.*?\])\[0\]', response.text, re.DOTALL)
            if match:
                render_data_json = match.group(1)
                render_data_dict = json.loads(render_data_json)
                note_detail = render_data_dict[0].get("status")
                note_item = {"mblog": note_detail}
                return note_item
            else:
                utils.logger.info(f"[WeiboClient.get_note_info_by_id] $render_data value not found")
                return dict()


    async def get_creator_container_info(self, creator_id: str) -> Dict:
        """
        Get user's container ID, container information represents the real API request path
            fid_container_id: Container ID for user's Weibo detail API
            lfid_container_id: Container ID for user's Weibo list API
        Args:
            creator_id: User ID

        Returns: Dictionary with container IDs

        """
        response = await self.get(f"/u/{creator_id}", return_response=True)
        m_weibocn_params = response.cookies.get("M_WEIBOCN_PARAMS")
        if not m_weibocn_params:
            raise DataFetchError("get containerid failed")
        m_weibocn_params_dict = parse_qs(unquote(m_weibocn_params))
        return {"fid_container_id": m_weibocn_params_dict.get("fid", [""])[0], "lfid_container_id": m_weibocn_params_dict.get("lfid", [""])[0]}

    async def get_creator_info_by_id(self, creator_id: str) -> Dict:
        """
        Get user details by user ID
        Args:
            creator_id:

        Returns:

        """
        uri = "/api/container/getIndex"
        containerid = f"100505{creator_id}"
        params = {
            "jumpfrom": "weibocom",
            "type": "uid",
            "value": creator_id,
            "containerid":containerid,
        }
        user_res = await self.get(uri, params)
        return user_res

    async def get_notes_by_creator(
        self,
        creator: str,
        container_id: str,
        since_id: str = "0",
    ) -> Dict:
        """
        Get creator's notes
        Args:
            creator: Creator ID
            container_id: Container ID
            since_id: ID of the last note from previous page
        Returns:

        """

        uri = "/api/container/getIndex"
        params = {
            "jumpfrom": "weibocom",
            "type": "uid",
            "value": creator,
            "containerid": container_id,
            "since_id": since_id,
        }
        return await self.get(uri, params)

    async def get_all_notes_by_creator_id(
        self,
        creator_id: str,
        container_id: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Get all posts published by a specified user, this method will continuously fetch all posts from a user
        Args:
            creator_id: Creator user ID
            container_id: Container ID for the user
            crawl_interval: Interval between requests in seconds
            callback: Optional callback function to process notes

        Returns: List of all notes

        """
        result = []
        notes_has_more = True
        since_id = ""
        crawler_total_count = 0
        while notes_has_more:
            notes_res = await self.get_notes_by_creator(creator_id, container_id, since_id)
            if not notes_res:
                utils.logger.error(f"[WeiboClient.get_notes_by_creator] The current creator may have been banned by Weibo, so they cannot access the data.")
                break
            since_id = notes_res.get("cardlistInfo", {}).get("since_id", "0")
            if "cards" not in notes_res:
                utils.logger.info(f"[WeiboClient.get_all_notes_by_creator] No 'notes' key found in response: {notes_res}")
                break

            notes = notes_res["cards"]
            utils.logger.info(f"[WeiboClient.get_all_notes_by_creator] got user_id:{creator_id} notes len : {len(notes)}")
            notes = [note for note in notes if note.get("card_type") == 9]
            if callback:
                await callback(notes)
            await asyncio.sleep(crawl_interval)
            result.extend(notes)
            crawler_total_count += 10
            notes_has_more = notes_res.get("cardlistInfo", {}).get("total", 0) > crawler_total_count
        return result

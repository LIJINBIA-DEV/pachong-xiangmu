# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/crawler.py
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

from typing import Literal

from fastapi import APIRouter, HTTPException, Response, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, SecretStr

from semantic_filter import MODEL, check_jev_connection

from ..schemas import CrawlerStartRequest, CrawlerStatusResponse
from ..services import crawler_manager

class PrivateSemanticInputRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        if not self.path.endswith(('/crawler/semantic-settings', '/crawler/semantic-key-check')):
            return handler
        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, 'semantic_settings_invalid_request') from None
        return private_handler


router = APIRouter(prefix="/crawler", tags=["crawler"], route_class=PrivateSemanticInputRoute)

from api.services import semantic_settings
from api.services.semantic_settings import SemanticSettingsUpdate


@router.get('/semantic-settings')
def semantic_key_status(response: Response):
    from api.routers.data import data_root
    response.headers['Cache-Control'] = 'no-store'
    try:
        return semantic_settings.public_settings(data_root())
    except Exception:
        raise HTTPException(422, 'semantic_settings_storage_failed') from None


@router.put('/semantic-settings')
def save_semantic_key(change: SemanticSettingsUpdate, request: Request, response: Response):
    from urllib.parse import urlsplit
    from api.routers.data import data_root
    response.headers['Cache-Control'] = 'no-store'
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'semantic_settings_origin_denied')
    try:
        result = semantic_settings.save_settings(data_root(), change)
        for cached in list(crawler_manager.task_credentials.values()):
            cached.pop('semantic_api_key', None)
        return result
    except Exception:
        raise HTTPException(422, 'semantic_settings_save_failed') from None


class WebLoginRequest(BaseModel):
    refresh: bool = False
    login_environment: Literal['auto', 'local', 'server'] = 'auto'


@router.get('/weibo-login')
async def weibo_login_status(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    from api.services.weibo_login import weibo_web_login
    return weibo_web_login.status()


@router.post('/weibo-login')
async def start_weibo_login(request: WebLoginRequest):
    from api.services.weibo_login import weibo_web_login
    try:
        return await weibo_web_login.start(crawler_manager, refresh=request.refresh, login_environment=request.login_environment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/weibo-login')
async def cancel_weibo_login():
    from api.services.weibo_login import weibo_web_login
    return await weibo_web_login.cancel(crawler_manager)


@router.get('/xhs-login')
async def xhs_login_status(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    from api.services.xhs_login import xhs_web_login
    return xhs_web_login.status()


@router.post('/xhs-login')
async def start_xhs_login(request: WebLoginRequest):
    from api.services.xhs_login import xhs_web_login
    try:
        return await xhs_web_login.start(crawler_manager, refresh=request.refresh, login_environment=request.login_environment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/xhs-login')
async def cancel_xhs_login():
    from api.services.xhs_login import xhs_web_login
    return await xhs_web_login.cancel(crawler_manager)


class SemanticKeyCheckRequest(BaseModel):
    api_key: SecretStr | None = None
    model: str = MODEL


@router.post("/semantic-key-check")
async def check_semantic_key(request: SemanticKeyCheckRequest):
    """Test the selected Jev model using an explicit or saved credential."""
    from api.routers.data import data_root
    api_key = (request.api_key.get_secret_value() if request.api_key else "") or semantic_settings.runtime_key(data_root())
    try:
        return await check_jev_connection(api_key.strip(), request.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start crawler task"""
    try:
        success = await crawler_manager.start(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        # Handle concurrent/duplicate requests: if process is already running, return 400 instead of 500
        if crawler_manager.process and crawler_manager.process.poll() is None:
            raise HTTPException(status_code=400, detail="Crawler is already running")
        raise HTTPException(status_code=500, detail="Failed to start crawler")

    return {"status": "ok", "message": "Crawler started successfully"}


@router.post("/stop")
async def stop_crawler():
    """Stop crawler task"""
    success = await crawler_manager.stop()
    if not success:
        # Handle concurrent/duplicate requests: if process already exited/doesn't exist, return 400 instead of 500
        if not crawler_manager.process or crawler_manager.process.poll() is not None:
            raise HTTPException(status_code=400, detail="No crawler is running")
        raise HTTPException(status_code=500, detail="Failed to stop crawler")

    return {"status": "ok", "message": "Crawler stopped successfully"}


@router.get("/status", response_model=CrawlerStatusResponse)
async def get_crawler_status():
    """Get crawler status"""
    return crawler_manager.get_status()


@router.get("/logs")
async def get_logs(limit: int = 100):
    """Get recent logs"""
    logs = crawler_manager.logs[-limit:] if limit > 0 else crawler_manager.logs
    return {"logs": [log.model_dump() for log in logs]}

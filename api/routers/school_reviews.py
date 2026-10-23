"""Authenticated loopback bridge used only by Ragent, not by the model directly."""
import os
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from api.services import crawler_manager
from api.services.school_reviews import SchoolReviewJobs

jobs = SchoolReviewJobs(crawler_manager)


def authenticate(x_ragent_token: str = Header(default='')):
    expected = os.environ.get('RAGENT_REVIEW_TOKEN', '')
    if not expected or not secrets.compare_digest(expected.encode(), x_ragent_token.encode()):
        raise HTTPException(401, 'bridge_unauthorized')


router = APIRouter(prefix='/school-reviews', tags=['school-reviews'], dependencies=[Depends(authenticate)])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner: str = Field(min_length=1, max_length=100)
    school: str = Field(min_length=2, max_length=60)
    topic: str = Field(default='计算机专硕就读体验', min_length=1, max_length=40)
    platform: Literal['xhs', 'wb', 'zhihu', 'bili'] = 'xhs'
    refresh: bool = False

    @field_validator('school', 'topic')
    @classmethod
    def safe_keywords(cls, value):
        value = value.strip()
        if not value or any(c in value for c in ',，\n\r\x00'):
            raise ValueError('请使用单个学校和主题，不允许逗号、换行')
        return value

    @field_validator('school')
    @classmethod
    def full_school(cls, value):
        if len(value) < 2:
            raise ValueError('请提供学校全称')
        return value


@router.post('')
async def start(request: ReviewRequest):
    try:
        return await jobs.start(**request.model_dump())
    except ValueError:
        raise HTTPException(409, '采集暂不可用，请先完成或取消工作台登录、检查已有采集任务。') from None


@router.get('/features')
async def features():
    return {**jobs.settings.public(), 'scheduler_running': jobs.scheduler is not None and not jobs.scheduler.done(),
            'prewarm_state': jobs.prewarm_state}


@router.get('/{job_id}')
async def status(job_id: str, owner: str = Query(min_length=1, max_length=100)):
    try:
        return jobs.public(jobs.read(job_id, owner))
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, '任务不存在或不属于当前用户') from None


@router.delete('/{job_id}')
async def cancel(job_id: str, owner: str = Query(min_length=1, max_length=100)):
    try:
        return await jobs.cancel(job_id, owner)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, '任务不存在或不属于当前用户') from None

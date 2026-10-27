from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from api.routers.data import data_root
from api.services import crawler_manager
from api.services.dashboard import dashboard_snapshot

router = APIRouter(prefix='/dashboard', tags=['dashboard'])


@router.get('')
def get_dashboard(period: Literal['task', 'today', 'week', 'month', 'year', 'custom'] = 'task',
                  start: datetime | None = None, end: datetime | None = None,
                  task_id: str | None = Query(None, pattern=r'^[a-f0-9]{32}$')):
    try:
        return dashboard_snapshot(data_root(), crawler_manager, period, start, end, task_id)
    except ValueError as exc:
        if str(exc) == 'invalid_date_range':
            raise HTTPException(status_code=422, detail='invalid_date_range') from exc
        raise HTTPException(status_code=422, detail='dashboard_data_unavailable') from exc
    except (OSError, KeyError, TypeError):
        raise HTTPException(status_code=422, detail='dashboard_data_unavailable')


@router.get('/progress')
def get_collection_progress():
    from api.services.dashboard import collection_progress
    try:
        return collection_progress(data_root(), crawler_manager)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(422, 'collection_progress_unavailable') from None

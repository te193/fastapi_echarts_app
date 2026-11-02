"""Page-only analytics, independent of business requests and ETL."""
import logging
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .services.page_usage import page_usage_service
from . import label_update_policy

router = APIRouter()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))
templates.env.globals['label_update_policy'] = label_update_policy


class Visit(BaseModel):
    page_id: str = Field(min_length=1, max_length=64)
    browser_id: UUID
    visit_id: UUID
    environment: Literal['production', 'test'] = 'production'


@router.get('/page-usage', response_class=HTMLResponse)
def page_usage_page(request: Request):
    return templates.TemplateResponse(request, 'page_usage.html',
                                      {'page': 'page_usage', 'title': '页面使用统计'})


@router.post('/api/page-usage/visits')
def record_visit(request: Request, visit: Visit):
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '只接受本站页面访问')
    environment = visit.environment
    if (request.url.port == 8001 or os.getenv('DASHBOARD_USAGE_ENV') == 'test'
            or os.getenv('DASHBOARD_PORT') == '8001'):
        environment = 'test'
    try:
        recorded = page_usage_service.record_visit(visit.page_id, str(visit.browser_id),
                                                    str(visit.visit_id), environment)
        return {'recorded': recorded, 'environment': environment}
    except ValueError as exc:
        raise HTTPException(422, '页面或访问参数无效') from exc
    except (sqlite3.Error, OSError) as exc:
        logger.warning('Page usage storage unavailable: %s', type(exc).__name__)
        raise HTTPException(503, '访问记录暂不可用，业务页面不受影响') from exc


@router.get('/api/page-usage')
def usage_summary(environment: Literal['production', 'test', 'all'] = 'production'):
    try:
        return page_usage_service.summary(environment)
    except (sqlite3.Error, OSError) as exc:
        logger.warning('Page usage summary unavailable: %s', type(exc).__name__)
        raise HTTPException(503, '访问统计暂不可用，请稍后重试') from exc

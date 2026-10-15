"""Read-only label analysis routes, isolated from the existing label hub."""
import logging
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from .services.label_analysis_service import AnalysisQuery, StaleAnalysis, label_analysis_service

router=APIRouter()
templates=Jinja2Templates(directory=str(Path(__file__).parent/'templates'))
logger=logging.getLogger(__name__)


def invoke(method,*args):
    try:return method(*args)
    except StaleAnalysis as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    except Exception as exc:
        logger.exception('Label analysis read failed')
        raise HTTPException(503,'分析数据暂不可用，请稍后刷新；未执行数据生成或业务操作') from exc


@router.get('/label-analysis',response_class=HTMLResponse)
def page(request:Request):
    return templates.TemplateResponse(request,'label_analysis.html',{'page':'label_analysis','title':'标签综合分析'})


@router.get('/api/label-analysis/meta')
def meta():return invoke(label_analysis_service.meta)


@router.post('/api/label-analysis/summary')
def summary(q:AnalysisQuery):return invoke(label_analysis_service.summary,q)


@router.post('/api/label-analysis/details')
def details(q:AnalysisQuery):return invoke(label_analysis_service.details,q)


@router.post('/api/label-analysis/trends')
def trends(q:AnalysisQuery):return invoke(label_analysis_service.trends,q)


@router.post('/api/label-analysis/export')
def export(q:AnalysisQuery):
    content=invoke(label_analysis_service.export,q)
    name=quote(f'标签综合分析-{q.export_kind}-{q.data_date or "最新"}.csv')
    return Response(content,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{name}"})

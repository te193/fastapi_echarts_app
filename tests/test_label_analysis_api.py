from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.services.label_analysis_service import LabelAnalysisService
from test_label_analysis_service import Repo


def test_new_page_and_api_without_mutating_refresh():
    from app import label_analysis_routes as routes
    client=TestClient(app)
    with patch.object(routes,'label_analysis_service',LabelAnalysisService(Repo())):
        page=client.get('/label-analysis')
        assert page.status_code==200 and '标签综合分析' in page.text
        meta=client.get('/api/label-analysis/meta')
        assert meta.status_code==200 and len(meta.json()['metrics'])>100
        result=client.post('/api/label-analysis/summary',json={'data_date':'2026-10-11','period':7})
        assert result.status_code==200
        version=result.json()['version']
        payload={'data_date':'2026-10-11','period':7,'version':version}
        assert client.post('/api/label-analysis/details',json=payload).json()['total']==2
        export=client.post('/api/label-analysis/export',json=payload)
        assert export.status_code==200 and 'text/csv' in export.headers['content-type']
        assert client.post('/api/label-analysis/refresh').status_code in (404,405)


def test_validation_and_expired_snapshot():
    from app import label_analysis_routes as routes
    client=TestClient(app)
    with patch.object(routes,'label_analysis_service',LabelAnalysisService(Repo())):
        assert client.post('/api/label-analysis/summary',json={'period':5}).status_code==422
        assert client.post('/api/label-analysis/summary',json={'conditions':[{'kind':'metric','metric':'evil','op':'gt','value':0}]}).status_code==422
        assert client.post('/api/label-analysis/details',json={'version':'bad'}).status_code==409

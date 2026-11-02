import ast
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles

from app.services.page_usage import PAGE_REGISTRY, PageUsageService
from app import page_usage_routes as routes


SHANGHAI = timezone(timedelta(hours=8))


@pytest.fixture
def store(tmp_path):
    clock = [datetime(2026, 10, 26, 12, tzinfo=SHANGHAI)]
    service = PageUsageService(tmp_path / 'usage.sqlite3', now=lambda: clock[0])
    service.initialize()
    return service, clock


def record(service, page='replenishment', browser=None, event=None, environment='production'):
    return service.record_visit(page, browser or str(uuid4()), event or str(uuid4()), environment)


def row(summary, page='replenishment'):
    return next(item for item in summary['items'] if item['page_id'] == page)


def test_zero_visit_pages_remain_visible_and_are_not_called_unused_on_day_one(store):
    service, _ = store
    result = service.summary()
    assert len(result['items']) == len(PAGE_REGISTRY)
    assert all(item['views_30d'] == 0 for item in result['items'])
    assert result['observation_started_at'].startswith('2026-10-26')
    assert result['review_ready'] is False
    assert result['summary']['zero_pages'] == len(PAGE_REGISTRY)


def test_rolling_shanghai_calendar_windows_distinct_browsers_active_days_and_last_visit(store):
    service, clock = store
    browser = str(uuid4())
    record(service, browser=browser)  # Outside the eventual 30-day window.
    clock[0] = datetime(2026, 10, 28, 0, tzinfo=SHANGHAI)
    record(service, browser=browser)  # First included day.
    clock[0] = datetime(2026, 11, 19, 23, 59, tzinfo=SHANGHAI)
    record(service, browser=browser)  # Outside seven days.
    clock[0] = datetime(2026, 11, 20, 0, tzinfo=SHANGHAI)
    record(service, browser=browser)
    clock[0] = datetime(2026, 11, 26, 12, tzinfo=SHANGHAI)
    record(service)
    result = service.summary()
    item = row(result)
    assert (item['views_7d'], item['views_30d']) == (2, 4)
    assert (item['browsers_30d'], item['active_days_30d']) == (2, 4)
    assert item['last_seen'] == '2026-11-26 12:00:00'
    assert result['review_ready'] is True
    assert result['summary']['browsers_30d'] == 2
    assert result['items'][-1]['page_id'] == 'replenishment'


def test_deduplication_boundary_and_retry_idempotency(store):
    service, clock = store
    browser, event = str(uuid4()), str(uuid4())
    assert record(service, browser=browser, event=event)
    clock[0] += timedelta(seconds=29)
    assert not record(service, browser=browser)
    clock[0] += timedelta(seconds=1)
    assert record(service, browser=browser)
    clock[0] += timedelta(minutes=5)
    assert not record(service, browser=browser, event=event)
    assert row(service.summary())['views_30d'] == 2


def test_simultaneous_duplicate_requests_are_counted_once(store):
    service, _ = store
    browser = str(uuid4())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: record(service, browser=browser), range(8)))
    assert sum(results) == 1


def test_test_visits_are_excluded_by_default_and_deduplicated_separately(store):
    service, _ = store
    browser = str(uuid4())
    record(service, browser=browser, environment='test')
    assert row(service.summary())['views_30d'] == 0
    assert record(service, browser=browser)
    assert row(service.summary('test'))['views_30d'] == 1
    assert row(service.summary('all'))['views_30d'] == 2
    assert service.summary('all')['summary']['browsers_30d'] == 1


def test_restart_preserves_events_and_observation_start(store):
    service, clock = store
    record(service)
    clock[0] += timedelta(days=2)
    other = PageUsageService(service.path, now=lambda: clock[0])
    assert row(other.summary())['views_30d'] == 1
    assert other.summary()['observation_started_at'].startswith('2026-10-26')


def test_registry_covers_every_existing_html_route():
    root = Path(__file__).resolve().parents[1]
    paths = set()
    for filename in ('app/main.py', 'app/label_analysis_routes.py', 'app/page_usage_routes.py'):
        tree = ast.parse((root / filename).read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
                if any(k.arg == 'response_class' and ast.unparse(k.value) == 'HTMLResponse' for k in node.keywords):
                    paths.add(ast.literal_eval(node.args[0]))
    assert {page['path'] for page in PAGE_REGISTRY} == paths


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(routes, 'page_usage_service', store[0])
    app = FastAPI()
    app.include_router(routes.router)
    app.mount('/static', StaticFiles(directory=str(Path(__file__).resolve().parents[1] / 'app/static')), name='static')
    return TestClient(app, headers={'User-Agent': 'Mozilla/5.0'})


def payload(**changes):
    return {'page_id': 'replenishment', 'browser_id': str(uuid4()), 'visit_id': str(uuid4()),
            'environment': 'production', **changes}


def test_api_collects_only_explicit_page_events_and_renders_statistics(client):
    assert client.get('/api/page-usage').json()['summary']['views_30d'] == 0
    assert client.post('/api/page-usage/visits', json=payload()).json()['recorded'] is True
    assert client.get('/api/page-usage').json()['summary']['views_30d'] == 1
    assert client.get('/page-usage').status_code == 200
    assert client.get('/api/page-usage').json()['summary']['views_30d'] == 1


def test_usage_page_loads_without_unneeded_chart_or_grid_libraries(client):
    response = client.get('/page-usage')
    assert response.status_code == 200
    assert 'js/page_usage_stats.js' in response.text
    assert 'echarts.min.js' not in response.text
    assert 'ag-grid-community.min.js' not in response.text


@pytest.mark.parametrize('changes', [{'page_id': 'unknown'}, {'browser_id': 'bad'}, {'environment': 'bad'}])
def test_api_rejects_invalid_event_fields(client, changes):
    assert client.post('/api/page-usage/visits', json=payload(**changes)).status_code == 422


def test_cross_origin_events_are_rejected(client):
    assert client.post('/api/page-usage/visits', json=payload(),
                       headers={'Origin': 'https://unrelated.example'}).status_code == 403


def test_test_server_traffic_cannot_be_counted_as_production(store, monkeypatch):
    monkeypatch.setattr(routes, 'page_usage_service', store[0])
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, base_url='http://testserver:8001', headers={'User-Agent': 'Mozilla/5.0'}) as test_client:
        assert test_client.post('/api/page-usage/visits', json=payload()).status_code == 200
    assert store[0].summary()['summary']['views_30d'] == 0
    assert store[0].summary('test')['summary']['views_30d'] == 1


def test_storage_failure_is_reported_without_breaking_page_render(client, store, monkeypatch):
    def unavailable(*args):
        raise sqlite3.OperationalError('disk unavailable')
    monkeypatch.setattr(store[0], 'record_visit', unavailable)
    assert client.post('/api/page-usage/visits', json=payload()).status_code == 503
    assert client.get('/page-usage').status_code == 200


def test_all_registered_pages_render_the_shared_collector_and_matching_page_identity():
    from app.main import app
    with_client = TestClient(app)
    for page in PAGE_REGISTRY:
        response = with_client.get(page['path'])
        assert response.status_code == 200, page['path']
        assert f'data-page="{page["page_id"]}"' in response.text
        assert 'js/page_usage.js' in response.text

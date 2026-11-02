"""Small, independent page-visit store. Never reads or runs business ETL."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import threading
from uuid import UUID


SHANGHAI = timezone(timedelta(hours=8))
PAGE_REGISTRY = (
    {'page_id': 'dashboard', 'name': '结构概览', 'path': '/', 'group': '结构分析'},
    {'page_id': 'layers', 'name': '分层分布', 'path': '/layers', 'group': '结构分析'},
    {'page_id': 'matrix', 'name': '交叉矩阵', 'path': '/matrix', 'group': '结构分析'},
    {'page_id': 'detail', 'name': '产品明细', 'path': '/detail', 'group': '结构分析'},
    {'page_id': 'alerts', 'name': '异常预警', 'path': '/alerts', 'group': '经营诊断'},
    {'page_id': 'opportunities', 'name': '机会池', 'path': '/opportunities', 'group': '经营诊断'},
    {'page_id': 'label_analysis', 'name': '标签综合分析', 'path': '/label-analysis', 'group': '经营诊断'},
    {'page_id': 'label_hub', 'name': '标签看板', 'path': '/label-hub', 'group': '经营诊断'},
    {'page_id': 'country_label_hub', 'name': '国家标签看板', 'path': '/country-label-hub', 'group': '经营诊断'},
    {'page_id': 'price_review', 'name': '调价复盘', 'path': '/price-review', 'group': '经营诊断'},
    {'page_id': 'price_adjustments', 'name': '调价日期', 'path': '/price-adjustments', 'group': '经营诊断'},
    {'page_id': 'ad_budget', 'name': '广告预算', 'path': '/ad-budget', 'group': '经营诊断'},
    {'page_id': 'ad_performance', 'name': '广告效果分析', 'path': '/ad-performance', 'group': '经营诊断'},
    {'page_id': 'inventory_weekly', 'name': '库存周报', 'path': '/inventory-weekly', 'group': '库存补货'},
    {'page_id': 'replenishment', 'name': '补货计划', 'path': '/replenishment', 'group': '库存补货'},
    {'page_id': 'replenishment_tracking', 'name': '补货追踪', 'path': '/replenishment-tracking', 'group': '库存补货'},
    {'page_id': 'return_goods', 'name': '返场品', 'path': '/return-goods', 'group': '库存补货'},
    {'page_id': 'return_goods_strategy', 'name': '返场品运营策略', 'path': '/return-goods-strategy', 'group': '库存补货'},
    {'page_id': 'page_usage', 'name': '页面使用统计', 'path': '/page-usage', 'group': '使用情况'},
)
PAGE_IDS = frozenset(page['page_id'] for page in PAGE_REGISTRY)


class PageUsageService:
    def __init__(self, path=None, *, now=None):
        self.path = Path(path or os.getenv('DASHBOARD_USAGE_DB_PATH') or
                         Path(__file__).resolve().parents[2] / 'data' / 'page_usage.sqlite3')
        self.now = now or (lambda: datetime.now(SHANGHAI))
        self._initialized = False
        self._initialize_lock = threading.Lock()

    def _time(self):
        value = self.now()
        return value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value.astimezone(SHANGHAI)

    @staticmethod
    def _stamp(value):
        return value.replace(tzinfo=None).isoformat(sep=' ', timespec='microseconds')

    def _open(self):
        conn = sqlite3.connect(str(self.path), timeout=2)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._open()
            try:
                conn.execute('pragma journal_mode=WAL')
                with conn:
                    conn.execute('create table if not exists usage_metadata (key text primary key, value text not null)')
                    conn.execute('''create table if not exists page_visits (
                        visit_id text primary key, page_id text not null, browser_id text not null,
                        environment text not null check(environment in ('production','test')),
                        occurred_at text not null)''')
                    conn.execute('create index if not exists usage_dedup on page_visits(environment,page_id,browser_id,occurred_at desc)')
                    conn.execute('create index if not exists usage_window on page_visits(environment,occurred_at,page_id)')
                    conn.execute('insert or ignore into usage_metadata values (?,?)',
                                 ('observation_started_at', self._stamp(self._time())))
            finally:
                conn.close()
            self._initialized = True

    @contextmanager
    def _connection(self):
        self.initialize()
        conn = self._open()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def record_visit(self, page_id, browser_id, visit_id, environment='production'):
        if page_id not in PAGE_IDS or environment not in ('production', 'test'):
            raise ValueError('Unknown page or environment')
        browser_id, visit_id = str(UUID(str(browser_id))), str(UUID(str(visit_id)))
        with self._connection() as conn:
            # Serialize the read/check/write across threads and worker processes.
            conn.execute('begin immediate')
            now = self._time()
            if conn.execute('select 1 from page_visits where visit_id=?', (visit_id,)).fetchone():
                return False
            duplicate = conn.execute('''select 1 from page_visits
                where environment=? and page_id=? and browser_id=? and occurred_at>?
                limit 1''', (environment, page_id, browser_id, self._stamp(now - timedelta(seconds=30)))).fetchone()
            if duplicate:
                return False
            conn.execute('insert into page_visits values (?,?,?,?,?)',
                         (visit_id, page_id, browser_id, environment, self._stamp(now)))
            return True

    def summary(self, environment='production'):
        if environment not in ('production', 'test', 'all'):
            raise ValueError('Unknown environment')
        now = self._time()
        start7 = (now.date() - timedelta(days=6)).isoformat()
        start30 = (now.date() - timedelta(days=29)).isoformat()
        end = (now.date() + timedelta(days=1)).isoformat()
        scope, args = ('', []) if environment == 'all' else (' and environment=?', [environment])
        with self._connection() as conn:
            started = conn.execute("select value from usage_metadata where key='observation_started_at'").fetchone()[0]
            rows = conn.execute(f'''select page_id,
                sum(case when occurred_at>=? then 1 else 0 end) views_7d,
                sum(case when occurred_at>=? then 1 else 0 end) views_30d,
                count(distinct case when occurred_at>=? then browser_id end) browsers_30d,
                count(distinct case when occurred_at>=? then substr(occurred_at,1,10) end) active_days_30d,
                max(occurred_at) last_seen
                from page_visits where occurred_at<? {scope} group by page_id''',
                [start7, start30, start30, start30, end, *args]).fetchall()
            browsers = conn.execute(f'''select count(distinct browser_id) from page_visits
                where occurred_at>=? and occurred_at<? {scope}''', [start30, end, *args]).fetchone()[0]
        by_page = {item['page_id']: dict(item) for item in rows}
        items = []
        for page in PAGE_REGISTRY:
            counts = by_page.get(page['page_id'], {})
            items.append({**page, **{key: int(counts.get(key) or 0) for key in
                         ('views_7d', 'views_30d', 'browsers_30d', 'active_days_30d')},
                         'last_seen': counts['last_seen'].split('.')[0] if counts.get('last_seen') else None})
        items.sort(key=lambda item: (item['views_30d'], item['browsers_30d'], item['name']))
        started_time = datetime.fromisoformat(started).replace(tzinfo=SHANGHAI)
        return {
            'environment': environment, 'timezone': 'Asia/Shanghai',
            'observation_started_at': started.split('.')[0],
            'observed_days': max(1, (now.date() - started_time.date()).days + 1),
            'review_ready': now - started_time >= timedelta(days=30),
            'window_7d_start': start7, 'window_30d_start': start30,
            'window_end': now.date().isoformat(), 'items': items,
            'summary': {'pages': len(items), 'zero_pages': sum(item['views_30d'] == 0 for item in items),
                        'views_30d': sum(item['views_30d'] for item in items), 'browsers_30d': browsers},
        }


page_usage_service = PageUsageService()

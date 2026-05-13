# FastAPI ECharts 产品结构看板

跨境电商产品分层数据看板，基于 FastAPI + ECharts + MySQL。

## 目录

- `app/` — FastAPI 应用、模板、静态资源
- `etl/` — 每日数据更新脚本
- `config.py` — 数据库及看板配置
- `requirements.txt` — Python 依赖

## 配置

编辑 `config.py` 修改数据库连接信息：

```python
DASHBOARD_DB_HOST = "192.168.112.235"
DASHBOARD_DB_USER = "lanuser"
DASHBOARD_DB_PASSWORD = "123456"
...
```

## 运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## ETL 数据更新

```bash
python -m etl.dashboard_daily_update
```

## 页面

- `/` — 产品分层看板
- `/detail` — 产品数据明细
- `/matrix` — 日销毛利率矩阵
- `/layers` — 产品分层分布

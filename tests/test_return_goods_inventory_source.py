from datetime import date,timedelta
from etl.return_goods_strategy_update import attach_inventory_days,merge_days
from app.services.return_goods_strategy_rules import build_events,comparison_metrics


def test_inventory_survives_absent_business_rows_without_inventing_sales():
    start=date(2026,10,1)
    rows=[dict(day=start+timedelta(days=i),stock=s,inventory_only=1)
          for i,s in enumerate([0,0,0,5])]
    days=merge_days(attach_inventory_days(rows))
    assert build_events(days)[0]['return_date']==start+timedelta(days=3)
    m=comparison_metrics({r['day']:r for r in days},days[-1]['day'],1)
    assert m['stock_missing']==[]
    assert m['sales_missing']==[days[-1]['day']]
    assert days[-1]['qty'] is None and days[-1]['profit'] is None


def test_snapshot_overrides_country_stock_without_multiplying_shared_stock():
    day=date(2026,10,1)
    rows=[dict(day=day,country=c,stock=None,qty=2,revenue=20,profit=4,sessions=10,ad_spend=1)
          for c in ('德国','法国')]
    rows.append(dict(day=day,stock=17,inventory_only=1))
    attached=attach_inventory_days(rows)
    assert all(r['stock']==17 for r in attached)
    m=merge_days(attached)[0]
    assert m['stock']==17 and m['qty']==4 and m['profit']==8


def test_absent_inventory_snapshot_stays_missing_even_if_business_reports_stock():
    day=date(2026,10,1)
    m=merge_days(attach_inventory_days([dict(day=day,stock=99,qty=1,revenue=10,profit=2)]))[0]
    assert m['stock'] is None
    assert m['qty']==1

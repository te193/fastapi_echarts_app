from datetime import date, timedelta
from decimal import Decimal

import pytest
from return_goods_data import rules as r
from return_goods_data.enrichment import country_budget_usage, index_budget_snapshot, ad_for_country


START=date(2026,10,5)
DAYS=[START+timedelta(days=i) for i in range(7)]
STOCK={d:20 for d in DAYS}


def prepared(cost=5,orders=0,**changes):
    obj=dict(object_type='keyword',associated_msku_count=1,currency_code='EUR')
    stats=dict(mature=True,days=7,mature_start=DAYS[0],mature_end=DAYS[-1],
               report_days=[d.isoformat() for d in DAYS],clicks=20,cost=Decimal(str(cost)),orders=orders,sales=0)
    stats.update(changes)
    return [(obj,stats)]


def budget(week=10,month=310,**changes):
    row=dict(biz_date=DAYS[0],currency_code='EUR',weekly_ad_budget_original=week,
             monthly_ad_budget_original=month)
    row.update(changes)
    return row


@pytest.mark.parametrize('ratio',[0,'.49999','.50','.99999','1','1.5'])
def test_old_budget_ratio_does_not_control_current_zero_order_action(ratio):
    ad=dict(mapping_count=1,enabled=True,mature=True,days=1,clicks=20,orders=0,
            cost=10,sales=0,current_bid=1,budget_comparison=dict(verified=True,ratio=Decimal(str(ratio))))
    result=r.ad_candidate(ad,28,True)
    assert result['target']==Decimal('.90')
    assert result['action']=='bid_down' and result['status']=='pending'


@pytest.mark.parametrize('change',[{'clicks':19},{'mature':False},{'mapping_count':2},{'current_bid':None},
                                   {'zero_order_coverage_verified':False}, {'orders':None}])
def test_stoploss_cannot_bypass_evidence_and_amount(change):
    ad=dict(mapping_count=1,enabled=True,mature=True,days=1,clicks=20,orders=0,
            cost=10,sales=0,current_bid=1)
    ad.update(change)
    assert r.ad_candidate(ad,28,True)['target'] is None


def test_period_budget_prorated_and_lower_month_week_cap():
    usage=country_budget_usage(prepared(),budget(),STOCK)
    assert usage['verified'] and usage['spend']==5 and usage['budget']==10
    assert usage['ratio']==Decimal('.5') and usage['days']==7
    usage=country_budget_usage(prepared(),budget(week=100,month=31),STOCK)
    assert usage['budget']==7 and usage['ratio']==Decimal(5)/7


def test_shared_budget_once_country_spend_includes_ordered_objects():
    values=prepared(2)+prepared(3,orders=3,sales=30)
    usage=country_budget_usage(values,budget(),STOCK)
    assert usage['spend']==5 and usage['budget']==10 and usage['ratio']==Decimal('.5')
    result=r.ad_candidate(dict(values[0][1],mapping_count=1,current_bid=1,budget_comparison=usage),28,True)
    assert result['target']==Decimal('.90')


@pytest.mark.parametrize('changes',[{'currency_code':'USD'},{'biz_date':date(2026,10,11)},
                                    {'weekly_ad_budget_original':0},{'monthly_ad_budget_original':-1}])
def test_currency_future_and_nonpositive_budget_are_unknown(changes):
    usage=country_budget_usage(prepared(),budget(**changes),STOCK)
    assert not usage['verified'] and usage['ratio'] is None and usage['issues']


def test_multi_product_automatic_summary_and_missing_daily_report_not_country_zero():
    for field,value in [('associated_msku_count',2),('object_type','ad_group')]:
        rows=prepared();rows[0][0][field]=value
        assert not country_budget_usage(rows,budget(),STOCK)['verified']
    rows=prepared(report_days=[d.isoformat() for d in DAYS[:-1]])
    assert not country_budget_usage(rows,budget(),STOCK)['verified']
    stock=dict(STOCK);stock[DAYS[-1]]=None
    assert not country_budget_usage(prepared(),budget(),stock)['verified']


def test_budget_revision_not_backfilled_and_conflicts_remain_unknown():
    rows=[budget(biz_date=DAYS[0]),budget(week=20,biz_date=DAYS[3])]
    usage=country_budget_usage(prepared(),dict(history=rows),STOCK)
    assert usage['verified'] and usage['budget']==Decimal(3)*10/7+Decimal(4)*20/7
    rows.append(budget(week=50,biz_date=DAYS[3]))
    assert not country_budget_usage(prepared(),dict(history=rows),STOCK)['verified']


def test_cross_month_budget_does_not_borrow_future_month():
    start=date(2026,9,30);end=date(2026,10,1)
    rows=prepared(mature_start=start,mature_end=end,report_days=[start.isoformat(),end.isoformat()])
    history=[budget(week=None,month=300,biz_date=start),budget(week=None,month=310,biz_date=end)]
    usage=country_budget_usage(rows,dict(history=history),{start:20,end:20})
    assert usage['budget']==20
    assert not country_budget_usage(rows,dict(history=history[:1]),{start:20,end:20})['verified']


def test_budget_index_preserves_history_separates_countries_and_ignores_future():
    rows=[dict(budget(biz_date=DAYS[0]),seller_name_new='s',country='德国',seller_sku_adj='sku'),
          dict(budget(biz_date=DAYS[-1]),seller_name_new='s',country='德国',seller_sku_adj='sku'),
          dict(budget(biz_date=DAYS[0]),seller_name_new='s',country='法国',seller_sku_adj='sku')]
    future=dict(rows[0],biz_date=DAYS[-1]+timedelta(days=1),weekly_ad_budget_original=999)
    indexed=index_budget_snapshot(rows+[future],DAYS[-1])
    assert len(indexed[('s','de','sku')]['history'])==2
    assert indexed[('s','de','sku')]['weekly_ad_budget_original']==10
    assert len(indexed[('s','fr','sku')]['history'])==1


def test_pipeline_deduplicates_objects_and_does_not_use_budget_fallback(monkeypatch):
    from return_goods_data import enrichment as etl
    monkeypatch.setattr(etl,'aggregate_ad_days',lambda *a:prepared(5)[0][1])
    event=dict(state='sales_repair',as_of=DAYS[-1],return_date=DAYS[0],
               timeline=[{'day':d,'stock':20} for d in DAYS],
               comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5'))))
    obj=dict(prepared()[0][0],current_bid=1,snapshot_date=DAYS[-1],object_id='1',
             profile_id='p',campaign_id='c',ad_group_id='g')
    key=('s','de','sku');ads=dict(by_product={key:[obj,dict(obj)]},common_end=DAYS[-1],daily={})
    output=ad_for_country(event,key,ads,28,budget(),{})
    assert len(output)==1 and output[0]['target']==Decimal('.90')
    assert output[0]['zero_order_clicks']['click_band']=='20_39'
    unknown=ad_for_country(event,key,ads,28,{},{} )[0]
    assert unknown['target']==Decimal('.90') and unknown['action']=='bid_down'
    assert not any('CPA' in str(value) or '获客成本' in str(value) for value in unknown.values())


def test_clicks_below_twenty_hold_regardless_of_budget(monkeypatch):
    from return_goods_data import enrichment as etl
    monkeypatch.setattr(etl,'aggregate_ad_days',lambda rows,*a:rows[0])
    event=dict(state='sales_repair',as_of=DAYS[-1],return_date=DAYS[0],
               timeline=[{'day':d,'stock':20} for d in DAYS],
               comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5'))))
    key=('s','de','sku')
    objects=[dict(prepared()[0][0],current_bid=1,snapshot_date=DAYS[-1],object_id=str(i),
                  profile_id='p',campaign_id='c',ad_group_id='g') for i in (1,2,3)]
    stats=[prepared(50,clicks=19)[0][1],prepared(40,clicks=19)[0][1],prepared(5,orders=3,sales=100)[0][1]]
    ads=dict(by_product={key:objects},common_end=DAYS[-1],daily={('p','c','g',str(i+1)):[s] for i,s in enumerate(stats)})
    output=ad_for_country(event,key,ads,28,budget(week=1000,month=31000),{})
    assert sum(s['action']=='hold' for s in output)==2
    increased=next(s for s in output if s['object_id']=='3')
    assert increased['action']=='bid_up' and increased['status']=='pending'

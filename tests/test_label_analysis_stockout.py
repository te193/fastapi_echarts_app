import csv
import io
from datetime import date, timedelta

import pytest

from app.services.label_analysis_engine import aggregate, prepare_rows
from app.services.label_analysis_service import AnalysisQuery, LabelAnalysisService
from app.services.label_analysis_repository import label_window
from test_label_analysis_engine import sample
from test_label_analysis_service import Repo


def test_stockout_risk_counts_rates_recovery_and_unknown_inventory():
    start=date(2026,10,1); end=date(2026,10,10)
    rows=[sample(name, name) for name in ['continuous','restored','healthy','unknown']]
    days=[(start+timedelta(days=i)).isoformat() for i in range(10)]
    rows[0]['inventory']=dict.fromkeys(days,0)
    rows[1]['inventory']={d:0 if i<2 else 5 for i,d in enumerate(days)}
    rows[2]['inventory']=dict.fromkeys(days,5)
    rows[3]['inventory']={days[0]:-1}
    prepared=prepare_rows(rows,start,end)
    result=aggregate(prepared)
    assert result['stockout_product_count']['value']==2
    assert result['stockout_occurrence_rate']['value']==pytest.approx(2/3)
    assert result['stockout_days']['value']==12
    assert result['average_stockout_days']['value']==6
    assert result['zero_inventory_count']['value']==1
    assert result['current_zero_inventory_rate']['value']==pytest.approx(1/3)
    assert result['long_stockout_count']['value']==1
    assert result['recovered_stockout_count']['value']==1
    assert result['current_inventory_unknown_count']['value']==1
    assert result['stockout_day_rate']['value']==pytest.approx(12/30)
    assert result['inventory_observation_rate']['value']==pytest.approx(30/40)
    assert result['max_stockout_days']['value']==10  # Maximum, not group median.
    selected=['average_stockout_days','long_stockout_count','max_stockout_days']
    assert aggregate(prepared,selected)=={k:result[k] for k in selected}
    assert result['zero_inventory_count']['status']=='partial'


def test_unknown_inventory_is_not_no_stockout_and_zero_denominator_is_unknown():
    row=sample(); row['inventory']={}
    result=aggregate(prepare_rows([row],date(2026,10,1),date(2026,10,10)))
    assert result['zero_inventory_count']['value']==0
    assert result['zero_inventory_count']['valid_count']==0
    assert result['zero_inventory_count']['status']=='partial'
    assert result['stockout_days']['value'] is None
    assert result['average_stockout_days']['value'] is None
    assert result['current_zero_inventory_rate']['value'] is None


def test_longest_early_stockout_still_reports_open_boundary_after_recovery():
    row=sample()
    row['inventory']={'2026-10-09':0,'2026-10-10':0,'2026-10-11':5}
    prepared=prepare_rows([row],date(2026,10,9),date(2026,10,11))
    assert prepared[0]['inventory_boundary_lower_bound'] is False
    assert prepared[0]['inventory_max_boundary_lower_bound'] is True
    assert aggregate(prepared)['max_stockout_days']['status']=='partial'


@pytest.mark.parametrize('period',[60,180])
def test_extended_periods_keep_same_cohort_and_stockout_export(period):
    service=LabelAnalysisService(Repo())
    query=AnalysisQuery(data_date='2026-10-11',period=period,columns=['stockout_product_count','stockout_days','zero_inventory_count','stockout_day_rate'])
    summary=service.summary(query)
    assert summary['current']['object_count']['value']==2
    assert summary['current']['stockout_product_count']['value']==2
    assert summary['current']['stockout_days']['value']==4
    assert summary['current']['stockout_day_rate']['value']==pytest.approx(4/6)
    assert summary['current']['inventory_observation_rate']['value']==pytest.approx(6/(period*2))
    rows=list(csv.reader(io.StringIO(service.export(query.model_copy(update={'version':summary['version'],'export_kind':'summary'})).lstrip('\ufeff'))))
    assert [int(row[8]) for row in rows[1:]]==[2,2]
    assert service.details(query.model_copy(update={'version':summary['version']}))['total']==2


def test_extended_period_labels_use_published_30_day_roles():
    assert label_window(30)==30
    assert label_window(90)==90
    assert label_window(60)==30
    assert label_window(180)==30


def test_long_period_traffic_before_source_boundary_stays_unknown():
    from app.services.label_analysis_traffic import attach_traffic,TrafficRows
    from app.services.label_analysis_engine import row_business_record
    row=sample();row['daily']={}
    attach_traffic([row],TrafficRows([], '2026-01-01'),'business_unit')
    assert row_business_record(row,'2025-12-31')['sessions_total'] is None
    assert row_business_record(row,'2026-01-01')['sessions_total']==0
    result=aggregate(prepare_rows([row],date(2025,12,31),date(2026,1,1)))
    assert result['sessions_total']['status']=='partial'
    assert result['sessions_total']['expected_object_days']==2
    assert result['sessions_total']['zero_filled_object_days']==1

from datetime import date
from etl.return_goods_strategy_update import settings_cutoff, expand_auto_targets


def test_latest_settings_do_not_stop_at_yesterdays_sales():
    assert settings_cutoff(date(2026, 10, 8), today=date(2026, 10, 9)) == date(2026, 10, 9)


def test_historical_replay_does_not_borrow_future_settings():
    assert settings_cutoff(date(2026, 10, 7), date(2026, 10, 7), date(2026, 10, 9)) == date(2026, 10, 7)


def test_target_sync_date_is_separate_from_group_snapshot():
    group=dict(profile_id='1', campaign_id='2', ad_group_id='3', object_type='ad_group', snapshot_date=date(2026, 10, 8))
    target=dict(profile_id='1', campaign_id='2', ad_group_id='3', target_id='4', expression='[{"type":"queryHighRelMatches"}]', bid='.08', state='enabled', create_time='2026-10-09 08:07:08')
    result=expand_auto_targets([group], [target])[0]
    assert result['object_text']=='紧密匹配'
    assert result['snapshot_date']==date(2026, 10, 8)
    assert result['target_source_date']=='2026-10-09 08:07:08'


def test_dated_page_query_excludes_batches_with_future_settings():
    from unittest.mock import MagicMock
    from app.services.return_goods_strategy_data import ReturnGoodsStrategyDataService
    conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect=[None,None];cur.fetchall.return_value=[]
    ReturnGoodsStrategyDataService()._batch(conn,'2026-10-08')
    query,params=cur.execute.call_args_list[0].args
    assert "json_extract(quality_json,'$.settings_date')" in query
    assert params==[date(2026,10,8),'2026-10-08']

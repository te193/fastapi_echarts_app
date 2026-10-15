from app.services.return_goods_strategy_data import filter_payload


def item(key,result,state,stock=None,reasons=(),age=20):
    return dict(event_id=key,msku=key,seller_name_new='s',country_category='欧洲站',
                exit_status='tracking',age=age,state=state,ad_result=result,current_stock=stock,
                ad_diagnostic_reasons=list(reasons),action_types=[],priority=0,ready_count=0,pending_count=0)


def test_limits_separate_zero_low_and_missing_stock_and_filter_exact_members():
    rows=[item('zero','limited','stock_interrupted',0),item('one','limited','stock_interrupted',1),
          item('missing','limited','stock_missing'),item('observing','limited','stock_missing',age=7)]
    payload=filter_payload(rows,{})
    groups=payload['ad_reason_groups']
    assert len(groups)==3 and sum(g['count'] for g in groups)==3
    for group in groups:
        selected=filter_payload(rows,{},focus=group['key'],all_rows=True)
        assert selected['total']==group['count']==len(group['products'])
        assert {r['event_id'] for r in selected['items']}=={p['event_id'] for p in group['products']}


def test_unknown_multiple_reasons_count_product_once_per_reason_and_follow_store_filter():
    rows=[item('a','unknown','poor',5,['缺少报表','缺少竞价','缺少报表']),
          item('b','unknown','poor',5,['缺少报表'])]
    rows[1]['seller_name_new']='other'
    groups=filter_payload(rows,{})['ad_reason_groups']
    assert {g['reason']:g['count'] for g in groups}=={'缺少报表':2,'缺少竞价':1}
    filtered=filter_payload(rows,{},seller_name_new='s')['ad_reason_groups']
    assert all(g['count']==1 for g in filtered)

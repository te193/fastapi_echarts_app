from app.services.return_goods_strategy_data import display_ordered_suggestions
from etl.return_goods_strategy_update import ad_for_country


def test_existing_country_bid_survives_other_country_without_ads_and_excludes_outside_seven():
    row=dict(state='sales_repair',countries=[
        dict(country='德国',suggestions=[dict(kind='ad',action='bid_up',label='提高竞价',status='pending',reason='效率满足',target=.55)]),
        dict(country='法国',suggestions=[dict(kind='ad',action='check',label='核查',status='pending',reason='未找到可核实的已有广告对象；检查是否原本无广告、暂停或映射缺失')]),
        dict(country='加拿大',suggestions=[dict(kind='price',action='price_down',label='降价',status='pending',reason='销量不足',target=10)])])
    result=display_ordered_suggestions(row)
    assert [c['country'] for c in result['countries']]==['德国','法国']
    assert result['countries'][0]['suggestions'][0]['target']==.55
    assert result['countries'][1]['suggestions'][0]['action']=='start_ad'
    assert result['ad_result']=='adjust'
    assert set(result['candidate_actions'])=={'bid_up','start_ad'}
    assert result['ad_diagnostic_reasons']==[]


def test_missing_ads_is_open_suggestion_without_invented_bid_or_budget():
    suggestions=ad_for_country(dict(state='sales_repair',recent=dict(daily=.5)),('s','de','a'),{},30,{}, {})
    assert suggestions[0]['action']=='start_ad'
    assert suggestions[0]['status']=='pending'
    assert suggestions[0].get('target') is None


def test_starting_ads_defers_only_same_country_price():
    row=dict(state='poor',countries=[
        dict(country='荷兰',suggestions=[dict(kind='ad',action='check',label='核查',status='pending',reason='未找到可核实的已有广告对象'),dict(kind='price',action='price_down',label='降价',status='pending',reason='销量不足')]),
        dict(country='美国',suggestions=[dict(kind='ad',action='hold',label='保持',status='hold',reason='正常'),dict(kind='price',action='price_up',label='提价',status='pending',reason='利润修复')])])
    result=display_ordered_suggestions(row)
    assert result['countries'][0]['suggestions'][1]['deferred']
    assert not result['countries'][1]['suggestions'][1].get('deferred')
    assert result['price_review_actions']==['price_up']

"""Versioned metric contracts shared by API, UI, filters and exports."""
from dataclasses import asdict, dataclass

VERSION = 'label-analysis-20261014-v6-stockout-risk'


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    group: str
    unit: str = 'number'
    aggregation: str = 'sum'
    grain: str = 'object'
    formula: str = '有效明细合计；缺失值不补零'
    source: str = '经营日事实'
    available: bool = True
    trend: bool = False
    share: bool = True
    numerator: str = ''
    denominator: str = ''
    multiplier: float = 1


METRICS = {}


def add(id, label, group, **kwargs):
    METRICS[id] = Metric(id, label, group, **kwargs)


for key, label in [('object_count','商品对象数'),('unique_msku_count','去重MSKU数'),('store_count','店铺数'),('country_count','国家数'),('pool_count','可识别库存池数'),('labeled_count','有标签商品数'),('sales_valid_count','有经营数据商品数'),('inventory_valid_count','有当日库存商品数'),('selling_count','有销量商品数'),('zero_sales_count','已观察零销量商品数'),('profitable_count','盈利商品数'),('loss_count','亏损商品数'),('traffic_count','有流量商品数'),('ad_product_count','有投放商品数'),('return_product_count','有退货商品数'),('zero_inventory_count','当前零库存商品数'),('stockout_product_count','周期出现缺货商品数'),('inventory_observed_count','有库存观察商品数'),('unlabeled_count','无标签商品数'),('missing_sales_count','无经营数据商品数'),('multiple_label_count','多标签命中商品数')]:
    add(key,label,'规模',aggregation='count',source='当前对象集合及有效记录')

DAILY_FIELDS = {}
for group, entries in {
    '经营':[('sales_qty','销量','number'),('sales_amount','销售额','money'),('sales_amount_ex_tax','未税销售额','money')],
    '利润':[('order_gross_profit','订单毛利润','money'),('settlement_gross_profit','结算毛利润','money'),('net_amount','来源净额','money')],
    '流量':[('sessions_total','总会话数','number')],
    '广告':[('ad_spend','广告花费','money'),('ad_sales','广告归因销售额','money'),('ad_orders','广告订单数','number'),('ad_clicks','广告点击','number'),('ad_impressions','广告曝光','number')],
    '售后':[('return_count','退货数量','number'),('return_amount','退货金额','money')],
}.items():
    for key,label,unit in entries:
        DAILY_FIELDS[key]=label
        add(key,label,group,unit=unit,trend=True,share=key not in ('order_gross_profit','settlement_gross_profit','net_amount'),source='产品表现.sessions_total' if key=='sessions_total' else '经营日事实',formula='周期日记录汇总；缺行按0，已有记录的空字段不补零')
SNAPSHOT_DAILY_FIELDS=tuple(DAILY_FIELDS)
PRODUCT_TRAFFIC_FIELDS={
    'order_count':('商品订单量','order_items'),
    'sessions_browser':('浏览器会话数','sessions'),
    'sessions_mobile':('移动端会话数','sessions_mobile'),
    'page_views':('总浏览量（PV）','page_views_total'),
    'page_views_browser':('浏览器浏览量','page_views'),
    'page_views_mobile':('移动端浏览量','page_views_mobile'),
}
TRAFFIC_DAILY_FIELDS=('sessions_total','traffic_sales_qty',*PRODUCT_TRAFFIC_FIELDS)
DAILY_FIELDS['traffic_sales_qty']='产品表现销量'
add('traffic_sales_qty','产品表现销量','流量',trend=True,source='产品表现.volume',formula='产品表现同一对象日的销量；用于销量CVR分子，不替换经营快照销量')
for key,(label,column) in PRODUCT_TRAFFIC_FIELDS.items():
    DAILY_FIELDS[key]=label
    add(key,label,'流量',trend=True,source=f'产品表现.{column}',formula='产品表现同一对象日汇总；缺行按0；来源不可用或字段空值不补零')
for key,label in [('positive_profit','正毛利润'),('loss_amount','亏损金额（绝对值）')]:
    add(key,label,'利润',unit='money',source='商品周期订单毛利润')

INVENTORY_FIELDS = {
    'ending_inventory_qty':('FBA可售库存','number'), 'inventory_total':('FBA总库存','number'),
    'inventory_cost':('FBA总库存成本金额','money'), 'available_inventory':('FBA可用库存','number'),
    'sellable_inventory_cost':('FBA可售库存成本金额','money'),
    'available_inventory_cost':('FBA可用库存成本金额','money'),
    'unsellable_inventory':('FBA不可售库存','number'), 'reserved_inventory':('待发货库存','number'),
    'transfer_inventory':('待调仓库存','number'), 'processing_inventory':('调仓中库存','number'),
    'inbound_inventory':('入库中库存','number'), 'in_transit':('实际在途库存','number'),
    'in_transit_cost':('实际在途成本金额','money'),
}
for key,(label,unit) in INVENTORY_FIELDS.items():
    add(key,label,'库存',unit=unit,grain='pool',source='截止日库存池日快照',formula='同一已识别库存池只计算一次；冲突不取任意最大值',trend=key=='ending_inventory_qty')
METRICS['sellable_inventory_cost']=Metric('sellable_inventory_cost','FBA可售库存成本金额','库存',unit='money',grain='pool',source='同日库存处理表.afn_fulfillable_quantity_price',formula='按库存池去重；同日可售数量与总成本须对齐库存日快照；缺失、冲突不计算，不用总库存成本替代')

REPL_FIELDS = {
    'replenishment_daily_sales':('日销','daily_avg_sales','number','sum'),
    'support_inventory_qty':('补货支持库存','support_inventory_qty','number','sum'),
    'support_days':('补货库存支持天数','inventory_support_days','days','median'),
    'arrival_support_days':('到货时库存支持天数','arrival_inventory_support_days','days','median'),
    'purchase_lead_days':('采购提前期','effective_purchase_lead_days','days','median'),
    'lead_stockout_days':('到货前预计缺货天数','lead_time_stockout_days','days','median'),
    'lead_shortfall_qty':('到货前预计缺口数量','lead_time_lost_sales_qty','number','sum'),
    'local_inventory':('本地可用库存','sc_quantity_local_valid','number','sum'),
    'purchase_in_transit':('采购在途','sc_quantity_purchase_shipping','number','sum'),
    'purchase_plan_qty':('采购计划数量','sc_quantity_purchase_plan','number','sum'),
    'local_qc_qty':('本地质检库存','sc_quantity_local_qc','number','sum'),
}
for key,(label,field,unit,agg) in REPL_FIELDS.items():
    add(key,label,'覆盖与补货',unit=unit,aggregation=agg,grain='pool' if key in ('local_inventory','purchase_in_transit','purchase_plan_qty','local_qc_qty') else 'demand',share=agg=='sum',source='补货同日已发布结果.'+field,formula='复用完整补货计算结果，按补货需求对象去重；日期不一致不混算')
add('fba_coverage_days','FBA可售天数','覆盖与补货',unit='days',aggregation='median',grain='demand',share=False,source='库存池及补货日销',formula='完整需求对象的FBA可售库存 / 补货日销；群体展示中位数及P25/P75')
add('coverage_demand_daily_sales','覆盖计算日销（完整需求）','覆盖与补货',grain='demand',source='补货同日已发布结果与完整需求映射',formula='覆盖天数实际使用的完整需求日销；含产品组与共享库存池需求；不等同于明细继承日销')
add('small_category_rank','截止日小类排名（单国家）','流量',aggregation='median',share=False,source='经营日事实.ranking',formula='只取截止日单国家的有效小类排名；同对象多条排名冲突、非正或缺失时未知；跨国家不合并排名；群体展示中位数')
add('period_daily_sales','周期平均日销量','经营',source='周期实际销量',formula='周期实际销量 / 所选自然天数')
for key,label in [('sales_days','有销售对象日'),('traffic_days','有流量对象日'),('stockout_days','缺货对象日'),('instock_days','有货对象日'),('unknown_inventory_days','未知库存对象日'),('inventory_observed_days','有效库存对象日'),('expected_inventory_days','应观察库存对象日'),('stockout_events','已确认缺货次数')]:
    add(key,label,'缺货',source='逐对象自然日日历',formula='日历逐日判定；缺失与异常库存为未知')
for key,label in [('current_stockout_days','当前连续缺货天数'),('max_stockout_days','最长连续缺货天数')]:
    add(key,label,'缺货',unit='days',aggregation='median',share=False,source='连续库存日历',formula='不跨缺失日连接；边界未确认时是已观察下限')
for key,label,formula in [
    ('stockout_product_count','周期断货商品数','周期内至少一天FBA可售库存为0的商品数；整期零库存也计入'),
    ('zero_inventory_count','当前断货商品数','截止日FBA可售库存为0的商品数；库存不明不计作断货'),
    ('long_stockout_count','连续断货≥7天商品数','截止日向前至少连续7天确认FBA可售库存为0的商品数；不跨缺失日连接'),
    ('recovered_stockout_count','当前已恢复有货商品数','周期内曾断货且截止日确认FBA可售库存大于0的商品数'),
    ('current_inventory_unknown_count','当前库存不明商品数','截止日缺少有效库存记录、负库存或映射冲突的商品数'),
]:
    add(key,label,'缺货',aggregation='count',formula=formula,source='商品FBA可售库存日快照')
add('stockout_days','累计断货天数','缺货',unit='days',formula='把各商品在周期内确认FBA可售库存为0的天数相加；2个商品各断货3天，累计6天',source='商品FBA可售库存日快照')
add('max_stockout_days','周期最长连续断货天数','缺货',unit='days',aggregation='max',share=False,formula='先取每个商品在周期内最长连续断货天数，再取群体最大值；不跨缺失日连接，边界不完整时为已确认下限',source='连续库存日历')
for key,label in [('stockout_days','库存池缺货观察日'),('instock_days','库存池有货观察日'),('inventory_observed_days','库存池有效观察日'),('expected_inventory_days','库存池应观察日')]:
    add('pool_'+key,label,'缺货',grain='pool',source='库存日历与库存池映射',formula='当前确认库存映射按池去重；不能解释为全群体自然日')
add('avg_inventory_qty','周期日均FBA可售库存','库存',grain='pool',source='完整库存日历',formula='逐日库存池去重后求自然日平均；日历缺失不计算')
add('avg_inventory_cost','周期日均库存成本','库存',unit='money',grain='pool',source='完整成本日历',formula='完整自然日库存成本平均')
add('zero_sales_inventory_cost','完整周期零销量库存金额','库存',unit='money',grain='pool',source='经营日历（缺行按0）与库存成本',formula='经营日历缺行按0后，周期销量为零且现有记录字段完整的库存池成本')

RATIOS = [
 ('label_coverage_rate','标签覆盖率','规模','labeled_count','object_count'),
 ('sales_coverage_rate','经营数据覆盖率','规模','sales_valid_count','object_count'),
 ('inventory_coverage_rate','当前库存覆盖率','规模','inventory_valid_count','object_count'),
 ('unlabeled_rate','无标签占比','规模','unlabeled_count','object_count'),
 ('missing_sales_rate','无经营数据占比','规模','missing_sales_count','object_count'),
 ('multiple_label_rate','多标签重叠率','规模','multiple_label_count','object_count'),
 ('selling_rate','动销商品率','经营','selling_count','sales_valid_count'),
 ('zero_sales_rate','已观察零销量商品率','经营','zero_sales_count','sales_valid_count'),
 ('order_gross_margin','订单毛利率','利润','order_gross_profit','sales_amount'),
 ('settlement_gross_margin','结算毛利率','利润','settlement_gross_profit','sales_amount'),
 ('profitable_rate','盈利商品率','利润','profitable_count','profit_valid_count'),
 ('loss_rate','亏损商品率','利润','loss_count','profit_valid_count'),
 ('current_zero_inventory_rate','当前零库存率','缺货','zero_inventory_count','inventory_valid_count'),
 ('stockout_occurrence_rate','周期缺货发生率','缺货','stockout_product_count','inventory_observed_count'),
 ('stockout_day_rate','缺货天数率','缺货','stockout_days','inventory_observed_days'),
 ('inventory_observation_rate','库存观察覆盖率','缺货','inventory_observed_days','expected_inventory_days'),
 ('traffic_coverage_rate','有流量商品率','流量','traffic_count','traffic_valid_count'),
 ('order_conversion','订单转化率（CVR）','流量','order_count','sessions_total'),
 ('product_conversion','销量转化率','流量','traffic_sales_qty','sessions_total'),
 ('ad_coverage_rate','投放覆盖率','广告','ad_product_count','ads_valid_count'),
 ('ctr','广告点击率CTR','广告','ad_clicks','ad_impressions'),
 ('acos','ACOS','广告','ad_spend','ad_sales'),('tacos','TACOS','广告','ad_spend','sales_amount'),
 ('ad_cvr','广告订单转化率','广告','ad_orders','ad_clicks'),
 ('ad_sales_share','广告归因销售额/销售额','广告','ad_sales','sales_amount'),
 ('return_qty_ratio','同期退货数量/销量比','售后','return_count','sales_qty'),
 ('return_amount_ratio','同期退货金额/销售额比','售后','return_amount','sales_amount'),
 ('return_product_rate','发生退货商品率','售后','return_product_count','return_valid_count'),
 ('zero_order_spend_share','有点击零广告订单花费占比','广告','zero_order_spend','ad_spend'),
 ('unsellable_rate','不可售库存占比','库存','unsellable_inventory','inventory_total'),
]
for key,label,group,num,den in RATIOS:
    add(key,label,group,unit='percent',aggregation='ratio',share=False,numerator=num,denominator=den,formula=f'{num} / {den}，同一有效样本重算；分母为0时不计算',source='对应分子与分母')
for key,label,num,den,formula,unit in [
    ('current_zero_inventory_rate','当前断货率','zero_inventory_count','inventory_valid_count','当前断货商品数 / 截止日库存有效商品数；库存不明商品不计入分母','percent'),
    ('stockout_occurrence_rate','周期断货发生率','stockout_product_count','inventory_observed_count','周期断货商品数 / 周期内至少一天库存有效的商品数','percent'),
    ('stockout_day_rate','缺货天数率','stockout_days','inventory_observed_days','累计断货天数 / 各商品确认有货或断货的天数合计；库存不明天数不计入分母','percent'),
    ('inventory_observation_rate','库存记录完整率','inventory_observed_days','expected_inventory_days','各商品库存有效天数合计 / 各商品应统计天数合计','percent'),
    ('average_stockout_days','断货商品平均断货天数','stockout_days','stockout_product_count','累计断货天数 / 周期断货商品数；仅对曾断货商品计算，没有断货商品时不计算','days'),
]:
    add(key,label,'缺货',unit=unit,aggregation='ratio',share=False,numerator=num,denominator=den,formula=formula,source='商品FBA可售库存日快照')
for key,label,group,num,den in [
 ('average_price','平均成交单价','经营','sales_amount','sales_qty'),
 ('unit_profit','件均订单毛利','利润','order_gross_profit','sales_qty'),
 ('units_per_session','每次会话销售件数','流量','sales_qty','sessions_total'),
 ('cpc','广告点击成本CPC','广告','ad_spend','ad_clicks'),
 ('roas','广告投入产出ROAS','广告','ad_sales','ad_spend'),
]:
    add(key,label,group,unit='money' if key in ('average_price','unit_profit','cpc') else 'number',aggregation='ratio',share=False,numerator=num,denominator=den,formula=f'{num} / {den}；相同有效样本',source='对应分子与分母')
for key,label,num in [('sales_per_1000_sessions','每千次会话销售额','sales_amount'),('profit_per_1000_sessions','每千次会话订单毛利润','order_gross_profit')]:
    add(key,label,'流量',unit='money',aggregation='ratio',share=False,numerator=num,denominator='sessions_total',multiplier=1000,formula='同一有效对象日分子合计 / 会话合计 × 1000',source='经营日事实共同有效样本')
add('zero_order_spend','有点击零广告订单花费','广告',unit='money',source='当前周期商品广告事实',formula='广告点击>0且广告订单=0的商品广告花费；不代表成熟归因损失')
add('top10_sales_share','Top10商品销售额占比','经营',unit='percent',aggregation='custom',share=False,formula='销售额最高10个对象的销售额 / 正销售额合计')

HISTORY_SOURCE='内网历史角色快照；源为dws_datasync.dws_product_sales_role_history'
add('history_valid_segments','历史有效周期数','历史销售角色',source=HISTORY_SOURCE,formula='截至页面日期已完成且源vote_eligible=1的30天段数；历史窗口不随经营周期改变')
add('history_excluded_segments','历史未计入周期数','历史销售角色',source=HISTORY_SOURCE,formula='截至页面日期已开始但未参与主导角色统计的周期数，含未完成、缺失、整段断货等；不当作问题产品')
for role,name in [('明星','star'),('潜力','potential'),('瘦狗','dog'),('问题','problem')]:
    add(f'history_{name}_count',f'历史{role}次数','历史销售角色',source=HISTORY_SOURCE,formula=f'历史有效完整30天段中{role}角色出现次数；群体按商品周期段合计')
    add(f'history_{name}_share',f'历史{role}占比','历史销售角色',unit='percent',aggregation='ratio',share=False,numerator=f'history_{name}_count',denominator='history_valid_segments',source=HISTORY_SOURCE,formula=f'历史{role}次数合计 / 历史有效周期数合计；不是商品占比，零有效周期时不计算')

PENDING = {
 '经营':[('average_order_value','客单价')],
 '利润':[('sales_cost','销售成本'),('allocated_fees','可归属商品费用'),('fee_rate','费用率')],
 '库存':[('quantity_turnover','库存数量周转次数（待同库存范围销量）'),('quantity_turnover_days','库存数量周转天数'),('inventory_turnover','成本口径库存周转率'),('turnover_days','成本口径库存周转天数'),('inventory_age','库龄数量与成本分布')],
 '流量':[('organic_sessions','自然流量'),('zero_traffic_rate','经来源完整性核验的零流量率')],
 '售后':[('refund_orders','退款订单数'),('cohort_return_rate','订单批次退货率'),('rating','评分'),('review_count','评价数'),('low_rating_rate','低评分商品率')],
 '标签变更（待接入）':[('member_entries','标签进入对象数'),('member_exits','标签退出对象数'),('membership_contribution','标签成员变化贡献'),('operating_stockout_rate','历史经营资格缺货率')],
}
for group, entries in PENDING.items():
    for key,label in entries:
        add(key,label,group,available=False,share=False,aggregation='pending',source='待接入并核验来源',formula='需要独立可靠来源，禁止由不等价字段估算')


def row_filterable(m):
    if not m.available or m.aggregation in ('count','custom'):return False
    return m.aggregation!='ratio' or (m.numerator in METRICS and m.denominator in METRICS and METRICS[m.numerator].aggregation!='count' and METRICS[m.denominator].aggregation!='count')


def catalog():
    return [{**asdict(m),'filterable':row_filterable(m)} for m in METRICS.values()]

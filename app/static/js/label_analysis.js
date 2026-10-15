(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let meta, metrics = {}, payload, detailPayload, trendPayload, epoch = 0, detailsRequest = 0, controller, group = '经营', custom = [], total = 0;
  const defaults = {period:30,view:'business_unit',conditions:[],overview_parent:1,inventory_tab:'coverage',topic_tab:'trend',open_sections:[],page:1,page_size:20,sort:'sales_amount',descending:true,country_categories:[],countries:[],stores:[],keyword:'',matrix_parents:[]};
  let gridApi, gridGroup='', gridRendering=false, drawerRequest=0, recoveringVersion=false; const gridStates={};
  let trendChart, trendRequest=0, trendLoading=false;
  let drawerProduct,drawerContext,drawerTab='overview';
  let catalogDraft=[],catalogGroup='';
  const drawerSections=[
    {id:'overview',label:'概览'},
    {id:'sales',label:'经营利润',groups:['经营','利润'],primary:['sales_qty','sales_amount','order_gross_profit','order_gross_margin','average_price','unit_profit']},
    {id:'stock',label:'库存补货',groups:['库存','覆盖与补货','缺货'],primary:['ending_inventory_qty','sellable_inventory_cost','fba_coverage_days','replenishment_daily_sales','support_days','stockout_days']},
    {id:'traffic',label:'流量广告',groups:['流量','广告'],primary:['sessions_total','page_views','order_count','order_conversion','product_conversion','sessions_mobile']},
    {id:'returns',label:'退货情况',groups:['售后'],primary:['return_count','return_amount','return_qty_ratio','return_amount_ratio']},
    {id:'role_history',label:'历史销售角色',groups:['历史销售角色'],primary:['history_valid_segments','history_excluded_segments','history_star_count','history_star_share','history_potential_count','history_potential_share','history_dog_count','history_dog_share','history_problem_count','history_problem_share']},
    {id:'evidence',label:'标签依据'}
  ];
  let state = {...defaults};
  try { const q = new URLSearchParams(location.search).get('q'); if(q) state = {...defaults,...JSON.parse(q)}; } catch (_) { /* Invalid links start from an empty scope. */ }
  try { custom = JSON.parse(localStorage.getItem('label-analysis-columns-v1') || '[]'); } catch (_) {}
  const omittedColumns=new Set(['coverage_demand_daily_sales','small_category_rank','sales_days','traffic_days']);
  const capitalColumns=['fba_coverage_days','replenishment_daily_sales','ending_inventory_qty','sellable_inventory_cost','inventory_cost','sales_qty','sales_amount','order_gross_profit','sessions_total'];
  const trafficColumns=['sessions_total','page_views','order_count','order_conversion','product_conversion','sessions_browser','sessions_mobile','page_views_browser','page_views_mobile'];
  const stockoutColumns=['stockout_product_count','stockout_occurrence_rate','stockout_days','stockout_day_rate','average_stockout_days','zero_inventory_count','current_zero_inventory_rate','long_stockout_count','recovered_stockout_count','max_stockout_days','inventory_observation_rate'];
  const coverageNames={no_performance:'周期内无表现数据',missing_daily_sales:'有表现但缺日销',zero_daily_sales:'日销为0',data_pending:'数据待核'};
  if(new URLSearchParams(location.search).get('focus')==='capital'&&!new URLSearchParams(location.search).has('q'))Object.assign(state,{conditions:[{kind:'metric',metric:'fba_coverage_days',op:'gt',value:180,preset:'capital'}],sort:'inventory_cost',column_group:'库存资金专项',open_sections:['laCapital']});
  group=state.column_group||group;
  if(group==='历史')group='历史销售角色';
  if(group==='退货情况')group='售后';
  const groupLabel=value=>value==='售后'?'退货情况':value==='自定义'?'自选指标':value;
  const metricWording={
    sales_days:{label:'累计有销量商品天数',formula:'把每个商品销量大于0的天数相加；2个商品各有销量3天，累计为6天。'},
    traffic_days:{label:'累计有流量商品天数',formula:'把每个商品总会话数大于0的天数相加。'},
    instock_days:{label:'累计有货商品天数',formula:'把每个商品FBA可售库存大于0的天数相加。'},
    unknown_inventory_days:{label:'库存不明商品天数',formula:'没有可靠库存记录或库存异常，无法判断有货还是缺货的商品天数；这些天不当作缺货。'},
    inventory_observed_days:{label:'库存已确认商品天数',formula:'累计有货商品天数＋累计缺货商品天数；不包含库存不明的天数。'},
    expected_inventory_days:{label:'应统计商品总天数',formula:'每个商品应统计的天数相加；例如250个商品统计30天，应统计7500个商品天数。'},
    pool_stockout_days:{label:'去重库存累计缺货天数',formula:'同一份共享库存只算一次，再累计其可售库存为0的天数。'},
    pool_instock_days:{label:'去重库存累计有货天数',formula:'同一份共享库存只算一次，再累计其可售库存大于0的天数。'},
    pool_inventory_observed_days:{label:'去重库存已确认天数',formula:'同一份共享库存只算一次，累计能够确认有货或缺货的天数。'},
    pool_expected_inventory_days:{label:'去重库存应统计天数',formula:'同一份共享库存只算一次，把每份库存应统计的天数相加。'}
  };
  const exportMetricNames={};
  function status(message,error=false) { $('laStatus').textContent=message; $('laStatus').className='la-status'+(error?' error':''); const notice=$('laLoadNotice');notice.textContent=message;notice.classList.toggle('error',error);if(error)notice.hidden=false; }
  function pendingModules(message,error=false) {
    if(payload)return;
    for(const id of ['laCapitalBands','laTagCategories','laCapitalStructure','laCapitalRanks','laTagTable','laCards','laMetricTable','laCoverage','laStockout','laStores','laMatrix','laDetailTable'])$(id).innerHTML='<p class="la-empty '+(error?'error':'')+'">'+esc(message)+'</p>';
  }
  function fmt(value, key) {
    if(value==null || !Number.isFinite(Number(value))) return '—';
    const m=metrics[key]||{}, n=Number(value);
    if(m.unit==='percent') return (n*100).toLocaleString('zh-CN',{maximumFractionDigits:2})+'%';
    return (m.unit==='money'?'¥':'')+n.toLocaleString('zh-CN',{maximumFractionDigits:key==='replenishment_daily_sales'?4:2});
  }
  const pct = v => v==null?'—':(v*100).toFixed(1)+'%';
  const labelOrder = item => item.id===900100?900299:Number(item.id??Infinity);
  const orderedLabels = items => items.slice().sort((a,b)=>(Number(a.parent_id||0)-Number(b.parent_id||0))||(labelOrder(a)-labelOrder(b)));
  function optionList(items,value,empty) { return (empty?'<option value="">'+esc(empty)+'</option>':'')+items.map(x=>{const v=typeof x==='object'?x.id:x,l=typeof x==='object'?x.label:x;return '<option value="'+esc(v)+'"'+(String(v)===String(value)?' selected':'')+'>'+esc(l)+'</option>';}).join(''); }
  function syncUrl() { const saved={...state}; history.replaceState(null,'','?q='+encodeURIComponent(JSON.stringify(saved))); }
  async function api(name,query,signal) {
    if(name==='summary')query={...query,columns:[...new Set([...columns(),'object_count','zero_inventory_count'])]};
    const response=await fetch('/api/label-analysis/'+name,{method:query?'POST':'GET',headers:query?{'Content-Type':'application/json'}:undefined,body:query?JSON.stringify(query):undefined,signal});
    if(!response.ok) {let data;try{data=await response.json();}catch(_){data={};} const msg=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||response.status);const error=new Error(msg);error.status=response.status;throw error;}
    return name==='export'?response.blob():response.json();
  }
  function columns() {
    if(group==='全部'){
      const order=['经营','利润','库存','覆盖与补货','缺货','流量','广告','售后','历史销售角色'];
      const available=[...new Set(Object.values(metrics).map(m=>m.group))];
      const groups=order.filter(g=>available.includes(g)).concat(available.filter(g=>g!=='规模'&&!order.includes(g)),'规模');
      return groups.flatMap(g=>Object.keys(metrics).filter(k=>k!=='object_count'&&!omittedColumns.has(k)&&metrics[k].available&&metrics[k].group===g));
    }
    if(group==='库存资金专项')return capitalColumns;if(group==='流量')return trafficColumns;if(group==='缺货')return stockoutColumns;
    if(group==='自定义')return custom.filter(k=>metrics[k]&&!omittedColumns.has(k));
    return Object.keys(metrics).filter(k=>!omittedColumns.has(k)&&metrics[k].group===group&&metrics[k].available&&metrics[k].aggregation!=='count').slice(0,12);
  }
  function activeCategories() { return orderedLabels(meta.categories||[]).filter(c=>state.view==='country'||c.scope!=='country'); }
  function labelName(parent,id) { const p=meta.categories.find(c=>c.id===parent); const c=p&&p.children.find(x=>x.id===id);return c?c.label:String(id); }
  function conditionName(c) { if(c.kind==='coverage')return coverageNames[c.reason]||'可售天数数据待核';return c.kind==='label'?c.ids.slice().sort((a,b)=>a-b).map(id=>labelName(c.parent_id,id)).join(' 或 '):(metrics[c.metric]?.label||c.metric)+' '+({gt:'>',gte:'≥',lt:'<',lte:'≤',eq:'=',range:'区间',between:'区间',missing:'缺失',present:'有效'}[c.op])+(c.value==null?'':' '+c.value)+(c.upper==null?'':' ～ '+c.upper); }
  function renderChips() {
    $('laQuick180').classList.toggle('active',state.conditions.some(c=>c.preset==='capital'&&c.metric==='fba_coverage_days'&&c.op==='gt'&&c.value===180));
    $('laChips').innerHTML=state.conditions.length?state.conditions.map((c,i)=>'<span class="la-chip">'+esc(conditionName(c))+'<button type="button" data-remove="'+i+'" aria-label="移除'+esc(conditionName(c))+'">×</button></span>').join(''):'<span class="summary-hint">全部商品</span>';
    $('laCohortTitle').textContent=state.conditions.length?state.conditions.map(conditionName).join(' × '):'全部商品';
    $('laBack').disabled=!state.conditions.length;
  }
  function addLabels(pairs,replace=false) {for(const [parent,id] of pairs){const found=state.conditions.find(c=>c.kind==='label'&&c.parent_id===parent);if(found){if(replace)found.ids=[id];else if(!found.ids.includes(id))found.ids.push(id);}else state.conditions.push({kind:'label',parent_id:parent,ids:[id]});}state.page=1;load();}
  function addLabel(parent,id) {addLabels([[parent,id]]);}
  function renderControls() {
    renderCustomControls();
    const cats=activeCategories();
    $('laLabelParent').innerHTML=optionList(cats,$('laLabelParent').value); renderChildren();
    for(const id of ['laMatrixA','laMatrixB']) $(''+id).innerHTML=optionList(cats,$(id).value);
    if(!state.matrix_parents.length && cats.length>1){$('laMatrixA').value=cats[0].id;$('laMatrixB').value=(cats.find(c=>c.id===3)||cats[1]).id;}
    if(state.matrix_parents.length===2){$('laMatrixA').value=state.matrix_parents[0];$('laMatrixB').value=state.matrix_parents[1];}
    $('laCountry').disabled=state.view!=='country';
  }
  function renderChildren() { const p=meta.categories.find(c=>c.id===Number($('laLabelParent').value));$('laLabelChild').innerHTML=optionList(orderedLabels(p?.children||[]).filter(c=>c.enabled!==false),null); }
  function metricHint(cell,key) {
    const m=metrics[key]||{},c=cell||{};
    return [m.formula,'有效数据 '+(c.valid_count??0)+' / '+(c.total_count??0),c.observed_object_days==null?'':'已记录商品天数 '+c.observed_object_days+' / 应统计 '+c.expected_object_days,c.zero_filled_object_days?'无经营记录按0计入：累计 '+c.zero_filled_object_days+' 个商品天数':'',c.reason||'',m.source||''].filter(Boolean).join('\n');
  }
  function metricCell(cell,key,shareBase) {
    const value=cell?.value;
    return '<td title="'+esc(metricHint(cell,key))+'">'+fmt(value,key)+(cell?.status==='partial'?'<span class="la-partial" title="'+esc(metricHint(cell,key))+'">部分</span>':'')+(shareBase!=null&&metrics[key]?.share?'<small>'+pct(value==null||shareBase<=0?null:value/shareBase)+'</small>':'')+'</td>';
  }
  function renderTagTable() {
    renderCustomControls();
    if(!payload)return;
    const cols=columns().filter(k=>k!=='object_count'),search=$('laTagSearch').value.trim();
    const cats=orderedLabels(payload.categories).filter(c=>!search||c.label.includes(search)||c.children.some(t=>t.label.includes(search)));
    let cat=cats.find(c=>c.id===Number(state.overview_parent))||cats[0];
    if(cat&&state.overview_parent!==cat.id){state.overview_parent=cat.id;syncUrl();}
    $('laTagCategories').innerHTML=cats.map(c=>'<button type="button" class="label-hub-category-card la-category '+(cat?.id===c.id?'active':'')+'" data-category="'+c.id+'" aria-pressed="'+(cat?.id===c.id)+'"><span><b>'+esc(c.label)+'</b><small>'+c.children.length+' 个子标签 · '+(c.scope==='country'?'国家':'国家类别')+'</small></span><i aria-hidden="true">›</i></button>').join('')||'<div class="la-empty">没有匹配标签</div>';
    if(!cat){$('laTagTable').innerHTML='';return;}
    const children=orderedLabels(cat.children).filter(c=>!search||cat.label.includes(search)||c.label.includes(search));
    const all=group==='全部',moneyCount=cols.filter(k=>metrics[k].unit==='money').length,metricHeaders=cols.map(k=>'<th scope="col" data-metric="'+k+'" title="'+esc(metrics[k].label+'\n'+metrics[k].formula)+'"><span class="la-metric-name">'+esc(metrics[k].label)+'</span></th>').join('');
    const historical=group==='历史销售角色';
    const roleHead=historical?'<th class="la-history-roles" title="各历史主导角色的商品数；点击角色可与当前标签联动筛选">历史主导角色构成</th>':'';
    const roleCell=child=>historical?'<td class="la-history-roles">'+(child.history_roles||[]).filter(r=>r.count).map(r=>'<button type="button" class="la-history-role" data-tag-parent="9001" data-tag="'+r.tag_id+'" data-history-parent="'+cat.id+'" data-history-label="'+child.id+'" title="筛选历史主导角色：'+esc(r.label)+'">'+esc(r.label.replace('产品',''))+' '+r.count+'</button>').join('')+'</td>':'';
    let head='<tr><th scope="col">标签</th><th scope="col">对象数 / 占比</th>'+roleHead+metricHeaders+'</tr>',colgroup='';
    if(all){
      const domains=[];for(const key of cols){const name=metrics[key].group,last=domains[domains.length-1];if(last?.name===name)last.count++;else domains.push({name,count:1});}
      head='<tr class="la-metric-domains"><th scope="col" rowspan="2" class="la-fixed-label">标签</th><th scope="col" rowspan="2" class="la-fixed-count">对象数 / 占比</th>'+domains.map(d=>'<th scope="colgroup" colspan="'+d.count+'">'+esc(groupLabel(d.name))+'</th>').join('')+'</tr><tr>'+metricHeaders+'</tr>';
      colgroup='<colgroup><col style="width:var(--la-label-width)"><col style="width:var(--la-count-width)">'+cols.map(k=>'<col style="width:var(--la-'+(metrics[k].unit==='money'?'money':'metric')+'-width)">').join('')+'</colgroup>';
    }
    $('laTagTable').innerHTML='<div class="la-table-title">'+esc(cat.label)+'</div>'+(historical?'<p class="la-history-note">上架起至 '+esc(payload.data_date)+' · 每30天一段 · 占比按有效周期数计算</p>':'')+(group==='缺货'?'<p class="summary-hint">'+esc(payload.period_start)+' — '+esc(payload.data_date)+' · '+payload.period+'天 · FBA可售库存为0记为断货</p>':'')+'<table class="la-table'+(all?' la-all-table':historical?' la-history-table':group==='缺货'?' la-stockout-table':'')+'"'+(all?' style="width:calc(var(--la-label-width) + var(--la-count-width) + '+(cols.length-moneyCount)+' * var(--la-metric-width) + '+moneyCount+' * var(--la-money-width))"':'')+'>'+colgroup+'<thead>'+head+'</thead><tbody>'+children.map(c=>'<tr class="'+(state.conditions.some(s=>s.kind==='label'&&s.parent_id===cat.id&&s.ids.includes(c.id))?'selected':'')+'"><td class="la-fixed-label" title="'+esc(c.label)+'"><button class="la-link" data-tag-parent="'+cat.id+'" data-tag="'+c.id+'" '+(c.enabled===false?'disabled':'')+'>'+esc(c.label)+'</button>'+(c.enabled===false?'<small>未启用</small>':'')+'</td><td class="la-fixed-count">'+fmt(c.count,'object_count')+'<small>'+pct(payload.current.object_count.value>0?c.count/payload.current.object_count.value:null)+'</small></td>'+roleCell(c)+cols.map(k=>metricCell(c.metrics[k],k,payload.current[k]?.value)).join('')+'</tr>').join('')+'</tbody></table>';
  }
  function renderMetrics() {
    const ids=['object_count','sales_qty','sales_amount','order_gross_profit','inventory_cost','ending_inventory_qty','fba_coverage_days','sellable_inventory_cost'];
    const labels={object_count:'商品对象数',sales_qty:'销量',sales_amount:'销售额',order_gross_profit:'订单毛利',inventory_cost:'FBA总库存成本',ending_inventory_qty:'FBA可售库存',fba_coverage_days:'可售天数 · 中位数',sellable_inventory_cost:'FBA可售库存成本'};
    $('laCards').innerHTML=ids.map(k=>{const c=payload.current[k];const hint=metricHint(c,k)+'\n占总体 '+pct(c.overall_share)+' · 占上层 '+pct(c.parent_share)+(k==='order_gross_profit'?'\n正毛利 '+fmt(payload.current.positive_profit.value,'positive_profit')+' · 亏损 '+fmt(payload.current.loss_amount.value,'loss_amount'):'');return '<article class="sales-role-kpi la-card" data-metric="'+k+'" title="'+esc(hint)+'"><span>'+esc(labels[k])+'</span><strong>'+fmt(c.value,k)+'</strong><small>'+(c.status==='partial'?'<span class="la-partial">部分数据</span> ':'')+(metrics[k].share?'占总体 '+pct(c.overall_share):k==='fba_coverage_days'?'P25 '+fmt(c.p25,k)+' · P75 '+fmt(c.p75,k):'较上期 '+fmt(payload.comparison[k].delta,k))+'</small></article>';}).join('');
    const cols=columns().filter(k=>k!=='fba_coverage_days');
    $('laMetricTable').innerHTML='<table class="la-table"><thead><tr><th>指标</th><th>当前群体</th><th>总体</th><th>上层群体</th><th>占总体 / 差异</th><th>占上层 / 差异</th><th>上期同群体</th><th>较上期变化</th></tr></thead><tbody>'+cols.map(k=>{const m=metrics[k],c=payload.current[k],diff=payload.comparison[k],bc=payload.baseline_comparison[k],pc=payload.parent_comparison[k];return '<tr><td title="'+esc(m.formula)+'">'+esc(m.label)+(m.aggregation==='median'?'<small>群体中位数</small>':'')+'</td>'+metricCell(c,k)+metricCell(payload.baseline[k],k)+metricCell(payload.parent[k],k)+'<td>'+(m.share?pct(c.overall_share):m.unit==='percent'?(bc.percentage_points==null?'—':bc.percentage_points.toFixed(2)+' 个百分点'):fmt(bc.delta,k))+'</td><td>'+(m.share?pct(c.parent_share):m.unit==='percent'?(pc.percentage_points==null?'—':pc.percentage_points.toFixed(2)+' 个百分点'):fmt(pc.delta,k))+'</td>'+metricCell(payload.previous[k],k)+'<td>'+fmt(diff.delta,k)+'<small>'+(m.unit==='percent'?(diff.percentage_points==null?'—':diff.percentage_points.toFixed(2)+' 个百分点'):pct(diff.relative_change))+'</small></td></tr>';}).join('')+'</tbody></table>';
  }
  function renderCapital() {
    const cap=payload.capital,scope=cap.scope,selected=state.conditions.filter(c=>c.preset==='capital');
    const isActive=b=>selected.length===b.conditions.length&&b.conditions.every(c=>selected.some(s=>s.kind===c.kind&&(s.reason||'')===(c.reason||'')&&(s.metric??null)===(c.metric??null)&&(s.op||'eq')===(c.op||'eq')&&(s.value??null)===(c.value??null)&&(s.upper??null)===(c.upper??null)));
    const shortLabels=['≤90天','90—180天','>180天'];
    $('laCapitalScope').textContent='分档参照 '+fmt(scope.object_count.value,'object_count')+' 个对象';
    $('laCapitalScope').title='保留其他标签、店铺和手工指标条件，仅移除专项分档条件；库存成本按池去重，分组不可直接相加。';
    $('laCapitalSummary').textContent='>180天 '+fmt(cap.bands[2].metrics.object_count.value,'object_count')+' 个对象';
    const card=(b,action,label)=>'<button type="button" class="label-hub-category-card la-capital-band '+(isActive(b)?'active':'')+'" '+action+' aria-pressed="'+isActive(b)+'" title="'+esc((b.description?b.description+'\n':'')+metricHint(b.metrics.inventory_cost,'inventory_cost'))+'"><span>'+esc(label)+'</span><strong>'+fmt(b.metrics.object_count.value,'object_count')+'<small> 个对象</small></strong><span>'+fmt(b.metrics.inventory_cost.value,'inventory_cost')+'</span><small>占参照金额 '+pct(scope.inventory_cost.value>0&&b.metrics.inventory_cost.value!=null?b.metrics.inventory_cost.value/scope.inventory_cost.value:null)+'</small></button>';
    $('laCapitalBands').innerHTML=cap.bands.slice(0,3).map((b,i)=>card(b,'data-capital="'+i+'"',shortLabels[i])).join('');
    $('laCapitalGapTitle').textContent='暂未形成可售天数 · '+fmt(cap.bands[3].metrics.object_count.value,'object_count')+' 个对象';
    $('laCapitalGaps').innerHTML=(cap.coverage_gaps||[]).map(b=>card(b,'data-capital-gap="'+esc(b.key)+'"',b.label)).join('');
    const z=cap.zero_demand;$('laCapitalZero').innerHTML='<span title="有FBA可售库存且完整需求日销为零；可售天数无法计算">零日销库存 '+fmt(z.metrics.object_count.value,'object_count')+' 个对象 · '+fmt(z.metrics.inventory_cost.value,'inventory_cost')+'</span><button class="text-button" type="button" data-capital="zero" aria-pressed="'+isActive(z)+'">查看</button>';
    const fields=['object_count','inventory_cost','sales_qty','order_gross_profit','sessions_total'];
    const table=(items,kind,parent)=>'<table class="la-table"><thead><tr><th>'+esc(kind)+'</th>'+fields.map(k=>'<th>'+esc(metrics[k].label)+'</th>').join('')+'</tr></thead><tbody>'+items.map((r,i)=>'<tr><td>'+(r.id===null?esc(r.label):'<button class="la-link" '+(parent?'data-capital-parent="'+parent+'" data-capital-label="'+r.id+'"':'data-rank="'+i+'"')+'>'+esc(r.label)+'</button>')+'</td>'+fields.map(k=>metricCell(r.metrics[k],k,payload.current[k].value)).join('')+'</tr>').join('')+'</tbody></table>';
    $('laCapitalStructure').innerHTML=orderedLabels(cap.structures).map(c=>'<div data-inventory-panel="'+(c.label==='销售角色'?'roles':'status')+'" class="la-table-wrap" hidden>'+table(orderedLabels(c.children),c.label,c.id)+'</div>').join('');
    $('laCapitalRanks').innerHTML=table(cap.ranks,'排名分档');
    applyTabs();
  }
  function applyTabs() {
    for(const [kind,key,valid] of [['inventory','inventory_tab',['coverage','roles','status','ranks']],['topic','topic_tab',['trend','stockout','matrix','stores']]]) {
      if(!valid.includes(state[key]))state[key]=valid[0];
      document.querySelectorAll('[data-'+kind+'-panel]').forEach(el=>el.hidden=el.dataset[kind+'Panel']!==state[key]);
      document.querySelectorAll('[data-'+kind+'-tab]').forEach(el=>{const active=el.dataset[kind+'Tab']===state[key];el.classList.toggle('active',active);el.setAttribute('aria-pressed',String(active));});
    }
  }
  function restoreSections() {
    const open=Array.isArray(state.open_sections)?state.open_sections:[];
    for(const id of ['laCapital','laTopics','laComparison','laSourcesPanel','laMoreFilters'])$(id).open=open.includes(id);
    applyTabs();
  }
  function applyCapitalPreset(bucket) {
    if(!payload)return;
    state.conditions=state.conditions.filter(c=>c.preset!=='capital').concat(bucket.conditions);state.page=1;state.sort='inventory_cost';$('laSort').value=state.sort;$('laCapital').open=true;changeGroup('库存资金专项');
  }
  function bar(label,value,total,buttonAttrs='') {return '<div class="la-bar-row">'+(buttonAttrs?'<button type="button" '+buttonAttrs+'>'+esc(label)+'</button>':'<span>'+esc(label)+'</span>')+'<div class="la-track"><div class="la-fill" style="width:'+Math.min(100,Math.max(0,total>0?value/total*100:0))+'%"></div></div><span class="la-bar-value">'+Number(value||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+'</span></div>';}
  function renderTopics() {
    $('laCoverage').innerHTML=payload.coverage_distribution.map((b,i)=>bar(b.label,b.count,payload.current.object_count.value,'data-coverage="'+i+'"')).join('');
    const keys=[...stockoutColumns,'current_inventory_unknown_count'];
    $('laStockout').innerHTML='<div class="la-toolbar"><span class="summary-hint">'+esc(payload.period_start)+' — '+esc(payload.data_date)+' · '+payload.period+'天</span><button type="button" class="ghost-button" data-stockout-filter="period">查看周期断货商品</button><button type="button" class="ghost-button" data-stockout-filter="current">查看当前断货商品</button></div><table class="la-table"><tbody>'+keys.map(k=>'<tr><td title="'+esc(metrics[k].formula)+'">'+esc(metrics[k].label)+'</td>'+metricCell(payload.current[k],k)+'</tr>').join('')+'</tbody></table>';
    const stores=payload.breakdowns.store.slice().sort((a,b)=>(b.metrics.sales_amount.value||0)-(a.metrics.sales_amount.value||0)).slice(0,10);
    const max=Math.max(...stores.map(s=>s.metrics.sales_amount.value||0),1);
    $('laStores').innerHTML=stores.map((s,i)=>bar(s.label,s.metrics.sales_amount.value,max,'data-store="'+esc(s.label)+'"')).join('')+'<p class="summary-hint">销售额 · Top10店铺</p>';
    if(payload.matrix.length){ const a=Number($('laMatrixA').value),b=Number($('laMatrixB').value),metric=columns()[0]||'object_count';$('laMatrix').innerHTML='<table class="la-table"><thead><tr><th>标签组合</th><th>'+esc(metrics[metric].label)+'</th></tr></thead><tbody>'+payload.matrix.map(c=>'<tr><td><button class="la-link" data-matrix="'+c.row_id+','+c.column_id+'">'+esc(labelName(a,c.row_id))+' × '+esc(labelName(b,c.column_id))+'</button></td>'+metricCell(c.metrics[metric],metric)+'</tr>').join('')+'</tbody></table>'; }
    else $('laMatrix').innerHTML='<p class="la-muted">交叉数据尚未查询</p>';
    if(payload.matrix.length) renderMatrix();
    const operating=payload.categories.find(c=>c.id===3);
    if(operating)$('laStockout').innerHTML+='<p class="la-muted">当前断货商品的运营状态（状态可重叠）</p>'+orderedLabels(operating.children).filter(c=>c.count).map(c=>'<span class="la-chip">'+esc(c.label)+'：'+fmt(c.metrics.zero_inventory_count.value,'number')+'</span>').join(' ');
  }
  function renderMatrix() {
    const [a,b]=state.matrix_parents, key=columns()[0]||'object_count';
    const rows=[...new Set(payload.matrix.map(c=>c.row_id))].sort((a,b)=>a-b),cols=[...new Set(payload.matrix.map(c=>c.column_id))].sort((a,b)=>a-b);
    const cells=new Map(payload.matrix.map(c=>[c.row_id+','+c.column_id,c]));
    $('laMatrix').innerHTML='<p class="la-muted">'+esc(metrics[key].label)+'</p><table class="la-table"><thead><tr><th>标签交叉</th>'+cols.map(c=>'<th>'+esc(labelName(b,c))+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr><td>'+esc(labelName(a,r))+'</td>'+cols.map(c=>{const item=cells.get(r+','+c);return '<td><button class="la-link" data-matrix="'+r+','+c+'">'+(item?fmt(item.metrics[key].value,key):'—')+'</button></td>';}).join('')+'</tr>').join('')+'</tbody></table>';
  }
  function renderDetails(p) {
    detailPayload=p;total=p.total;const cols=columns().filter(k=>metrics[k].filterable);
    $('laDetailCount').textContent=total.toLocaleString()+' 个对象';
    if(gridApi&&gridGroup)gridStates[gridGroup]=gridApi.getColumnState().map(({colId,width,pinned,hide})=>({colId,width,pinned,hide}));
    const columnDefs=[
      {field:'msku',headerName:'MSKU',pinned:'left',width:180,cellRenderer:params=>'<button class="text-button la-object-link" data-object="'+esc(params.data.key)+'">'+esc(params.value)+'</button>'},
      {field:'store',headerName:'店铺',width:145},
      {field:'country_display',headerName:'国家范围',width:120,sortable:false},
      {field:'tag_summary',headerName:'销售角色 / 运营状态',width:220,sortable:false},
      ...(['历史销售角色','全部'].includes(group)?[{field:'historical_role',headerName:'历史主导角色',width:150,sortable:false}]:[]),
      ...cols.map(k=>({field:k,headerName:metrics[k].label,width:150,sort:state.sort===k?(state.descending?'desc':'asc'):null,cellClass:'ag-grid-number-cell',valueFormatter:params=>fmt(params.value,k),tooltipValueGetter:params=>metrics[k].formula+(k==='fba_coverage_days'?'\n'+params.data.coverage_reason:'')+(k==='current_stockout_days'&&params.data.inventory_boundary_lower_bound?'\n至少已确认，历史边界不完整':'')}))
    ];
    for(const c of columnDefs)if(c.field===state.sort)c.sort=state.descending?'desc':'asc';
    const rows=p.rows.map(r=>({...r,...r.values,country_display:r.country||r.country_category,historical_role:(r.labels||[]).find(t=>t.parent_id===9001)?.label||'历史数据未覆盖',tag_summary:orderedLabels(r.labels).filter(t=>[1,3].includes(t.parent_id)).map(t=>t.label||labelName(t.parent_id,t.id)).join(' / ')}));
    gridRendering=true;
    window.kanbanGrid.destroy('laDetailTable');
    $('laDetailTable').replaceChildren();
    gridApi=window.kanbanGrid.makeGrid('laDetailTable',{
      rowData:rows,columnDefs,domLayout:'normal',rowHeight:46,headerHeight:46,suppressMultiSort:true,
      defaultColDef:{sortable:true,filter:false,resizable:true,minWidth:100,wrapHeaderText:true,autoHeaderHeight:true,sortingOrder:['asc','desc']},
      getRowId:params=>params.data.key,
      onSortChanged:event=>{if(gridRendering)return;const sorted=event.api.getColumnState().find(c=>c.sort);if(!sorted||(sorted.colId===state.sort&&(sorted.sort==='desc')===state.descending))return;state.sort=sorted.colId;state.descending=sorted.sort==='desc';state.page=1;$('laSort').value=state.sort;$('laDirection').textContent=state.descending?'降序 ↓':'升序 ↑';loadDetails();}
    });
    if(gridApi&&gridStates[group])gridApi.applyColumnState({state:gridStates[group],applyOrder:true});
    gridGroup=group;gridRendering=false;
    $('laPageLabel').textContent=state.page+' / '+Math.max(1,Math.ceil(total/state.page_size));$('laPrev').disabled=state.page<=1;$('laNext').disabled=state.page*state.page_size>=total;
  }
  async function recoverExpired(error,requestEpoch) {
    if(error.status!==409||requestEpoch!==epoch||recoveringVersion)return false;
    recoveringVersion=true;
    const refreshEpoch=epoch+1;
    try {state.version='';syncUrl();await load(false,true);return epoch===refreshEpoch&&Boolean(state.version)&&!$('laStatus').classList.contains('error');}
    finally {recoveringVersion=false;}
  }
  async function loadDetails(myEpoch=epoch,allowRecovery=true) {
    const request=++detailsRequest;syncUrl();
    try {const p=await api('details',state,controller?.signal);if(myEpoch===epoch&&request===detailsRequest)renderDetails(p);}
    catch(e){if(e.name!=='AbortError'&&myEpoch===epoch&&request===detailsRequest){if(e.status===409&&allowRecovery){await recoverExpired(e,myEpoch);return;}status(e.message,true);window.kanbanGrid.destroy('laDetailTable');gridApi=null;$('laDetailTable').innerHTML='<p class="la-empty error">'+esc(e.message)+'</p>';}}
  }
  async function load(allowRecovery=true,forceRefresh=false) {
    const currentEpoch=++epoch;if(controller)controller.abort();controller=new AbortController();trendPayload=null;trendRequest++;trendLoading=false;resetTrend('正在更新分析范围…');
    syncUrl();renderChips();$('laLoadNotice').hidden=false;status('正在读取已发布的分析结果…');pendingModules('正在读取分析结果…');$('laStatus').classList.add('loading');$('analysisApp').setAttribute('aria-busy','true');
    const started=Date.now(),timer=setInterval(()=>{if(currentEpoch===epoch&&!payload){$('laLoadNotice').textContent='正在读取并汇总分析数据 · 已等待 '+Math.floor((Date.now()-started)/1000)+' 秒。页面会在查询完成后自动呈现。';}},1000);
    try {const p=await api('summary',{...state,force_refresh:forceRefresh},controller.signal);if(currentEpoch!==epoch)return;payload=p;state.version=p.version;state.data_date=p.data_date;meta.categories=p.categories;if(![...$('laDate').options].some(o=>o.value===p.data_date))$('laDate').add(new Option(p.data_date,p.data_date));$('laDate').value=p.data_date;
      const o=p.options;$('laCategory').innerHTML=optionList(o.country_categories,state.country_categories[0],'全部类别');$('laCountry').innerHTML=optionList(o.countries,state.countries[0],'全部国家');$('laStore').innerHTML=optionList(o.stores,state.stores[0],'全部店铺');
      $('laDenominators').textContent='总体 '+p.baseline.object_count.value.toLocaleString()+' / 上层 '+p.parent.object_count.value.toLocaleString()+' / 当前 '+p.current.object_count.value.toLocaleString()+' 个对象';$('laDenominators').title=p.baseline_description+'；'+p.parent_description;$('laHeaderDate').textContent='数据日期 '+p.data_date+' · 标签 '+p.sources.labels;
      $('laWindow').textContent=p.period_start+' — '+p.data_date+' · 标签 '+p.sources.labels+(p.sources.label_window_days&&p.sources.label_window_days!==p.period?'（'+p.sources.label_window_days+'天口径）':'');
      renderTagTable();renderMetrics();renderTopics();renderCapital();
      $('laSources').innerHTML='<ul>'+p.warnings.map(w=>'<li>'+esc(w)+'</li>').join('')+'</ul><p class="la-snapshot">数据版本 '+esc(p.version)+' · 公式 '+esc(p.formula_version)+'</p><pre class="la-snapshot">'+esc(JSON.stringify(p.sources,null,2))+'</pre>';
      resetTrend('展开后加载每日趋势');
      status('已加载 '+p.current.object_count.value.toLocaleString()+' 个商品对象 · 经营数据覆盖 '+pct(p.current.sales_coverage_rate.value)+' · 库存观察覆盖 '+pct(p.current.inventory_observation_rate.value));
      await loadDetails(currentEpoch,allowRecovery);
    }catch(e){if(e.name!=='AbortError'&&currentEpoch===epoch){if(e.status===409&&allowRecovery){await recoverExpired(e,currentEpoch);return;}status(e.message+'；点击“刷新数据”重新加载。',true);pendingModules('读取失败：'+e.message+'。请点击页面顶部“刷新数据”重试。',true);}}finally{clearInterval(timer);if(currentEpoch===epoch){$('analysisApp').setAttribute('aria-busy','false');$('laLoadNotice').hidden=!$('laStatus').classList.contains('error');maybeLoadTrend(allowRecovery);}}
  }
  function resetTrend(message) {
    if(trendChart){trendChart.dispose();trendChart=null;}
    $('laTrend').innerHTML='<p class="la-empty">'+esc(message)+'</p>';
    $('laTrend').setAttribute('aria-busy','false');
    $('laTrendPeriods').hidden=true;$('laTrendScope').textContent='';
    $('laLoadTrends').disabled=false;$('laLoadTrends').textContent='加载趋势';
  }
  function maybeLoadTrend(allowRecovery=true) {
    if(payload&&$('laTopics').open&&state.topic_tab==='trend'&&!trendPayload&&!trendLoading&&$('analysisApp').getAttribute('aria-busy')==='false'&&!$('laStatus').classList.contains('error'))loadTrends(allowRecovery);
  }
  async function loadTrends(allowRecovery=true) {
    if(trendLoading)return;
    const e=epoch,request=++trendRequest;trendLoading=true;trendPayload=null;
    resetTrend('正在读取每日趋势…');$('laTrend').setAttribute('aria-busy','true');$('laLoadTrends').disabled=true;$('laLoadTrends').textContent='加载中…';
    try {const result=await api('trends',state,controller?.signal);if(e!==epoch||request!==trendRequest)return;trendPayload=result;renderTrend();}
    catch(error){if(error.name!=='AbortError'&&e===epoch&&request===trendRequest){if(error.status===409&&allowRecovery){if(await recoverExpired(error,e))await loadTrends(false);return;}resetTrend(error.message);}}
    finally{if(e===epoch&&request===trendRequest){trendLoading=false;$('laTrend').setAttribute('aria-busy','false');$('laLoadTrends').disabled=false;$('laLoadTrends').textContent=trendPayload?'刷新趋势':'重试';}}
  }
  function renderTrend() {
    if(!trendPayload||!$('laTrend').clientWidth)return;
    const key=$('laTrendMetric').value,a=trendPayload.current,b=trendPayload.previous,m=metrics[key];
    const values=[...a,...b].map(r=>r[key]).filter(v=>v!=null);
    if(!values.length){resetTrend('当前及上期没有有效趋势数据');return;}
    if(!window.echarts){resetTrend('图表组件未加载，请刷新页面');return;}
    const range=rows=>rows.length?rows[0].date+' — '+rows[rows.length-1].date:'无日期';
    $('laTrendPeriods').innerHTML='<span><i class="la-trend-swatch"></i><b>本期</b>'+esc(range(a))+'</span><span><i class="la-trend-swatch previous"></i><b>上期</b>'+esc(range(b))+'</span><small>按周期天数对齐</small>';
    $('laTrendPeriods').hidden=false;$('laTrendScope').textContent='当前群体 · '+trendPayload.member_count.toLocaleString()+' 个商品对象';
    $('laTrendScope').title='本期、上期均使用当前选中的商品群体；经营日记录缺行按0，已有记录空字段及库存缺失留空。';
    $('laTrend').setAttribute('aria-label',m.label+'每日走势，本期'+range(a)+'，上期'+range(b)+'，按周期天数对齐');
    if(!trendChart){$('laTrend').replaceChildren();trendChart=window.echarts.init($('laTrend'),null,{renderer:'canvas'});}
    const shortDay=value=>value.slice(5).replace('-','/');
    const axisValue=value=>Math.abs(value)>=10000?(value/10000).toLocaleString('zh-CN',{maximumFractionDigits:1})+'万':value.toLocaleString('zh-CN',{maximumFractionDigits:1});
    const axisUnit=m.unit==='money'?'金额（元）':['sales_qty','ending_inventory_qty','return_count'].includes(key)?'数量（件）':key==='ad_orders'?'订单（笔）':'数量（次）';
    trendChart.setOption({animation:false,aria:{enabled:true},textStyle:{fontFamily:getComputedStyle($('laTrend')).fontFamily},
      grid:{left:12,right:18,top:32,bottom:12,containLabel:true},
      tooltip:{trigger:'axis',confine:true,borderColor:'#dce6f1',padding:12,textStyle:{fontSize:12,color:'#173653'},axisPointer:{type:'line',lineStyle:{color:'#a8bdd6',type:'dashed'}},
        formatter:params=>{const i=params[0]?.dataIndex;if(i==null)return '';const row=(items,label)=>{const point=items[i],coverage=point?.coverage?.[key];return '<div class="la-trend-tooltip-row"><span>'+label+'</span><span>'+esc(point?.date||'—')+'</span><b>'+esc(point?.[key]==null?'未观测':fmt(point[key],key))+'</b>'+(coverage?'<small>有效样本 '+coverage.valid_count.toLocaleString()+' / '+coverage.total_count.toLocaleString()+'</small>':'')+'</div>';};return '<div class="la-trend-tooltip"><strong>'+esc(m.label)+' · 周期第 '+(i+1)+' 天</strong>'+row(a,'本期')+row(b,'上期')+'</div>'; }},
      xAxis:{type:'category',boundaryGap:false,data:a.map(r=>r.date),axisTick:{show:false},axisLine:{lineStyle:{color:'#dce6f1'}},axisLabel:{color:'#72859b',fontSize:11,interval:Math.max(0,Math.ceil((a.length-1)/($('laTrend').clientWidth<650?3:6))-1),hideOverlap:true,showMinLabel:true,showMaxLabel:true,formatter:shortDay}},
      yAxis:{type:'value',name:axisUnit,nameTextStyle:{color:'#72859b',align:'left',fontSize:11},splitNumber:4,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:'#72859b',fontSize:11,formatter:axisValue},splitLine:{lineStyle:{color:'#edf1f7',type:'dashed'}}},
      series:[{name:'上期',type:'line',data:b.map(r=>r[key]??null),showSymbol:false,symbol:'circle',symbolSize:6,connectNulls:false,lineStyle:{width:2,type:'dashed',color:'#94a3b8'},itemStyle:{color:'#94a3b8'},emphasis:{focus:'series'}},
        {name:'本期',type:'line',data:a.map(r=>r[key]??null),showSymbol:false,symbol:'circle',symbolSize:6,connectNulls:false,lineStyle:{width:2.5,color:'#1769e0'},itemStyle:{color:'#1769e0'},areaStyle:{color:'#1769e0',opacity:.035},emphasis:{focus:'series'}}]
    },true);trendChart.resize();
  }
  function resizeTrend() {
    if(!trendChart||!$('laTrend').clientWidth)return;
    trendChart.resize();
    trendChart.setOption({xAxis:{axisLabel:{interval:Math.max(0,Math.ceil((trendPayload.current.length-1)/($('laTrend').clientWidth<650?3:6))-1)}}});
  }
  async function openObject(key,allowRecovery=true) {
    const e=epoch,request=++drawerRequest;drawerProduct=null;drawerContext=null;drawerTab='overview';
    if(!$('laDrawer').open)$('laDrawer').showModal();
    $('laDrawerTitle').textContent='商品详情';$('laDrawerMeta').textContent='';$('laDrawerBody').scrollTop=0;
    $('laDrawerBody').innerHTML='<p class="la-empty">正在读取商品画像…</p>';$('laDrawerBody').setAttribute('aria-busy','true');
    try {
      const p=await api('details',{...state,object_key:key,page:1},controller?.signal);
      if(e!==epoch||request!==drawerRequest||!$('laDrawer').open)return;
      const r=p.rows[0];if(!r){$('laDrawerBody').textContent='当前筛选下没有该商品';return;}
      drawerProduct=r;drawerContext=p;
      $('laDrawerTitle').textContent=r.msku+' · '+r.store;
      $('laDrawerMeta').textContent=(r.country||r.country_category)+' · '+p.period_start+' — '+p.data_date+' · '+p.period+'天经营周期';
      renderDrawer();
    }catch(err){if(err.name!=='AbortError'&&e===epoch&&request===drawerRequest&&$('laDrawer').open){if(err.status===409&&allowRecovery){if(await recoverExpired(err,e)&&request===drawerRequest&&$('laDrawer').open)await openObject(key,false);return;}$('laDrawerBody').textContent=err.message;}}
    finally{if(request===drawerRequest)$('laDrawerBody').setAttribute('aria-busy','false');}
  }
  function drawerMetric(key) {
    const m=metrics[key],r=drawerProduct,value=r.values[key],observed=r.effective_days?.[key]??r.ratio_pairs?.[key]?.[2];
    const partial=observed!=null&&observed<r.period_days;
    const lowerBound=key==='current_stockout_days'&&r.inventory_boundary_lower_bound&&value>0;
    const hint=[m.formula,key==='fba_coverage_days'?r.coverage_reason:'',partial?'有效观察 '+observed+' / '+r.period_days+' 天':'',lowerBound?'至少已确认，历史边界不完整':'',m.source].filter(Boolean).join('\n');
    const note=value==null?(key==='fba_coverage_days'?'无法计算':'暂无有效值'):partial?'有效记录 '+observed+' / '+r.period_days+' 天':'';
    return '<div class="la-product-metric '+(value==null?'missing':value<0?'negative':'')+'" data-drawer-metric="'+key+'" title="'+esc(hint)+'"><dt>'+esc(m.label)+'</dt><dd>'+(lowerBound?'≥ ':'')+fmt(value,key)+(note?'<small>'+esc(note)+'</small>':'')+'</dd></div>';
  }
  function drawerMetricSection(title,keys,compact=false,subtitle='') {
    const valid=keys.filter(k=>metrics[k]?.available&&metrics[k]?.filterable);
    if(!valid.length)return '';
    return '<section class="la-product-section"><h3>'+esc(title)+(subtitle?'<small>'+esc(subtitle)+'</small>':'')+'</h3><dl class="la-product-metrics'+(compact?' compact':'')+'">'+valid.map(drawerMetric).join('')+'</dl></section>';
  }
  function drawerHistory() {
    const days=drawerProduct.history||[];
    return '<details class="la-product-fold" data-drawer-history><summary>每日记录 · '+days.length+' 天</summary>'+(days.length?'<div class="la-table-wrap"><table class="la-table"><thead><tr><th>日期</th><th>销量</th><th>销售额</th><th>FBA可售库存</th></tr></thead><tbody>'+days.slice().reverse().map(d=>'<tr><td>'+esc(d.date)+'</td><td>'+fmt(d.sales_qty,'sales_qty')+'</td><td>'+fmt(d.sales_amount,'sales_amount')+'</td><td>'+fmt(d.inventory,'ending_inventory_qty')+'</td></tr>').join('')+'</tbody></table></div>':'<p class="la-muted">没有可用的每日记录</p>')+'</details>';
  }
  function drawerSupply() {
    const r=drawerProduct;
    return '<details class="la-product-fold"><summary>补货口径与来源</summary><p class="la-muted">'+esc(r.coverage_mapping_status||'暂无映射信息')+'</p><p class="la-muted">'+esc(r.coverage_reason||'')+'</p><div class="la-product-note"><span>日销日期 <b>'+esc(r.replenishment_source_date||'未覆盖')+'</b></span><span>完整需求日销 <b>'+fmt(r.coverage_daily_sales,'replenishment_daily_sales')+'</b></span><span>完整需求库存 <b>'+fmt(r.coverage_inventory_qty,'ending_inventory_qty')+'</b></span></div>'+(r.replenishment&&Object.keys(r.replenishment).length?'<details class="la-product-fold"><summary>原始补货记录</summary><pre class="la-snapshot">'+esc(JSON.stringify(r.replenishment,null,2))+'</pre></details>':'')+'</details>';
  }
  function drawerEvidence() {
    const r=drawerProduct,labels=orderedLabels(r.labels||[]);
    if(!labels.length)return '<p class="la-empty">当前商品没有已匹配的标签</p>';
    return '<p class="la-muted">标签日期 '+esc(drawerContext.sources.labels||'—')+'</p>'+labels.map(t=>{
      const category=meta.categories.find(c=>c.id===t.parent_id),definition=category?.children.find(c=>c.id===t.id);
      const hits=(r.tag_evidence||[]).filter(item=>Number(item.label_id)===t.id&&(item.label_period||'')===(t.period||''));
      const records=hits.map(item=>{let value=item.evidence_blob;try{if(typeof value==='string')value=JSON.parse(value);}catch(_){}return '<details class="la-product-fold"><summary>原始命中记录</summary><pre class="la-snapshot">'+esc(typeof value==='string'?value:JSON.stringify(value,null,2))+'</pre></details>';}).join('');
      const period=t.period==='current'?'当前':t.period?.replace(/^(\d+)d$/,'$1天标签')||'';
      return '<details class="la-product-rule"><summary>'+esc(t.label)+'<small>'+esc(category?.label||'')+(period?' · '+esc(period):'')+'</small></summary><p class="la-muted">'+esc(definition?.rule||definition?.definition||'暂无规则说明')+'</p>'+records+'</details>';
    }).join('');
  }
  function renderDrawer() {
    if(!drawerProduct)return;
    const r=drawerProduct,section=drawerSections.find(t=>t.id===drawerTab)||drawerSections[0];
    const basic=orderedLabels(r.labels||[]).filter(t=>[1,2,3,8,13,14].includes(t.parent_id));
    const tags=basic.map(t=>'<span class="la-product-tag" title="'+esc(meta.categories.find(c=>c.id===t.parent_id)?.label||'')+'">'+esc(t.label)+'</span>').join('')||'<span class="la-muted">暂无基础标签</span>';
    const navigation='<div class="la-product-tags">'+tags+'<button type="button" class="text-button" data-drawer-tab="evidence">全部标签（'+(r.labels||[]).length+'）</button></div><nav class="la-product-tabs" aria-label="商品详情专题">'+drawerSections.map(t=>'<button type="button" data-drawer-tab="'+t.id+'" class="'+(t.id===section.id?'active':'')+'" aria-pressed="'+(t.id===section.id)+'">'+t.label+'</button>').join('')+'</nav>';
    let body='';
    if(section.id==='overview') {
      body=drawerMetricSection('经营表现',['sales_qty','sales_amount','order_gross_profit'],false,drawerContext.period+'天累计')+
        drawerMetricSection('库存情况',['ending_inventory_qty','sellable_inventory_cost','fba_coverage_days'],false,'截止 '+drawerContext.data_date)+
        '<div class="la-product-note"><span>日销 <b>'+fmt(r.values.replenishment_daily_sales,'replenishment_daily_sales')+'</b></span><span>日销日期 <b>'+esc(r.replenishment_source_date||'未覆盖')+'</b></span></div>'+drawerHistory();
    }else if(section.id==='role_history') {
      const tag=(r.labels||[]).find(t=>t.parent_id===9001),history=r.role_history;
      body='<div class="la-product-note"><span>历史主导角色 <b>'+esc(tag?.label||'历史数据未覆盖')+'</b></span><span>历史截止 <b>'+esc(history?.as_of_date||drawerContext.data_date)+'</b></span><span>源结果日期 <b>'+esc(history?.source_date||'未覆盖')+'</b></span></div>'+drawerMetricSection('历史角色次数与占比',section.primary,true,'仅有效完整30天周期参与统计；次数最多为主导角色，同次数取最近有效周期的角色。');
    }else if(section.id==='evidence')body=drawerEvidence();
    else {
      const additional=section.groups.map(group=>{
        const keys=Object.keys(metrics).filter(k=>!omittedColumns.has(k)&&metrics[k].available&&metrics[k].filterable&&metrics[k].group===group&&!section.primary.includes(k));
        const label=group==='覆盖与补货'?'补货':groupLabel(group);
        return keys.length?'<details class="la-product-fold" data-drawer-more><summary>更多'+esc(label)+'指标（'+keys.length+'）</summary>'+drawerMetricSection(label+'指标',keys,true)+'</details>':'';
      }).join('');
      body=drawerMetricSection(section.label,section.primary,true)+
        additional+
        (section.id==='stock'?drawerSupply():'');
    }
    $('laDrawerBody').innerHTML=navigation+'<div class="la-product-content" data-drawer-panel="'+section.id+'">'+body+'</div>';
  }
  function renderCustomControls() {
    $('laCustomControls').hidden=group!=='自定义';
    const count=custom.filter(k=>metrics[k]&&!omittedColumns.has(k)).length;
    $('laCustomHint').textContent=count?'已选 '+count+' 个展示指标':'尚未添加展示指标';
    $('laCustomEdit').textContent=count?'修改指标':'＋添加指标';
  }
  function openCatalog() {
    catalogDraft=custom.filter(k=>metrics[k]&&!omittedColumns.has(k));catalogGroup='';
    $('laMetricSearch').value='';$('laCatalogSelectedOnly').checked=false;
    renderCatalog();$('laCatalog').showModal();$('laMetricSearch').focus();
  }
  function catalogCount() {
    $('laCatalogCount').textContent='已选 '+catalogDraft.length+' 个字段';
    $('laClearColumns').disabled=!catalogDraft.length;
    const visible=Array.from($('laCatalogList').querySelectorAll('[data-column]:not(:disabled)'));
    const selected=visible.filter(input=>catalogDraft.includes(input.dataset.column)).length;
    $('laCatalogSelectAll').checked=visible.length>0&&selected===visible.length;
    $('laCatalogSelectAll').indeterminate=selected>0&&selected<visible.length;
    $('laCatalogSelectAll').disabled=!visible.length;
    $('laCatalogSelectAllLabel').textContent='全选当前结果（'+visible.length+'项）';
  }
  function renderCatalog() {
    const text=$('laMetricSearch').value.trim().toLowerCase(),selectedOnly=$('laCatalogSelectedOnly').checked;
    const entries=Object.entries(metrics).filter(([k])=>!omittedColumns.has(k));
    const groups=['',...new Set(entries.map(([,m])=>m.group))];
    $('laCatalogGroups').innerHTML=groups.map(g=>'<button type="button" data-catalog-group="'+esc(g)+'" aria-pressed="'+(g===catalogGroup)+'" class="'+(g===catalogGroup?'active':'')+'">'+esc(g?groupLabel(g):'全部')+'</button>').join('');
    const visible=entries.filter(([k,m])=>(!catalogGroup||m.group===catalogGroup)&&(!selectedOnly||catalogDraft.includes(k))&&[m.label,m.formula,m.group,groupLabel(m.group),m.source].join(' ').toLowerCase().includes(text));
    $('laCatalogList').innerHTML=visible.map(([k,m])=>'<article class="la-catalog-item '+(catalogDraft.includes(k)?'selected ':'')+(!m.available?'pending':'')+'"><label class="la-catalog-choice"><input type="checkbox" data-column="'+esc(k)+'" '+(catalogDraft.includes(k)?'checked ':'')+(!m.available?'disabled ':'')+'><span>'+esc(m.label)+'<small>'+esc(groupLabel(m.group))+'</small></span>'+(!m.available?'<span class="la-catalog-pending">待接入</span>':'')+'</label><details class="la-catalog-definition"><summary>查看口径</summary><p>'+esc(m.formula)+'</p><p>来源：'+esc(m.source)+'</p><small>粒度：'+esc(m.grain)+' · '+esc(m.aggregation)+(m.filterable?' · 支持商品筛选':' · 群体指标或待接入')+'</small></details></article>').join('')||'<p class="la-empty">'+(selectedOnly?'没有符合条件的已选字段':'没有找到匹配的字段')+'</p>';
    $('laCatalogList').scrollTop=0;
    catalogCount();
  }
  async function exportCsv(kind,selectedColumns=columns(),allowRecovery=true) {const e=epoch;if(kind==='summary'&&group==='全部')selectedColumns=['object_count',...selectedColumns.filter(k=>k!=='object_count')];if(kind==='details')selectedColumns=selectedColumns.filter(k=>metrics[k]?.filterable);try{status('正在导出完整筛选结果…');const raw=await api('export',{...state,export_kind:kind,columns:selectedColumns});const text=(await raw.text()).replace(/^\uFEFF/,'');const newline=text.indexOf('\n');const header=(newline<0?text:text.slice(0,newline)).replace(/\r$/,'').split(',').map(label=>exportMetricNames[label]||label).join(',');const blob=new Blob(['\uFEFF'+header+(newline<0?'':text.slice(newline))],{type:raw.type});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='标签综合分析-'+kind+'-'+state.data_date+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);status('导出完成');}catch(error){if(error.status===409&&allowRecovery&&e===epoch){if(await recoverExpired(error,e))await exportCsv(kind,selectedColumns,false);return;}if(e===epoch)status(error.message,true);}}
  function changeGroup(next) {group=next;state.column_group=next;$('laDetailGroup').value=next;document.querySelectorAll('[data-group]').forEach(b=>b.classList.toggle('active',b.dataset.group===group));renderCustomControls();load();}
  $('laCapital').onclick=e=>{const preset=e.target.closest('[data-capital]'),gap=e.target.closest('[data-capital-gap]'),tag=e.target.closest('[data-capital-label]'),rank=e.target.closest('[data-rank]');if(gap&&payload)applyCapitalPreset(payload.capital.coverage_gaps.find(b=>b.key===gap.dataset.capitalGap));else if(preset&&payload)applyCapitalPreset(preset.dataset.capital==='zero'?payload.capital.zero_demand:payload.capital.bands[Number(preset.dataset.capital)]);else if(tag)addLabel(Number(tag.dataset.capitalParent),Number(tag.dataset.capitalLabel));else if(rank&&payload){state.conditions=state.conditions.filter(c=>c.metric!=='small_category_rank').concat(payload.capital.ranks[Number(rank.dataset.rank)].condition);state.page=1;load();}};
  $('laQuick180').onclick=()=>{if(payload)applyCapitalPreset(payload.capital.bands[2]);};
  $('laTagCategories').onclick=e=>{const b=e.target.closest('[data-category]');if(b){state.overview_parent=Number(b.dataset.category);syncUrl();renderTagTable();}};
  $('laDetailGroup').onchange=()=>changeGroup($('laDetailGroup').value);
  document.querySelectorAll('[data-tab-set]').forEach(el=>el.onclick=e=>{const b=e.target.closest('[data-inventory-tab],[data-topic-tab]');if(b){if(b.dataset.inventoryTab)state.inventory_tab=b.dataset.inventoryTab;else state.topic_tab=b.dataset.topicTab;applyTabs();syncUrl();if(trendPayload)renderTrend();maybeLoadTrend();}});
  for(const id of ['laCapital','laTopics','laComparison','laSourcesPanel','laMoreFilters'])$(id).addEventListener('toggle',()=>{state.open_sections=['laCapital','laTopics','laComparison','laSourcesPanel','laMoreFilters'].filter(key=>$(key).open);syncUrl();if(trendPayload&&$('laTopics').open)renderTrend();maybeLoadTrend();});
  document.querySelectorAll('.la-nav a').forEach(a=>a.addEventListener('click',()=>{const target=$(a.hash.slice(1));if(target?.tagName==='DETAILS')target.open=true;}));
  $('laCapitalExport').onclick=()=>exportCsv('details',capitalColumns);
  $('laScope').addEventListener('submit',e=>{e.preventDefault();const view=$('laView').value,period=Number($('laPeriod').value),dt=$('laDate').value;if(view!==state.view||period!==state.period||dt!==state.data_date)state.version='';if(view!==state.view){state.conditions=state.conditions.filter(c=>c.kind!=='label'||meta.categories.find(x=>x.id===c.parent_id)?.scope!=='country');status('已移除不兼容的国家标签条件');}Object.assign(state,{view,period,data_date:dt,country_categories:[$('laCategory').value].filter(Boolean),countries:view==='country'?[$('laCountry').value].filter(Boolean):[],stores:[$('laStore').value].filter(Boolean),keyword:$('laKeyword').value,page:1,matrix_parents:[]});renderControls();load();});
  $('laView').onchange=()=>{$('laCountry').disabled=$('laView').value!=='country';};
  $('laRefresh').onclick=async()=>{try{state.version='';await load(true,true);meta=await api('meta');$('laDate').innerHTML=optionList(meta.dates,state.data_date);}catch(e){status(e.message,true);}};$('laBack').onclick=()=>{state.conditions.pop();state.page=1;load();};$('laReset').onclick=()=>{Object.assign(state,{conditions:[],country_categories:[],countries:[],stores:[],keyword:'',matrix_parents:[],page:1});$('laKeyword').value='';load();};
  $('laLabelParent').onchange=renderChildren;$('laAddLabel').onclick=()=>addLabel(Number($('laLabelParent').value),Number($('laLabelChild').value));
  $('laChips').onclick=e=>{const b=e.target.closest('[data-remove]');if(b){state.conditions.splice(Number(b.dataset.remove),1);state.page=1;load();}};
  $('laTagTable').onclick=e=>{const b=e.target.closest('[data-tag]');if(b){if(b.dataset.historyParent)addLabels([[Number(b.dataset.historyParent),Number(b.dataset.historyLabel)],[Number(b.dataset.tagParent),Number(b.dataset.tag)]],true);else addLabel(Number(b.dataset.tagParent),Number(b.dataset.tag));}};
  $('laMetricGroups').onclick=e=>{const b=e.target.closest('[data-group]');if(b)changeGroup(b.dataset.group);};
  $('laTagSearch').oninput=renderTagTable;
  $('laMetricFilterToggle').onclick=()=>{$('laMetricFilter').hidden=!$('laMetricFilter').hidden;};
  $('laAddMetric').onclick=()=>{const op=$('laFilterOp').value,raw=$('laFilterValue').value,upper=$('laFilterUpper').value;if(!['missing','present'].includes(op)&&raw===''){status('请填写指标阈值',true);return;}const c={kind:'metric',metric:$('laFilterMetric').value,op,value:['missing','present'].includes(op)?null:Number(raw)};if(op==='between'){if(upper===''||Number(upper)<c.value){status('区间上限不能小于下限',true);return;}c.upper=Number(upper);}state.conditions.push(c);state.page=1;load();};
  $('laCoverage').onclick=e=>{const b=e.target.closest('[data-coverage]');if(b){state.conditions.push(payload.coverage_distribution[Number(b.dataset.coverage)].condition);state.page=1;load();}};
  $('laStockout').onclick=e=>{const b=e.target.closest('[data-stockout-filter]');if(b){const current=b.dataset.stockoutFilter==='current';state.conditions.push({kind:'metric',metric:current?'ending_inventory_qty':'stockout_days',op:current?'eq':'gt',value:0});state.sort='stockout_days';$('laSort').value=state.sort;state.page=1;changeGroup('缺货');}};
  $('laStores').onclick=e=>{const b=e.target.closest('[data-store]');if(b){state.stores=[b.dataset.store];state.page=1;load();}};
  $('laMatrixApply').onclick=()=>{state.matrix_parents=[Number($('laMatrixA').value),Number($('laMatrixB').value)];load();};
  $('laMatrix').onclick=e=>{const b=e.target.closest('[data-matrix]');if(b){const ids=b.dataset.matrix.split(',').map(Number);state.matrix_parents.forEach((p,i)=>{const found=state.conditions.find(c=>c.kind==='label'&&c.parent_id===p);if(found)found.ids=[ids[i]];else state.conditions.push({kind:'label',parent_id:p,ids:[ids[i]]});});state.page=1;load();}};
  $('laSort').onchange=()=>{state.sort=$('laSort').value;state.page=1;syncUrl();loadDetails();};$('laDirection').onclick=()=>{state.descending=!state.descending;$('laDirection').textContent=state.descending?'降序 ↓':'升序 ↑';loadDetails();};$('laPageSize').onchange=()=>{state.page_size=Number($('laPageSize').value);state.page=1;loadDetails();};$('laPrev').onclick=()=>{state.page--;syncUrl();loadDetails();};$('laNext').onclick=()=>{state.page++;syncUrl();loadDetails();};
  $('laDetailTable').onclick=e=>{const b=e.target.closest('[data-object]');if(b)openObject(b.dataset.object);};
  $('laCatalogOpen').onclick=$('laCustomEdit').onclick=openCatalog;$('laCatalogClose').onclick=$('laCatalogCancel').onclick=()=>$('laCatalog').close();$('laDrawerClose').onclick=()=>{drawerRequest++;$('laDrawer').close();};$('laDrawer').addEventListener('close',()=>{drawerRequest++;});$('laDrawer').addEventListener('cancel',()=>{drawerRequest++;});$('laMetricSearch').oninput=renderCatalog;
  $('laDrawerBody').onclick=e=>{const button=e.target.closest('[data-drawer-tab]');if(button&&drawerProduct&&drawerSections.some(t=>t.id===button.dataset.drawerTab)){drawerTab=button.dataset.drawerTab;renderDrawer();$('laDrawerBody').scrollTop=0;$('laDrawerBody').querySelector('.la-product-tabs [data-drawer-tab="'+drawerTab+'"]').focus({preventScroll:true});}};
  $('laCatalogGroups').onclick=e=>{const b=e.target.closest('[data-catalog-group]');if(b){catalogGroup=b.dataset.catalogGroup;renderCatalog();$('laCatalogGroups').querySelector('[aria-pressed="true"]').focus({preventScroll:true});}};
  $('laCatalogSelectedOnly').onchange=renderCatalog;
  $('laCatalogSelectAll').onchange=e=>{const visible=Array.from($('laCatalogList').querySelectorAll('[data-column]:not(:disabled)'),input=>input.dataset.column);catalogDraft=e.target.checked?[...new Set([...catalogDraft,...visible])]:catalogDraft.filter(k=>!visible.includes(k));renderCatalog();};
  $('laClearColumns').onclick=()=>{catalogDraft=[];renderCatalog();};
  $('laCatalogList').onchange=e=>{const k=e.target.dataset.column;if(k&&metrics[k]?.available){catalogDraft=e.target.checked?[...new Set([...catalogDraft,k])]:catalogDraft.filter(x=>x!==k);e.target.closest('.la-catalog-item').classList.toggle('selected',e.target.checked);if($('laCatalogSelectedOnly').checked)renderCatalog();else catalogCount();}};
  $('laSaveColumns').onclick=()=>{custom=[...catalogDraft];try{localStorage.setItem('label-analysis-columns-v1',JSON.stringify(custom));}catch(_){}$('laCatalog').close();changeGroup('自定义');};
  $('laLoadTrends').onclick=()=>loadTrends();$('laTrendMetric').onchange=renderTrend;$('laExport').onclick=()=>exportCsv('details');$('laExportSummary').onclick=()=>exportCsv('summary');
  window.addEventListener('resize',resizeTrend);
  if(window.ResizeObserver)new ResizeObserver(resizeTrend).observe($('laTrend'));
  async function init(){try{meta=await api('meta');meta.metrics=meta.metrics.map(m=>{const wording=metricWording[m.id];if(wording)exportMetricNames[m.label]=wording.label;return {...m,label:wording?.label||m.label,formula:wording?.formula||m.formula.replaceAll('对象日','商品、同一天'),source:m.source.replaceAll('逐对象自然日日历','每个商品每日记录')};});metrics=Object.fromEntries(meta.metrics.map(m=>[m.id,m]));custom=custom.filter(k=>metrics[k]);if(!meta.dates.includes(state.data_date)&&(!state.version||!state.data_date)){state.data_date=meta.dates[0];state.version='';}$('laDate').innerHTML=optionList([...new Set([...meta.dates,state.data_date].filter(Boolean))],state.data_date);$('laPeriod').value=state.period;$('laView').value=state.view;$('laKeyword').value=state.keyword;$('laPageSize').value=state.page_size;$('laDirection').textContent=state.descending?'降序 ↓':'升序 ↑';restoreSections();
    const groups=['全部','库存资金专项',...new Set(meta.metrics.map(m=>m.group).filter(g=>g!=='规模'&&g!=='标签变更（待接入）')),'自定义'];if(!groups.includes(group))group='经营';state.column_group=group;$('laDetailGroup').innerHTML=optionList(groups.map(id=>({id,label:groupLabel(id)})),group);$('laMetricGroups').innerHTML=groups.map(g=>'<button type="button" data-group="'+esc(g)+'" class="'+(g===group?'active':'')+'">'+esc(groupLabel(g))+'</button>').join('');
    const ready=meta.metrics.filter(m=>m.available&&!omittedColumns.has(m.id));if(omittedColumns.has(state.sort))state.sort='sales_amount';$('laSort').innerHTML=optionList(ready.filter(m=>m.filterable).map(m=>({id:m.id,label:m.label})),state.sort);$('laFilterMetric').innerHTML=optionList(ready.filter(m=>m.filterable).map(m=>({id:m.id,label:m.label})),'fba_coverage_days');$('laTrendMetric').innerHTML=optionList(ready.filter(m=>m.trend).map(m=>({id:m.id,label:m.label})),'sales_amount');renderControls();await load();
  }catch(e){status(e.message,true);pendingModules('读取失败：'+e.message+'。请刷新页面重试。',true);}}
  pendingModules('正在读取指标目录与分析数据…');
  init();
})();

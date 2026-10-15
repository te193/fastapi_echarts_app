(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('strategyFilters');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (value, digits=2) => value == null ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits:digits});
  const pct = value => value == null ? '—' : `${num(value*100,1)}%`;
  const money = (value, currency='') => value == null ? '金额待核' : `${num(value,2)} ${esc(currency || '')}`;
  const exitName = value => ({tracking:'未退出',early:'D7提前退出',normal:'常规达标退出'}[value] || value);
  const statusName = value => ({ready:'条件已满足',pending:'待核建议',blocked:'暂不调整',hold:'保持'}[value] || value);
  const observationText = row => row.exit_status==='tracking' && row.age>=1 && row.age<=7 ? '处于观察期，暂不进行人工干预' : null;
  const badge = (label, tone) => `<span class="rgs-badge ${esc(tone)}">${esc(label)}</span>`;
  const stateNames={observe:'自然观察',good:'恢复较好',improving:'改善中',poor:'恢复不足',sales_repair:'销量修复',risk:'利润风险',unknown:'旧快照数据不足',history_missing:'历史数据不足',history_zero:'历史零销量',data_missing:'返场经营数据缺失',stock_missing:'库存数据缺失',stock_interrupted:'库存中断',no_sales:'当前评价窗口无销量',profit_unknown:'利润无法评价'};
  let batchId=null, recommendation='all', activeCard='tracking', focus='all', gridApi, controller, detailController, opener;

  function ensureGrid() {
    if(gridApi) return;
    const cell=(main,sub='')=>`<div class="rgs-grid-cell">${main}${sub?`<small>${sub}</small>`:''}</div>`;
    gridApi=window.kanbanGrid?.makeGrid('strategyGrid',{
      domLayout:'normal',rowHeight:98,pagination:true,paginationPageSize:50,paginationPageSizeSelector:[20,50,100,200],
      suppressCellFocus:false,getRowId:p=>p.data.event_id,
      defaultColDef:{sortable:true,filter:true,resizable:true,minWidth:110,wrapHeaderText:true,autoHeaderHeight:true},
      overlayNoRowsTemplate:'<span class="ag-empty-copy">当前筛选没有商品。可切换条件或清除筛选。</span>',
      onFilterChanged:()=>{if(gridApi)$('strategySelection').textContent=`表内筛选后 ${num(gridApi.getDisplayedRowCount(),0)} 个商品 · 列筛选作用于当前查询的全部商品`;},
      columnDefs:[
        {field:'msku',headerName:'商品 / 店铺',width:220,pinned:'left',filterValueGetter:p=>`${p.data.msku} ${p.data.seller_name_new} ${p.data.local_sku || ''}`,
          cellRenderer:p=>cell(`<strong>${esc(p.data.msku)}</strong>`,`${esc(p.data.seller_name_new)} · ${esc(p.data.country_category)}<br>${esc(p.data.local_sku || '')}`)},
        {colId:'age',headerName:'返场进度',width:180,filter:'agNumberColumnFilter',valueGetter:p=>p.data.exit_status==='tracking'?p.data.age:Math.round((Date.parse(p.data.exit_date)-Date.parse(p.data.return_date))/86400000)+1,
          cellRenderer:p=>cell(`<strong>${p.data.exit_status==='tracking'?'':'退出时'}D${p.value}</strong> · ${p.data.exit_status==='tracking'?(p.data.age<=7?'观察期':'干预期'):'本轮已结束'}`,`返场 ${esc(p.data.return_date)}<br>可售 ${num(p.data.current_stock,0)} 件`)},
        {field:'intervention_label',headerName:'恢复决策',width:180,valueGetter:p=>p.data.state==='no_sales'?p.data.state_label:p.data.intervention_label,cellRenderer:p=>p.data.state==='no_sales'?cell(esc(p.value),p.data.no_sales_scope==='since_return'?`完整返场${p.data.age}天记录`:p.data.no_sales_previous_sales?'返场后曾有销量':'仅指当前评价窗口'):cell(esc(p.value))},
        {field:'recovery',headerName:'销量恢复率',headerTooltip:'按百分数筛选，例如输入80表示80%',width:190,filter:'agNumberColumnFilter',valueGetter:p=>p.data.recovery==null?null:p.data.recovery*100,cellRenderer:p=>cell(`<strong>${pct(p.data.recovery)}</strong>`,`历史 ${num(p.data.historical_daily)} → 近${p.data.recent_days || 7}天 ${num(p.data.recent_daily)} 件/天`)},
        {field:'margin',headerName:'订单毛利率',headerTooltip:'按百分数筛选，例如输入5表示5%',width:155,filter:'agNumberColumnFilter',valueGetter:p=>p.data.margin==null?null:p.data.margin*100,cellRenderer:p=>cell(`<strong>${pct(p.data.margin)}</strong>`,`近${p.data.recent_days || 7}天角色：${esc(p.data.role)}`)},
        {colId:'trend7',headerName:'近7天变化提示',width:245,sortable:false,filter:false,cellRenderer:p=>{const t=p.data.trend7;return cell(t?`日销 ${num(t.current.daily)} 件/天 · 毛利率 ${pct(t.current.margin)}`:'旧快照未保存',t?`较前7天日销 ${pct(t.daily_change)} · 毛利率变化 ${t.margin_change==null?'—':num(t.margin_change*100,1)+'个百分点'}${t.warning?'<br>'+esc(t.warning):''}`:'');}},
        {field:'state_label',headerName:'经营判断',width:245,tooltipField:'state_reason',cellRenderer:p=>cell(badge(p.value,p.data.state),esc(p.data.state_reason))},
        {field:'ad_result_label',headerName:'广告判断结果',width:185,valueGetter:p=>observationText(p.data) || p.data.ad_result_label,cellRenderer:p=>cell(esc(p.value || '本批次未保存广告判断'))},
        {colId:'exit',headerName:'退出情况 / 原因',width:270,valueGetter:p=>exitName(p.data.exit_status),tooltipValueGetter:p=>p.data.exit_reasons.join('；'),
          cellRenderer:p=>cell(badge(p.value,p.data.exit_status),`${p.data.exit_target?`目标：至少${esc(p.data.exit_target)}<br>`:''}${esc(p.data.exit_date || p.data.exit_reasons[0])}${p.data.exit_reasons.length>1&&p.data.exit_status==='tracking'?`<br>另有 ${p.data.exit_reasons.length-1} 项，详情查看`:''}`)},
        {field:'suggestion_summary',headerName:'建议怎么处理',width:190,valueGetter:p=>observationText(p.data) || p.data.suggestion_summary,cellRenderer:p=>cell(`<strong>${esc(p.value)}</strong>`,observationText(p.data)?'':`${p.data.ready_count?`条件满足 ${p.data.ready_count} 条 `:''}${p.data.pending_count?`待核 ${p.data.pending_count} 条`:''}`)},
        {colId:'detail',headerName:'明细',width:145,pinned:'right',sortable:false,filter:false,cellRenderer:p=>`<button type="button" class="rgs-link" data-event="${esc(p.data.event_id)}">查看原因与建议</button>`}
      ]
    });
    if(!gridApi) throw new Error('AG Grid组件加载失败，请刷新页面重试');
  }

  function renderIntervention(cards, diagnostics, reasonGroups) {
    const visible=['all','tracking'].includes(form.elements.exit_status.value)&&!['observe','early','normal'].includes(form.elements.stage.value);
    $('strategyIntervention').hidden=!visible;
    const byKey=Object.fromEntries((cards || []).map(c=>[c.key,c]));
    const button=key=>{const c=byKey[key];return c?`<button type="button" data-focus="${key}" class="${focus===key?'active':''}" aria-pressed="${focus===key}" title="${esc(c.description)}"><span>${esc(c.label)}</span><strong>${num(c.count,0)}<small> 个</small></strong></button>`:'';};
    const categories=['good','improving','poor','sales_repair','risk','history_missing','history_zero','no_sales_since_return','no_sales_window','data_missing','stock_missing','stock_interrupted','profit_unknown','unknown'].filter(k=>['good','improving','poor'].includes(k)||byKey[k]?.count>0);
    const total=categories.reduce((sum,k)=>sum+(byKey[k]?.count||0),0);
    const steps=[['1','判断自然恢复情况',`共 ${total} 个干预期商品，以下分类不重复、可相加。日销不足1件先修复销量；达到1件再判断利润。恢复不足先检查广告。`,categories],
      ['2','广告判断结果与调整建议','系统先判断广告，再给出处理结果。无法判断的商品单独说明缺失数据，不视为广告正常。',['ad_adjust','ad_hold','ad_no_need','ad_limited','ad_unknown']],
      ['3','广告判断后，决定价格怎么调','有适用广告动作，优先处理广告；没有适用动作或只缺广告专属数据，独立审核价格。仍须通过价格自身条件。',['price_up_review','price_down_review','price_wait_ad']]];
    const openKeys=new Set([...$('strategyInterventionCards').querySelectorAll('details[open][data-reason-panel]')].map(d=>d.dataset.reasonPanel));
    const reasons=category=>`<details class="rgs-ad-reasons" data-reason-panel="${category}" ${openKeys.has(category)?'open':''}><summary>${category==='limited'?'受限':'无法判断'}原因</summary><p>点击原因筛选下方商品表格。同一商品可能有多个原因，各原因数量不相加。</p>${(reasonGroups||[]).filter(g=>g.category===category).map(g=>`<section class="rgs-ad-reason"><button type="button" data-focus="${esc(g.key)}" class="${focus===g.key?'active':''}"><span>${esc(g.reason)}</span><strong>${num(g.count,0)}<small> 个</small></strong></button></section>`).join('')||'<p>当前筛选没有对应商品。</p>'}</details>`;
    $('strategyInterventionCards').innerHTML=steps.map(([n,title,note,keys])=>`<section class="rgs-decision-step"><h3><b>${n}</b>${title}</h3><p>${note}</p><div>${keys.map(k=>button(k)+(k==='ad_limited'?reasons('limited'):k==='ad_unknown'?reasons('unknown'):'')).join('')}</div>${n==='3'?'<p class="rgs-decision-limit">一轮只调一档 · 最低P10 · 涨价最高P35</p><p>降价看本站返场N／21／30天窗口：给够断货前卖3件所需的访问机会，实际销量仍低于预期70%才审核降档；不固定50次。</p>':''}</section>`).join('');
    $('strategyInterventionCards').querySelectorAll('.rgs-decision-step')[1].insertAdjacentHTML('beforeend',`<p>仅判断德国、法国、意大利、西班牙、荷兰、英国、美国；各国家独立给出建议。</p><p>具体广告调整（可点击查看对象和金额）</p><div>${['start_ad','restore','bid_up','bid_down','budget'].map(button).join('')}</div>`);
    $('strategyDecisionNotes').innerHTML=`<details><summary>为什么很多商品只有“检查广告”，没有竞价调整？</summary><p>以下按商品统计；一个商品可以在不同站点遇到多种情况，数量不相加。</p>${(diagnostics||[]).map(d=>`<p>${esc(d.reason)}：${num(d.count,0)} 个商品</p>`).join('')}</details>`;
  }

  function options(name, values, caption) {
    const select=form.elements[name], old=select.value;
    select.innerHTML=`<option value="all">${caption}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
    select.value=values.includes(old)?old:'all';
  }

  function renderDistribution(d) {
    const counts=d.counts || {},tracked=(counts.observe || 0)+(counts.intervene || 0),exited=(counts.early || 0)+(counts.normal || 0);
    const groups=[['tracking','跟踪中',tracked,[['observe','观察期','D1—D7 · 自然恢复'],['intervene','干预期','D8起 · 按表现决定是否调整']]],
      ['exited','已退出',exited,[['early','表现稳定提前退出','D7 · 每天及整体达标'],['normal','常规达标退出','最早D10 · 对应窗口角色连续3天达标']]]];
    $('strategyStages').innerHTML=groups.map(([group,label,total,stages])=>`<div class="rgs-stage-group ${group}">
      <button type="button" data-summary="${group}" class="rgs-group-heading"><span>${label}</span><strong>${num(total,0)}</strong><small>个商品</small><span class="rgs-group-link">查看全部 →</span></button>
      <div class="rgs-stage-options">${stages.map(([key,title,note])=>`<button type="button" data-stage="${key}" aria-pressed="${form.elements.stage.value===key}" class="${form.elements.stage.value===key?'active':''}"><span>${title}</span><strong>${num(counts[key] || 0,0)}<small> 个</small></strong><small>${note}</small></button>`).join('')}</div>
    </div>`).join('');
    $('strategyDistributions').innerHTML=['observe','intervene'].map(stage=>{
      const days=(d.days || []).filter(row=>row.stage===stage),total=counts[stage] || 0;
      return `<div class="rgs-distribution-panel"><h3>${stage==='observe'?'观察期':'干预期'}内的分布 <small>${num(total,0)} 个未退出商品</small></h3>
        <p>${stage==='observe'?'逐日查看D1—D7；D7稳定达标后可提前退出。':'按返场天数分段；进入干预期不代表一定要调价或加投。'}</p>
        <div class="rgs-day-bands">${days.map(row=>`<button type="button" data-stage="${stage}" data-band="${row.key}" aria-pressed="${form.elements.age_band.value===row.key}" class="${form.elements.age_band.value===row.key?'active':''}"><span>${row.label}</span><strong>${num(row.count,0)} <small>个</small></strong><span class="rgs-band-track"><i style="width:${total?row.count/total*100:0}%"></i></span><small>占本期 ${total?pct(row.count/total):'—'}</small></button>`).join('')}</div>
        <div class="rgs-state-counts"><span>经营判断</span>${Object.entries(d.states?.[stage] || {}).filter(([,count])=>count>0).map(([state,count])=>`<button type="button" data-stage="${stage}" data-state="${state}">${stateNames[state]} <b>${num(count,0)}</b></button>`).join('') || '<span>本期暂无商品</span>'}</div></div>`;
    }).join('');
  }

  async function load() {
    controller?.abort(); controller=new AbortController();
    const thisController=controller;
    const params=new URLSearchParams(new FormData(form));
    params.set('all_rows','true');params.set('recommendation',recommendation);params.set('focus',focus);
    $('strategyTable').setAttribute('aria-busy','true');
    try {
      ensureGrid();gridApi.setGridOption('loading',true);
      const res=await fetch(`/api/return-goods-strategy?${params}`,{signal:thisController.signal});
      if(!res.ok) throw new Error('读取失败，请稍后重试');
      const data=await res.json();
      if(thisController!==controller) return;
      const meta=data.meta || {};batchId=meta.batch_id;
      $('strategyMeta').textContent=meta.data_date?`经营数据截至 ${meta.data_date}${meta.settings_date?` · 设置读取截至 ${meta.settings_date}`:''} · 新版规则试算 · 每个商品仅显示最新返场轮次`:'尚无完整成功快照';
      const warnings=meta.warnings || [];
      $('strategyWarnings').hidden=!warnings.length;
      $('strategyWarnings').querySelector('summary').textContent=`数据说明 · ${warnings.length}项待关注`;
      $('strategyWarnings').querySelector('ul').innerHTML=warnings.map(w=>`<li>${esc(w)}</li>`).join('');
      options('country_category',data.options.countries,'全部国家类别');options('seller_name_new',data.options.stores,'全部店铺');
      renderDistribution(data.distribution || {});
      renderIntervention(data.intervention || [],data.ad_diagnostics || [],data.ad_reason_groups || []);
      document.querySelectorAll('[data-summary]').forEach(btn=>{
        btn.querySelector('strong').textContent=num(data.summary[btn.dataset.summary],0);
        btn.classList.toggle('active',btn.dataset.summary===activeCard);
        btn.setAttribute('aria-pressed',String(btn.dataset.summary===activeCard));
      });
      $('strategyClearAdvice').classList.toggle('active',recommendation==='all');
      $('strategyClearAdvice').setAttribute('aria-pressed',String(recommendation==='all'));
      if(form.elements.age_band.value!=='all') $('strategyDistributionDetails').open=true;
      $('strategyCount').textContent=`当前筛选 ${num(data.total,0)} 个商品`;
      gridApi.setFilterModel(null);gridApi.setGridOption('rowData',data.items);gridApi.paginationGoToFirstPage();
      $('strategySelection').textContent=`已加载 ${num(data.total,0)} 个商品 · 排序和列筛选作用于全部查询结果`;
    } catch(e) {
      if(e.name==='AbortError') return;
      gridApi?.setGridOption('rowData',[]);$('strategySelection').textContent=`${e.message}。点击“查询”重试。`;
      $('strategyMeta').textContent='本次加载失败，未展示不完整结果';
    } finally {
      if(thisController===controller) {gridApi?.setGridOption('loading',false);$('strategyTable').setAttribute('aria-busy','false');}
    }
  }

  function mini(label, value) { return `<div><small>${esc(label)}</small><strong>${value}</strong></div>`; }
  function pricePosition(amount,ladder) {
    const entries=Object.entries(ladder || {}).filter(([,v])=>v!=null).sort((a,b)=>Number(a[1])-Number(b[1]));
    if(amount==null || entries.length!==6) return '档位待核';
    const exact=entries.find(([,v])=>Math.abs(Number(v)-Number(amount))<.000001);
    if(exact) return exact[0].toUpperCase();
    if(amount<entries[0][1]) return '低于P10';
    if(amount>entries.at(-1)[1]) return '高于P35';
    const upper=entries.findIndex(([,v])=>v>amount);
    return `${entries[upper-1][0].toUpperCase()}—${entries[upper][0].toUpperCase()}之间`;
  }
  function actionCard(s,ladder) {
    const concrete=s.target!=null;
    const name=s.kind==='ad'?(s.object_text || s.ad_group || ''):'';
    return `<article class="rgs-action ${esc(s.status)}">
      <div class="rgs-action-title">${badge(s.deferred&&s.status!=='blocked'?'优先处理广告':statusName(s.status),s.status)}<strong>${esc(s.label)}${s.deferred&&s.action.startsWith('price_')?'候选':''}</strong>${name?`<span>${esc(name)}</span>`:''}</div>
      ${s.deferred?`<p><strong>${esc(s.defer_reason)}。价格试算保留供后续审核。</strong></p>`:''}
      ${concrete?`<div class="rgs-value">${money(s.current,s.currency)} ${s.kind==='price'?`<span class="rgs-badge">${esc(pricePosition(s.current,ladder))}</span>`:''} → ${money(s.target,s.currency)} ${s.tier?`<span class="rgs-badge">${esc(s.tier)}</span>`:''}</div><p>实际变化 ${pct(s.current?s.target/s.current-1:null)}${s.status==='pending'?' · 候选金额，以下条件尚未核实':''}</p>`:''}
      ${s.action==='restore'?'<p>当前有暂停层级 → 核实后恢复原投放设置</p>':''}
      <p>${esc(s.reason)}</p>
      ${s.profit_policy?`<p>${esc(s.profit_policy)}</p>`:''}
      ${s.price_risk_note?`<p>${esc(s.price_risk_note)}</p>`:''}
      ${(s.checks || []).length?`<ul>${s.checks.map(c=>`<li>${esc(c)}</li>`).join('')}</ul>`:''}
      ${s.kind==='ad'&&s.campaign?`<p class="rgs-source">${esc(s.campaign)} / ${esc(s.ad_group)} · 对象 ${esc(s.object_id)}</p>`:''}
      ${s.stats?.mature?`<p class="rgs-source">返场后已归因数据 ${esc(s.stats.mature_start)} 至 ${esc(s.stats.mature_end)}：${num(s.stats.clicks,0)} 次点击 / ${num(s.stats.orders,0)} 单 / 花费 ${money(s.stats.cost,s.currency)}</p>`:''}
      ${s.source_date?`<p class="rgs-source">设置或价格日期：${esc(s.source_date)}</p>`:''}
      ${s.target_source_date?`<p class="rgs-source">自动匹配方式同步日期：${esc(s.target_source_date)}（竞价及状态来自该次同步）</p>`:''}
      ${s.last_change_date?`<p class="rgs-source">已核对的最近调价日期：${esc(s.last_change_date)}</p>`:''}
    </article>`;
  }

  function sparkline(rows) {
    const values=rows.map(r=>r.qty),max=Math.max(1,...values.filter(v=>v!=null));
    const segments=[];let current=[];
    values.forEach((v,i)=>{if(v==null){if(current.length) segments.push(current);current=[];}else current.push(`${8+i*744/Math.max(1,values.length-1)},${76-v/max*65}`);});
    if(current.length)segments.push(current);
    return `<svg class="rgs-chart" viewBox="0 0 760 85" role="img" aria-label="本轮每日销量趋势，缺失日期断开">${segments.map(s=>`<polyline points="${s.join(' ')}" fill="none" stroke="#407bbd" stroke-width="2"/>`).join('')}</svg><div class="rgs-chart-caption">每日销量 · ${esc(rows[0]?.day || '')} 至 ${esc(rows.at(-1)?.day || '')} · 缺失日期留空</div>`;
  }

  function historyComparison(d) {
    const before=d.pre_stockout,baseline=d.comparison?(d.comparison.history || {}):d.baseline,after=d.comparison?.current || d.recent;
    if(!before) return '<p class="rgs-source">本批次尚未保存断货前表现明细，请更新策略快照后查看。</p>';
    const perDay=(m,key)=>m?.[key]!=null&&m?.days?m[key]/m.days:null;
    const marginText=m=>m?.margin!=null?pct(m.margin):m?.revenue===0?'不可计算（销售额为0）':m?.revenue<0?'不可计算（销售额为负）':'缺少完整数据';
    const conversion=m=>m?.qty!=null&&m?.sessions>0?pct(m.qty/m.sessions):m?.sessions===0?'不可计算（Sessions为0）':'缺少流量数据';
    const columns=[before,baseline,after];
    const rows=[['累计销量',m=>num(m?.qty)],['日均销量',m=>num(m?.daily)],['订单毛利率',marginText],
      ['日均订单毛利额',m=>num(perDay(m,'profit'))],['销售额合计',m=>num(m?.revenue)],['订单毛利额合计',m=>num(m?.profit)],
      ['Sessions合计',m=>num(m?.sessions,0)],['日均Sessions',m=>num(perDay(m,'sessions'))],['销量 / Sessions',conversion],['销售角色',m=>esc(m?.role || '不可判')]];
    const missing=new Set([...(before.missing || []),...(before.stock_missing || [])]).size;
    return `<div class="rgs-history" id="strategyHistory"><h4>断货前表现与返场后对比</h4>
      <p>断货前实际记录：${esc(before.start)} 至 ${esc(before.end)}，${before.days}天；${missing?`有${missing}天数据不完整`:'数据完整'}${before.stock_missing?.length?'，库存记录不完整':before.zero_days?.length?`，其中${before.zero_days.length}天无可售库存`:'，每天有可售库存'}。</p>
      <div class="rgs-history-note">销量比较：${d.comparison?`${d.comparison.days}天对${d.comparison.days}天；`:''}${esc(d.comparison&&!d.comparison.history?'没有对应有效历史销量窗口':baseline.evidence)}${baseline.start?`，历史来源 ${esc(baseline.start)} 至 ${esc(baseline.end)}`:''}。${d.recovery==null?'当前不能计算销量恢复率，不能把它当成恢复0%。':''}<br>历史角色基准独立保存：${esc(d.baseline.evidence)}。</div>
      <div class="rgs-history-scroll"><table><thead><tr><th>指标</th><th>断货前30天实际表现<small>${esc(before.start)} 至 ${esc(before.end)}</small></th><th>用于恢复率的有效历史基准<small>${baseline.start?`${esc(baseline.start)} 至 ${esc(baseline.end)} · ${baseline.days}天`:'未形成有效基准'}</small></th><th>返场近${after.days}天表现<small>${esc(after.start)} 至 ${esc(after.end)}</small></th></tr></thead><tbody>${rows.map(([label,format])=>`<tr data-history-metric="${esc(label)}"><td>${label}</td>${columns.map(m=>`<td>${m?.start?format(m):'未形成有效基准'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <p class="rgs-source">D1—D21按返场N天对历史N天，D22—D29比较21天，D30起比较30天。销量与利润分别计算；0表示有记录且为0，缺失不填0。销量历史窗口不要求毛利率可计算；退出仍使用独立角色规则。</p>
      ${d.pre_stockout_timeline?.length?`<details class="rgs-history-days"><summary>查看断货前30天每日库存与表现</summary><div class="rgs-timeline"><table><thead><tr><th>日期</th><th>FBA可售</th><th>销量</th><th>订单毛利率</th><th>当日角色</th></tr></thead><tbody>${d.pre_stockout_timeline.map(r=>`<tr><td>${esc(r.day)}</td><td>${num(r.stock,0)}</td><td>${num(r.qty,0)}</td><td>${pct(r.margin)}</td><td>${esc(r.role)}${r.complete?'':' · 缺数'}</td></tr>`).join('')}</tbody></table></div></details>`:''}
    </div>`;
  }

  async function openDetail(eventId,button) {
    opener=button;detailController?.abort();detailController=new AbortController();
    const thisController=detailController;
    $('strategyDrawer').hidden=false;$('strategyMask').hidden=false;document.body.style.overflow='hidden';
    $('strategyDetailTitle').textContent='商品详情';$('strategyDetail').innerHTML='<p>正在读取本批次商品详情…</p>';$('strategyClose').focus();
    try {
      const res=await fetch(`/api/return-goods-strategy/detail?${new URLSearchParams({event_id:eventId,batch_id:batchId})}`,{signal:thisController.signal});
      if(!res.ok) throw new Error('详情读取失败，请关闭后重试');
      const d=await res.json();if(thisController!==detailController) return;
      $('strategyDetailTitle').textContent=`${d.msku} · ${d.seller_name_new}`;
      const b=d.baseline,m=d.exit_evidence || d.current_evaluation || d.current14 || d.recent;
      $('strategyDetail').innerHTML=`
        <section class="rgs-detail-section"><h3>1. ${d.exit_status==='tracking'?'为什么还没退出':'本轮已达标退出'}</h3>
          ${badge(exitName(d.exit_status),d.exit_status)} ${d.exit_date?`<strong>${esc(d.exit_date)}</strong>`:`<strong> D${d.age} · ${esc(d.phase)}</strong>`}
          <ul class="rgs-reasons">${d.exit_reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>
          <p class="rgs-source">退出评价使用 ${esc(m?.start || '—')} 至 ${esc(m?.end || '—')} 的 ${esc(m?.days || '—')} 天数据。</p>
          <div class="rgs-mini-grid">${mini('评价日销',`${num(m?.daily)} 件`)}${mini('订单毛利率',pct(m?.margin))}${mini('评价角色',esc(m?.role || '不可判'))}${mini('连续达标',d.exit_status==='early'?'7天每日稳定':`${d.confirmation_days} / 3天`)}</div>
          <p><strong>断货前角色：${esc(b.role)}；本轮退出目标：至少${esc(d.exit_target || '潜力')}。</strong></p>
          <p class="rgs-source">原问题、瘦狗或历史不可判，至少达到瘦狗；原潜力、明星，至少达到潜力。D7提前退出要求每天及7天整体达到本轮目标；常规退出从D8起，D8—D21按返场N天、D22—D29按最近21天、D30起按最近30天评价角色，连续3天达到本轮目标，最早D10。销量恢复率不作为退出门槛。</p>
          ${d.exit_confirmation?.length?`<p class="rgs-source">连续确认：${d.exit_confirmation.map(v=>`${esc(v.end)} · ${v.days}天窗口 · ${esc(v.role)}`).join('；')}。</p>`:''}
        </section>
        <section class="rgs-detail-section"><h3>2. 建议怎么调、调多少</h3><p>${esc(d.comparison?.days || d.recent.days)}天恢复判断：${esc(d.state_reason)}</p>
          <p class="rgs-source">${esc(d.dos_note)} · 参考库存覆盖 ${num(d.dos)} 天。候选金额不代表已执行，也不代表所有条件已通过。</p>
          ${(d.countries || []).map((c,i)=>`<details class="rgs-country" ${i===0?'open':''}><summary>${esc(c.country)} · ${c.suggestions.filter(s=>s.status==='pending').length} 条待核</summary>
            <div class="rgs-mini-grid">${mini('当前价格',money(c.listing.price,c.listing.currency))}${mini('近7天日销',num(c.recent.daily))}${mini('订单毛利率',pct(c.recent.margin))}${mini('近7天Sessions',num(c.recent.sessions,0))}</div>
            <div class="rgs-tier-list">${Object.entries(c.ladder).map(([k,v])=>`<span class="rgs-tier">${esc(k.toUpperCase())} · ${num(v)}</span>`).join('')}</div>
            <p class="rgs-source">价格档位日期 ${esc(c.ladder_date || '缺失')} · 月配置预算 ${money(c.budget.monthly_ad_budget_original,c.budget.currency_code)} / 周配置预算 ${money(c.budget.weekly_ad_budget_original,c.budget.currency_code)}；可分配余额待核。</p>
            <h4>广告判断及处理</h4>${c.suggestions.filter(s=>s.kind==='ad').map(s=>actionCard(s,c.ladder)).join('') || '<p>本轮没有具体广告调整建议，经营或库存限制见上方说明。</p>'}
            <h4>价格判断</h4><p>广告专属数据缺失不会单独阻止价格审核；未命中价格条件则保持，价格受限则显示具体原因。实际广告操作记录仍待核，不据此声称广告正常或已完成复评。</p>${c.suggestions.filter(s=>s.kind!=='ad'&&!s.deferred).map(s=>actionCard(s,c.ladder)).join('')}
            ${c.suggestions.some(s=>s.deferred)?`<p>该站点已有具体广告建议，当前优先处理广告。下方价格仅为后续试算，不代表广告已执行或已进入复评。</p><details><summary>查看后续价格试算</summary>${c.suggestions.filter(s=>s.deferred).map(s=>actionCard(s,c.ladder)).join('')}</details>`:''}</details>`).join('') || '<p>暂无可核实的国家站点记录。</p>'}
        </section>
        <section class="rgs-detail-section"><h3>3. 断货前表现与本轮恢复</h3>
          <div class="rgs-mini-grid">${mini('连续断货首日',esc(d.stockout_date))}${mini('库存恢复 / D1',esc(d.return_date))}${mini('同长度历史日销',num(d.comparison?d.comparison.history?.daily:b.daily))}${mini(`${d.comparison?.days || 7}天销量恢复率`,pct(d.recovery))}</div>
          ${d.comparison?`<p>情况明细：${d.comparison.issues.map(k=>esc(stateNames[k])).join('；') || '比较窗口数据完整'}。</p><p>窗口内最长连续0库存：${num(d.comparison.current.max_zero_stock_days,0)} 天；连续至少3天才归为库存中断。</p><p class="rgs-source">缺销量日期：${esc(d.comparison.current.sales_missing.join('、') || '无')}；缺销售额或毛利日期：${esc((d.comparison.current.finance_missing || []).join('、') || '无')}；缺库存日期：${esc(d.comparison.current.stock_missing.join('、') || '无')}；无可售库存日期：${esc(d.comparison.current.zero_days.join('、') || '无')}。</p>`:''}
          ${d.trend7?`<h4>近7天变化提示</h4><p>日销 ${num(d.trend7.current.daily)} 件/天，订单毛利率 ${pct(d.trend7.current.margin)}；较前7天日销变化 ${pct(d.trend7.daily_change)}，毛利率变化 ${d.trend7.margin_change==null?'—':num(d.trend7.margin_change*100,1)+'个百分点'}。</p><p class="rgs-source">${esc(d.trend7.warning || (d.trend7.previous?'未发现日销或毛利率下降':'尚未形成返场后两个完整7天窗口'))}。短期提示不代替主窗口恢复判断，不自动触发调整。</p>`:''}
          ${historyComparison(d)}
          <h4 class="rgs-recovery-title">返场后的每日表现</h4>
          ${sparkline(d.timeline)}
          <div class="rgs-timeline"><table><thead><tr><th>日期</th><th>FBA可售</th><th>销量</th><th>订单毛利率</th><th>当日角色</th></tr></thead><tbody>${d.timeline.map(r=>`<tr><td>${esc(r.day)}</td><td>${num(r.stock,0)}</td><td>${num(r.qty,0)}</td><td>${pct(r.margin)}</td><td>${esc(r.role)}${r.complete?'':' · 缺数'}</td></tr>`).join('')}</tbody></table></div>
        </section>`;
    } catch(e) {if(e.name!=='AbortError') $('strategyDetail').innerHTML=`<p class="rgs-error">${esc(e.message)}</p>`;}
  }
  function closeDetail() {detailController?.abort();$('strategyDrawer').hidden=true;$('strategyMask').hidden=true;document.body.style.overflow='';opener?.focus();}
  form.addEventListener('submit',e=>{e.preventDefault();focus='all';recommendation='all';activeCard=form.elements.exit_status.value;load();});
  $('strategyReset').addEventListener('click',()=>{form.reset();focus='all';recommendation='all';activeCard='tracking';$('strategyDistributionDetails').open=false;load();});
  function selectSummary(e) {const btn=e.target.closest('[data-summary]');if(!btn)return;activeCard=btn.dataset.summary;recommendation=['ready','pending'].includes(activeCard)?activeCard:'all';form.elements.exit_status.value=recommendation==='all'?activeCard:'tracking';form.elements.stage.value='all';form.elements.age_band.value='all';focus='all';load();}
  $('strategySummary').addEventListener('click',selectSummary);$('strategyStages').addEventListener('click',selectSummary);
  $('strategyClearAdvice').addEventListener('click',()=>{recommendation='all';activeCard=form.elements.exit_status.value;load();});
  function selectStage(e) {const btn=e.target.closest('[data-stage]');if(!btn)return;const stage=btn.dataset.stage;
    form.elements.stage.value=stage;form.elements.age_band.value=btn.dataset.band || 'all';
    form.elements.exit_status.value=['early','normal'].includes(stage)?stage:'tracking';
    if(btn.dataset.state)form.elements.state.value=btn.dataset.state;
    activeCard=form.elements.exit_status.value==='tracking'?'tracking':'exited';recommendation='all';focus='all';load();}
  $('strategyStages').addEventListener('click',selectStage);$('strategyDistributions').addEventListener('click',selectStage);
  $('strategyClearStage').addEventListener('click',()=>{form.elements.stage.value='all';form.elements.age_band.value='all';form.elements.exit_status.value='tracking';recommendation='all';activeCard='tracking';focus='all';load();});
  function selectFocus(key) {focus=key;form.elements.stage.value='intervene';form.elements.exit_status.value='tracking';form.elements.age_band.value='all';recommendation='all';activeCard='tracking';load();}
  $('strategyInterventionCards').addEventListener('click',e=>{const btn=e.target.closest('[data-focus]');if(btn)selectFocus(btn.dataset.focus);});
  $('strategyDecisionNotes').addEventListener('click',e=>{const btn=e.target.closest('[data-focus]');if(btn)selectFocus(btn.dataset.focus);});
  $('strategyClearFocus').addEventListener('click',()=>selectFocus('all'));
  $('strategyGrid').addEventListener('click',e=>{const btn=e.target.closest('[data-event]');if(btn)openDetail(btn.dataset.event,btn);});
  $('strategyClose').addEventListener('click',closeDetail);$('strategyMask').addEventListener('click',closeDetail);
  document.addEventListener('keydown',e=>{if($('strategyDrawer').hidden)return;if(e.key==='Escape')closeDetail();if(e.key==='Tab'){const items=[...$('strategyDrawer').querySelectorAll('button,summary,a,[tabindex="0"]')].filter(el=>el.getClientRects().length);const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
  load();
})();

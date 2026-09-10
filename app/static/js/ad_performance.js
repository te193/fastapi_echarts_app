(function () {
  "use strict";
  var state = { mode: "overview", bidType: "ad_group", view: "product", window: 7, page: 1, pageSize: 50, sort: "cost", direction: "desc", total: 0, options: null, recOptions: null, diagnosisOptions: null, governanceOptions: null, grid: null, governanceGrid: null, chart: null, actionChart: null, recStatusChart: null, controller: null, requestId: 0, trendMode: "amount", trendRows: [], scope: {}, governanceLevel: "campaign", governanceCampaignId: null, governanceAdGroupId: null };
  var $ = function (id) { return document.getElementById(id); };
  var viewMeta = {
    product: ["MSKU 表现", "指标来自广告商品报表，可直接归属到 MSKU。"],
    campaign: ["广告活动", "每行代表一个广告账号下的活动，名称与配置状态为当前值。"],
    ad_group: ["广告组", "广告组指标不按其关联的多个 MSKU 分摊。"],
    keyword: ["关键词", "相同文字在不同活动、广告组和匹配方式下分别统计。"],
    search_term: ["搜索词", "展示用户实际搜索词及对应投放内容，属于搜索词报表覆盖范围。"]
  };
  var recMeta = {
    bid: ["竞价优化", "逐项展示当前竞价、建议竞价和具体调整金额。"],
    add: ["加词建议", "业务指标决定建议动作；MSKU映射异常在数据提示中单独标注。"],
    negative: ["否词建议", "搜索词达到阈值后，品牌词、核心类目词和新品推广词命中后转人工审核。"]
  };
  function text(value) { return value === null || value === undefined || value === "" ? "—" : String(value); }
  function number(value, digits) { return value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits === undefined ? 2 : digits }); }
  function percent(value) { return value === null || value === undefined ? "—" : (Number(value) * 100).toFixed(2) + "%"; }
  function currentCurrency() { return $("ap-currency") ? $("ap-currency").value : ""; }
  function money(value, currency, digits) { return AdCurrency.format(value, currency || currentCurrency(), digits); }
  function rowMoney(params, currency) { return money(params.value, currency || (params.data && params.data.currency_code)); }
  function params(extra) {
    var p = new URLSearchParams({ view: state.view, window: state.window, start: $("ap-start").value, end: $("ap-end").value,
      currency: $("ap-currency").value, store: $("ap-store").value, country: $("ap-country").value,
      targeting: $("ap-targeting").value, campaign: $("ap-campaign").value.trim(), ad_group: $("ap-ad-group").value.trim(),
      keyword_text: $("ap-keyword-text").value.trim(), search_term: $("ap-search-term").value.trim(), msku: $("ap-msku").value.trim(),
      page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction });
    if (["keyword", "search_term"].indexOf(state.view) < 0) p.delete("keyword_text");
    if (state.view !== "search_term") p.delete("search_term");
    Object.keys(state.scope).forEach(function (key) { if (state.scope[key] !== null && state.scope[key] !== undefined && state.scope[key] !== "") p.set(key, state.scope[key]); });
    Object.keys(extra || {}).forEach(function (key) { p.set(key, extra[key]); });
    return p;
  }
  function endpoint(path, extra) { return "/api/ad-performance/" + path + "?" + params(extra).toString(); }
  function recommendationParams(extra) {
    var p = new URLSearchParams({ kind: state.mode, currency: "", store: $("ap-store").value,
      country: $("ap-country").value, targeting: $("ap-targeting").value, status: $("ap-rec-status").value,
      priority: $("ap-rec-priority").value, campaign: $("ap-campaign").value.trim(), ad_group: $("ap-ad-group").value.trim(),
      keyword_text: $("ap-keyword-text").value.trim(), search_term: $("ap-search-term").value.trim(), msku: $("ap-msku").value.trim(),
      page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction });
    if (state.mode === "bid") p.set("object_type", state.bidType);
    if (state.mode === "bid") p.delete("search_term");
    Object.keys(state.scope).forEach(function(key){if(state.scope[key]!==null&&state.scope[key]!==undefined&&state.scope[key]!=="")p.set(key,state.scope[key]);});
    Object.keys(extra || {}).forEach(function (key) { p.set(key, extra[key]); }); return p;
  }
  function recommendationEndpoint(path, extra) { return "/api/ad-performance/recommendations/" + path + "?" + recommendationParams(extra).toString(); }
  function governanceParams(extra) {
    var p=new URLSearchParams({base_store:$("ap-governance-base-store").value.trim(),store:$("ap-governance-store").value.trim(),country:$("ap-governance-country").value.trim(),targeting_type:$("ap-governance-targeting").value,entity_state:$("ap-governance-state").value,action_type:$("ap-governance-action").value,keyword:$("ap-governance-keyword").value.trim(),level:state.governanceLevel});
    if(state.governanceCampaignId)p.set("campaign_id",state.governanceCampaignId);
    if(state.governanceAdGroupId)p.set("ad_group_id",state.governanceAdGroupId);
    Object.keys(extra||{}).forEach(function(key){var value=extra[key];if(value===null||value===undefined||value==="")p.delete(key);else p.set(key,value);});return p;
  }
  function governanceEndpoint(path,extra){return "/api/ad-performance/governance/"+path+"?"+governanceParams(extra).toString();}
  function diagnosisParams(extra) {
    var p=new URLSearchParams({period:$("ap-diagnosis-period").value,window:state.window,currency:$("ap-currency").value,
      store:$("ap-store").value,country:$("ap-country").value,keyword:$("ap-msku").value.trim(),
      action:$("ap-diagnosis-action").value,page:state.page,page_size:state.pageSize,sort:state.sort,direction:state.direction});
    Object.keys(extra||{}).forEach(function(key){p.set(key,extra[key]);});return p;
  }
  function diagnosisEndpoint(path,extra){return "/api/ad-performance/product-diagnosis/"+path+"?"+diagnosisParams(extra).toString();}
  function isRecommendationMode(mode){return ["bid","add","negative"].indexOf(mode)>=0;}
  async function json(path, signal, extra) {
    var response = await fetch(endpoint(path, extra), { signal: signal });
    if (!response.ok) throw new Error((await response.json()).detail || "请求失败");
    return response.json();
  }
  function fillSelect(id, items, valueKey) {
    var select = $(id), initial = select.options[0] ? select.options[0].outerHTML : "";
    select.innerHTML = initial + items.map(function (item) { var value = valueKey ? item[valueKey] : item; var label = item.label || value; return '<option value="' + escapeHtml(value) + '">' + escapeHtml(label) + "</option>"; }).join("");
  }
  function escapeHtml(value) { var d = document.createElement("div"); d.textContent = value === undefined ? "" : value; return d.innerHTML; }
  function showError(error) { $("ap-error").hidden = false; $("ap-error").querySelector("span").textContent = error.message || error; }
  function hideError() { $("ap-error").hidden = true; }
  function recommendationStatusMeta(kind) {
    if(kind==="bid") return [
      ["","全部记录","当前筛选范围","#176e83"],["increase","建议提价","竞价可提高","#0f9f83"],["decrease","建议降价","竞价需降低","#e5a332"],
      ["keep","建议保持","本次不调整","#4e86c6"],["manual_review","人工复核","需人工判断","#d96f53"],
      ["no_order_below_threshold","无订单未达阈值","暂不参与竞价调整","#7d8da0"],
      ["with_order_below_threshold","有订单未达阈值","暂不参与竞价调整","#64748b"],
      ["current_bid_missing","当前竞价缺失","无法给出建议竞价","#b45309"],
      ["calculation_input_missing","计算字段缺失","需补齐后再判断","#a16207"]
    ];
    if(kind==="add") return [
      ["","全部候选","当前筛选范围","#176e83"],["recommended","建议新增","可进入复核清单","#159b80"],["manual_review","核对商品归属","映射需人工核对","#d96f53"],
      ["existing","已经存在","同组同对象已启用","#4e86c6"],["existing_inactive","已存在但未启用","暂停或归档对象","#8b6f47"],["observe","未达标准","继续观察","#7d8da0"]
    ];
    return [
      ["","全部候选","当前筛选范围","#176e83"],["recommended","建议否定","可进入复核清单","#159b80"],["manual_review","人工审核","品牌/类目/新品保护","#d96f53"],
      ["existing","已经存在","无需重复否定","#4e86c6"],["observe","未达标准","继续观察","#7d8da0"]
    ];
  }
  function fillDatalist(id, items) {
    $(id).innerHTML = items.map(function (item) { return '<option value="' + escapeHtml(item) + '"></option>'; }).join("");
  }
  function applyRecommendationStatus(value) {
    var select=$("ap-rec-status"),next=select.value===value&&value!==""?"":value;
    select.value=next;state.page=1;load();
  }
  function renderRecommendationSummary(row) {
    var breakdown=row.status_breakdown||{},selected=$("ap-rec-status").value,meta=recommendationStatusMeta(state.mode);
    $("ap-rec-summary-title").textContent=recMeta[state.mode][0]+"实际分布";
    $("ap-rec-summary-meta").textContent="成熟30天 · 全部币种";
    $("ap-rec-status-cards").innerHTML=meta.map(function(item){var count=item[0]===""?row.total:(breakdown[item[0]]||0);return '<button type="button" class="ap-rec-status-card'+(selected===item[0]?' active':'')+'" data-rec-status="'+escapeHtml(item[0])+'" aria-pressed="'+String(selected===item[0])+'"><span>'+escapeHtml(item[1])+'</span><strong>'+number(count,0)+'</strong><small>'+escapeHtml(item[2])+'</small></button>';}).join("");
    var chartMeta=["add","negative"].indexOf(state.mode)>=0?meta.slice(1).filter(function(item){return item[0]!=="observe";}):meta.slice(1);
    $("ap-rec-status-chart").style.height=state.mode==="bid"?"238px":"190px";
    if(!state.recStatusChart)state.recStatusChart=echarts.init($("ap-rec-status-chart"));
    state.recStatusChart.resize();
    state.recStatusChart.setOption({animationDuration:240,grid:{left:105,right:42,top:8,bottom:22},tooltip:{trigger:"axis",axisPointer:{type:"shadow"}},xAxis:{type:"value",minInterval:1,splitLine:{lineStyle:{color:"#edf1f5"}}},yAxis:{type:"category",inverse:true,data:chartMeta.map(function(item){return item[1];}),axisLine:{show:false},axisTick:{show:false}},series:[{type:"bar",barMaxWidth:22,data:chartMeta.map(function(item){return {value:breakdown[item[0]]||0,status:item[0],itemStyle:{color:item[3],borderRadius:[0,6,6,0]}};}),label:{show:true,position:"right",color:"#3e5872",fontWeight:700}}]},true);
    state.recStatusChart.off("click");state.recStatusChart.on("click",function(event){if(event.data&&event.data.status!==undefined)applyRecommendationStatus(event.data.status);});
  }
  function renderGovernanceSummary(row) {
    $("ap-governance-campaigns").textContent=number(row.campaign_count,0);$("ap-governance-groups").textContent=number(row.ad_group_count,0);$("ap-governance-actionable").textContent=number(row.actionable_ad_group_count,0);$("ap-governance-rate").textContent="覆盖率 "+percent(row.actionable_rate);$("ap-governance-review").textContent=number(row.manual_review_ad_group_count,0);
    $("ap-governance-bid").textContent=number(row.bid_action_count,0);$("ap-governance-bid-detail").textContent="提价 "+number(row.bid_increase_count,0)+" · 降价 "+number(row.bid_decrease_count,0);$("ap-governance-add").textContent=number(row.add_action_count,0);$("ap-governance-negative").textContent=number(row.negative_action_count,0);
  }
  function governanceBadge(label,value,tone){if(!Number(value||0))return "";return '<span class="ap-governance-badge '+(tone||"action")+'">'+escapeHtml(label)+" "+number(value,0)+"</span>";}
  function renderGovernanceStores(rows) {
    $("ap-governance-store-count").textContent=number(rows.length,0)+" 个";
    $("ap-governance-store-list").innerHTML=rows.map(function(row){var active=$("ap-governance-base-store").value===row.base_store_name;return '<button type="button" class="ap-governance-store'+(active?' active':'')+'" data-base-store="'+escapeHtml(row.base_store_name)+'"><span><b>'+escapeHtml(row.base_store_name||"未识别店铺")+'</b><em>'+number(row.actionable_ad_group_count,0)+' 组待办</em></span><small>'+number(row.site_count,0)+' 个站点 · '+number(row.campaign_count,0)+' 个活动 · '+number(row.ad_group_count,0)+' 个广告组 · '+number(row.msku_count,0)+' 个MSKU</small><div>'+governanceBadge("竞价",row.bid_action_count)+governanceBadge("加词",row.add_action_count)+governanceBadge("否词",row.negative_action_count)+governanceBadge("审核",row.manual_review_ad_group_count,"review")+governanceBadge("待归属",row.unresolved_msku_ad_group_count,"review")+'</div></button>';}).join("")||'<div class="empty-state compact">当前筛选下没有店铺</div>';
  }
  function renderGovernanceSites(rows) {
    var selectedStore=$("ap-governance-store").value,selectedCountry=$("ap-governance-country").value;
    var all='<button type="button" data-governance-store="" data-governance-country="" class="'+(!selectedStore&&!selectedCountry?'active':'')+'">全部站点</button>';
    $("ap-governance-sites").innerHTML=all+rows.map(function(row){var active=selectedStore===row.seller_name&&selectedCountry===row.country_code;return '<button type="button" class="'+(active?'active':'')+'" data-governance-store="'+escapeHtml(row.seller_name||"")+'" data-governance-country="'+escapeHtml(row.country_code||"")+'">'+escapeHtml(row.country_code||"未知")+' · '+number(row.actionable_ad_group_count,0)+'</button>';}).join("");
  }
  function targetingLabel(value){return value==="auto"?"自动广告":value==="manual"?"手动广告":value==="mixed"?"混合投放":"未知类型";}
  function governanceStateLabel(value){return ({enabled:"启用",paused:"暂停",archived:"归档"})[String(value||"").toLowerCase()]||"未知";}
  function governanceMskuMappingLabel(value){return ({normal_mapping:"归属明确",period_record_missing:"成熟期无商品记录",current_record_missing:"当前商品记录缺失",period_multiple_msku:"成熟期多MSKU",current_multiple_msku:"当前多MSKU",msku_changed:"MSKU已变更"})[value]||"待确认归属";}
  function governanceActionButtons(row){if(state.governanceLevel==="msku"&&!row.msku)return '<span class="muted">先确认归属</span>';return '<div class="ap-governance-row-actions">'+[["bid","竞价","竞价建议",row.bid_action_count],["add","加词","加词建议",row.add_action_count],["negative","否词","否词建议",row.negative_action_count],["bid_review","竞审","竞价人工审核",row.bid_manual_review_count],["add_review","加审","加词人工审核",row.add_manual_review_count],["negative_review","否审","否词人工审核",row.negative_manual_review_count]].filter(function(item){return Number(item[3]||0)>0;}).map(function(item){return '<button type="button" class="ap-governance-action-link" data-governance-action="'+item[0]+'" title="'+item[2]+'">'+item[1]+' '+number(item[3],0)+'</button>';}).join("")+"</div>";}
  function renderGovernanceEntities(rows) {
    var campaign=state.governanceLevel==="campaign",adGroup=state.governanceLevel==="ad_group",msku=state.governanceLevel==="msku";
    var cols=msku?
      [{field:"msku",headerName:"MSKU",minWidth:130,flex:1,valueFormatter:function(p){return p.value||"待确认归属";}},{field:"asin",headerName:"ASIN",width:118,valueFormatter:function(p){return text(p.value);}},{field:"country_code",headerName:"站点",width:70},{field:"msku_mapping_status",headerName:"归属状态",width:138,valueFormatter:function(p){return governanceMskuMappingLabel(p.value);}},{field:"campaign_count",headerName:"活动",width:72},{field:"ad_group_count",headerName:"广告组",width:78},{field:"cost",headerName:"花费",width:96,valueFormatter:rowMoney},{field:"sales",headerName:"销售额",width:104,valueFormatter:rowMoney},{field:"acos",headerName:"ACOS",width:78,valueFormatter:function(p){return percent(p.value);}},{field:"actionable_ad_group_count",headerName:"待办组",width:78},{headerName:"治理动作",minWidth:220,flex:1,sortable:false,filter:false,cellRenderer:function(p){return governanceActionButtons(p.data);},onCellClicked:function(p){var button=p.event.target.closest("[data-governance-action]");if(button)switchGovernanceRecommendation(button.dataset.governanceAction,p.data);}}]:
      [objectColumn(campaign?"campaign_name_current":"ad_group_name_current",campaign?"广告活动":"广告组",campaign?190:180),{field:"country_code",headerName:"站点",width:70},{field:"targeting_type",headerName:"投放方式",width:90,valueFormatter:function(p){return targetingLabel(p.value);}},{field:campaign?"campaign_state_current":"ad_group_state_current",headerName:"状态",width:75,valueFormatter:function(p){return governanceStateLabel(p.value);}},{field:"ad_group_count",headerName:"广告组",width:78},{field:"cost",headerName:"花费",width:96,valueFormatter:rowMoney},{field:"sales",headerName:"销售额",width:104,valueFormatter:rowMoney},{field:"acos",headerName:"ACOS",width:78,valueFormatter:function(p){return percent(p.value);}},{field:"actionable_ad_group_count",headerName:"待办组",width:78},{headerName:"治理动作",minWidth:220,flex:1,sortable:false,filter:false,cellRenderer:function(p){return governanceActionButtons(p.data);},onCellClicked:function(p){var button=p.event.target.closest("[data-governance-action]");if(button)switchGovernanceRecommendation(button.dataset.governanceAction,p.data);}}];
    if(campaign)cols.push({headerName:"下钻",width:86,pinned:"right",sortable:false,filter:false,cellRenderer:function(){return '<button type="button" class="ap-governance-action-link" data-governance-drill="1">广告组</button>';},onCellClicked:function(p){if(p.event.target.closest("[data-governance-drill]")){state.governanceCampaignId=p.data.campaign_id;state.governanceAdGroupId=null;state.governanceLevel="ad_group";renderGovernanceLevel();loadGovernanceEntities();}}});
    if(adGroup)cols.push({headerName:"下钻",width:86,pinned:"right",sortable:false,filter:false,cellRenderer:function(){return '<button type="button" class="ap-governance-action-link" data-governance-msku="1">MSKU</button>';},onCellClicked:function(p){if(p.event.target.closest("[data-governance-msku]")){state.governanceCampaignId=p.data.campaign_id;state.governanceAdGroupId=p.data.ad_group_id;state.governanceLevel="msku";renderGovernanceLevel();loadGovernanceEntities();}}});
    if(state.governanceGrid&&state.governanceGrid.destroy)state.governanceGrid.destroy();state.governanceGrid=window.kanbanGrid.makeGrid("ap-governance-entity-grid",{rowData:rows,columnDefs:cols,domLayout:"normal",rowHeight:48,headerHeight:44});
  }
  function renderGovernanceLevel(){$("ap-governance-levels").querySelectorAll("button[data-level]").forEach(function(button){button.classList.toggle("active",button.dataset.level===state.governanceLevel);});}
  async function governanceFetch(path,extra){var response=await fetch(governanceEndpoint(path,extra));if(!response.ok)throw new Error((await response.json()).detail||"治理数据读取失败");return response.json();}
  async function loadGovernanceEntities(){
    if(!$("ap-governance-base-store").value){renderGovernanceSites([]);renderGovernanceEntities([]);return;}
    var results=await Promise.all([governanceFetch("entities",{level:"site",campaign_id:"",ad_group_id:""}),governanceFetch("entities",{level:state.governanceLevel})]);renderGovernanceSites(results[0].rows||[]);renderGovernanceEntities(results[1].rows||[]);
  }
  async function loadGovernance(){
    var results=await Promise.all([governanceFetch("summary"),governanceFetch("stores",{base_store:""})]);renderGovernanceSummary(results[0].summary||{});var rows=results[1].rows||[];
    if(!$("ap-governance-base-store").value&&rows.length)$("ap-governance-base-store").value=rows[0].base_store_name||"";renderGovernanceStores(rows);$("ap-governance-selection").textContent=$("ap-governance-base-store").value||"请选择店铺主体";await loadGovernanceEntities();
  }
  function switchGovernanceRecommendation(kind,row){
    var review=kind.endsWith("_review"),recommendationKind=review?kind.replace("_review",""):kind,targeting=(row&&row.targeting_type)||$("ap-governance-targeting").value;if(recommendationKind==="bid")state.bidType=targeting==="auto"?"ad_group":targeting==="manual"?"keyword":"";state.mode=recommendationKind;$("ap-store").value=(row&&row.seller_name)||$("ap-governance-store").value;$("ap-country").value=(row&&row.country_code)||$("ap-governance-country").value;$("ap-targeting").value=$("ap-governance-targeting").value;if(row&&row.msku)$("ap-msku").value=row.msku;switchMode(recommendationKind);state.scope={base_store:$("ap-governance-base-store").value};["profile_id","campaign_id","ad_group_id"].forEach(function(key){if(row&&row[key])state.scope[key]=row[key];});$("ap-rec-status").value=review?"manual_review":recommendationKind==="bid"?"":"recommended";load();
  }
  function renderSummary(row) {
    $("ap-cost").textContent = money(row.cost); $("ap-sales").textContent = money(row.sales); $("ap-orders").textContent = number(row.orders, 0);
    $("ap-impressions").textContent = number(row.impressions, 0); $("ap-clicks").textContent = number(row.clicks, 0); $("ap-acos").textContent = percent(row.acos);
    $("ap-cvr").textContent = "CVR " + percent(row.cvr); $("ap-ctr").textContent = "CTR " + percent(row.ctr); $("ap-cpc").textContent = "CPC " + money(row.cpc);
    $("ap-roas").textContent = "ROAS " + number(row.roas); $("ap-cost-currency").textContent = $("ap-currency").selectedOptions[0].textContent;
    $("ap-sales-window").textContent = state.window + " 天归因";
  }
  function renderTrend(rows) {
    state.trendRows = rows;
    if (!state.chart) state.chart = echarts.init($("ap-trend"));
    var modes = {
      amount: { title: "投入与转化走势", names: ["花费", "广告销售额"], fields: ["cost", "sales"], colors: ["#2563eb", "#f59e0b"], percent: false },
      traffic: { title: "流量规模走势", names: ["曝光", "点击"], fields: ["impressions", "clicks"], colors: ["#2563eb", "#16a34a"], percent: false },
      rate: { title: "点击与转化效率", names: ["CTR", "CVR"], fields: ["ctr", "cvr"], colors: ["#7c3aed", "#ea580c"], percent: true }
    };
    var mode = modes[state.trendMode];
    $("ap-trend-title").textContent=mode.title;
    state.chart.setOption({ animationDuration: 280, color: mode.colors, tooltip: { trigger: "axis", valueFormatter: mode.percent ? function(v){ return v === null ? "—" : (Number(v) * 100).toFixed(2) + "%"; } : undefined },
      legend: { top: 8, data: mode.names }, grid: { left: 58, right: 62, top: 48, bottom: 35 },
      xAxis: { type: "category", data: rows.map(function (r) { return r.report_date; }), axisLine: { lineStyle: { color: "#cbd5e1" } } },
      yAxis: [{ type: "value", axisLabel: { formatter: mode.percent ? function(v){ return (v * 100).toFixed(0) + "%"; } : "{value}" }, splitLine: { lineStyle: { color: "#edf1f6" } } },
              { type: "value", axisLabel: { formatter: mode.percent ? function(v){ return (v * 100).toFixed(0) + "%"; } : "{value}" }, splitLine: { show: false } }],
      series: [{ name: mode.names[0], type: "line", smooth: true, symbol: "none", areaStyle: { opacity: .08 }, data: rows.map(function (r) { return r[mode.fields[0]]; }) },
               { name: mode.names[1], type: "line", yAxisIndex: 1, smooth: true, symbol: "none", data: rows.map(function (r) { return r[mode.fields[1]]; }) }] }, true);
  }
  function objectColumn(field, header, width) { return { field: field, headerName: header, minWidth: width || 150, pinned: field === "msku" ? "left" : null,
    cellRenderer: function (p) { return '<span class="ap-object" title="' + escapeHtml(text(p.value)) + '">' + escapeHtml(text(p.value)) + "</span>"; } }; }
  function columns(view) {
    var common = [objectColumn("seller_name", "店铺", 140), { field: "country_code", headerName: "站点", width: 82 }, { field: "currency_code", headerName: "币种", width: 82 }];
    var objects = {
      product: [objectColumn("msku", "MSKU", 155), objectColumn("asin", "关联 ASIN", 150)],
      campaign: [objectColumn("campaign_name_current", "广告活动（当前）", 220), objectColumn("portfolio_name_current", "Portfolio（当前）", 160), { field: "targeting_type", headerName: "方式", width: 90 }],
      ad_group: [objectColumn("campaign_name_current", "广告活动（当前）", 180), objectColumn("ad_group_name_current", "广告组（当前）", 200), { field: "associated_msku_count", headerName: "关联MSKU", width: 105 }],
      keyword: [objectColumn("keyword_text", "关键词", 190), { field: "match_type", headerName: "匹配", width: 95 }, objectColumn("campaign_name_current", "广告活动（当前）", 170), objectColumn("ad_group_name_current", "广告组（当前）", 170)],
      search_term: [objectColumn("search_term", "用户搜索词", 190), objectColumn("target_text", "投放内容", 160), { field: "match_type", headerName: "匹配", width: 90 }, objectColumn("ad_group_name_current", "广告组（当前）", 170)]
    }[view];
    var metrics = [{ field: "impressions", headerName: "曝光", width: 100, valueFormatter: function(p){return number(p.value,0);} }, { field: "clicks", headerName: "点击", width: 90, valueFormatter: function(p){return number(p.value,0);} },
      { field: "ctr", headerName: "CTR", width: 90, valueFormatter: function(p){return percent(p.value);} }, { field: "cost", headerName: "花费", width: 118, valueFormatter: rowMoney },
      { field: "cpc", headerName: "CPC", width: 100, valueFormatter: rowMoney }, { field: "orders", headerName: "订单", width: 90, valueFormatter: function(p){return number(p.value,0);} },
      { field: "units", headerName: "销量", width: 90, valueFormatter: function(p){return number(p.value,0);} }, { field: "sales", headerName: "销售额", width: 125, valueFormatter: rowMoney },
      { field: "cvr", headerName: "CVR", width: 90, valueFormatter: function(p){return percent(p.value);} }, { field: "acos", headerName: "ACOS", width: 95, valueFormatter: function(p){return percent(p.value);} },
      { field: "roas", headerName: "ROAS", width: 95, valueFormatter: function(p){return number(p.value);} },
      { field: "same_orders", headerName: "直接订单", width: 105, hide: true }, { field: "same_sales", headerName: "直接销售额", width: 120, hide: true },
      { headerName: "详情", width: 82, pinned: "right", sortable: false, filter: false, cellRenderer: function(){return '<button class="ap-detail-button">查看</button>';}, onCellClicked: function(p){openDetail(p.data);} }];
    return common.concat(objects, metrics);
  }
  function statusLabel(value, kind) {
    if(kind==="add") return ({recommended:"建议新增",manual_review:"先核对商品归属",existing:"无需新增（已存在）",existing_inactive:"已存在但未启用",observe:"暂不新增（未达标准）"})[value] || text(value);
    if(kind==="negative") return ({recommended:"建议否定",manual_review:"人工审核",existing:"无需否定（已存在）",observe:"暂不否定（未达标准）"})[value] || text(value);
    return ({increase:"建议提价",decrease:"建议降价",keep:"建议保持",manual_review:"人工复核",no_order_below_threshold:"无订单未达阈值，暂不参与竞价调整",with_order_below_threshold:"有订单未达阈值，暂不参与竞价调整",current_bid_missing:"当前竞价缺失",calculation_input_missing:"计算字段缺失"})[value] || text(value);
  }
  function renderDiagnosisSummary(row) {
    $("ap-diag-products").textContent=number(row.product_count,0);$("ap-diag-actionable").textContent=number(row.actionable_product_count,0);
    $("ap-diag-op-sales").textContent=money(row.operating_sales_amount,"CNY");$("ap-diag-profit").textContent=money(row.operating_gross_profit,"CNY");
    $("ap-diag-cost").textContent=money(row.ad_cost);$("ap-diag-ad-sales").textContent=money(row.ad_sales);$("ap-diag-window").textContent=state.window+"天归因";
    if(!state.actionChart)state.actionChart=echarts.init($("ap-diagnosis-actions-chart"));
    state.actionChart.setOption({tooltip:{trigger:"axis",axisPointer:{type:"shadow"}},grid:{left:70,right:24,top:22,bottom:30},xAxis:{type:"value"},yAxis:{type:"category",data:["竞价动作","建议加词","建议否词","人工审核"]},series:[{type:"bar",barMaxWidth:24,itemStyle:{color:"#2563eb",borderRadius:[0,6,6,0]},data:[row.bid_action_count||0,row.add_action_count||0,row.negative_action_count||0,row.manual_review_count||0]}]},true);
  }
  function renderDiagnosisTrend(rows) {
    state.trendRows=rows;if(!state.chart)state.chart=echarts.init($("ap-trend"));$("ap-trend-title").textContent="经营与广告销售走势";
    state.chart.setOption({color:["#16a34a","#f59e0b","#2563eb"],tooltip:{trigger:"axis"},legend:{top:8,data:["经营销售额","广告销售额","广告花费"]},grid:{left:58,right:30,top:48,bottom:35},xAxis:{type:"category",data:rows.map(function(r){return r.report_date;})},yAxis:{type:"value",splitLine:{lineStyle:{color:"#edf1f6"}}},series:[{name:"经营销售额",type:"line",symbol:"none",smooth:true,data:rows.map(function(r){return r.operating_sales_amount;})},{name:"广告销售额",type:"line",symbol:"none",smooth:true,data:rows.map(function(r){return r.ad_sales;})},{name:"广告花费",type:"line",symbol:"none",smooth:true,data:rows.map(function(r){return r.ad_cost;})}]},true);
  }
  function suggestionLabel(value) { return ({exact_keyword:"新增精准关键词",product_target:"新增商品投放",negative_exact:"精准否定",negative_product_target:"否定商品投放"})[value] || text(value); }
  function priorityLabel(value) { return ({highest:"最高",high:"高",medium:"中",none:"—"})[value] || text(value); }
  function budgetSupportLabel(row) { var value=row.budget_support_status;if(value==="预算已用尽，禁止提价")return "预算已用尽，仅禁止提价";if(value==="库存不足，禁止提价")return "库存不足，仅禁止提价";return value || ({multiple_msku:"关联多个MSKU，分别查看商品预算",period_multiple_msku:"成熟窗口内投放过多个MSKU",current_multiple_msku:"当前同时启用多个MSKU",msku_changed:"成熟窗口商品与当前启用商品不一致",msku_missing:"未找到推广MSKU，需人工排查",not_mapped:"商品预算未匹配，需人工排查"})[row.budget_context_status] || "—"; }
  function reasonLabel(value) { return ({theoretical_cpc_guard:"按定价毛利段理论CPC确定调整幅度",minimum_bid_increment_blocks_change:"最小竞价单位限制，本次不调整",clicks_ge_15_orders_zero:"点击≥15且无广告订单，建议降价",acos_gt_50:"ACOS>50%，优先降价",acos_gt_333:"ACOS>33.3%，建议降价",high_cvr_increase:"低ACOS且CVR达到站点P75，进入较高提价候选",site_avg_cvr_increase:"低ACOS且CVR达到站点均值，进入小幅提价候选",performance_within_guardrail:"表现处于保持区间",inventory_blocks_increase:"库存不足，禁止提价",budget_blocks_increase:"人民币月预算已用尽，禁止提价",no_order_below_threshold:"无订单但点击未达到15次降价门槛，暂不参与竞价调整",with_order_below_threshold:"已有订单但点击未达到20次判断门槛，暂不参与竞价调整",current_bid_missing:"当前竞价缺失，无法计算建议",calculation_input_missing:"达到基础样本门槛，但计算所需字段缺失",metric_missing:"计算所需字段缺失",multiple_msku:"广告组关联多个MSKU",period_multiple_msku:"成熟窗口内投放过多个MSKU",current_multiple_msku:"当前同时启用多个MSKU",msku_changed:"成熟窗口商品与当前启用商品不一致",msku_missing:"广告组未映射MSKU",price_not_mapped:"Listing价格未匹配",margin_ladder_missing:"毛利价格阶梯缺失",below_zero_margin_price:"当前价格低于0%毛利价格",existing_enabled:"同广告组同文本的精准对象已启用",existing_inactive:"同广告组同对象已存在，但当前为暂停或归档状态",orders_ge_10_acos_le_10:"订单不少于10且ACOS不高于10%",orders_ge_10_acos_le_15:"订单不少于10且ACOS不高于15%",clicks_ge_10_orders_zero:"点击不少于10且订单为0",threshold_not_met:"未达到建议阈值",term_protection_context_missing:"未匹配Listing保护信息",brand_context_missing:"产品品牌信息缺失",category_context_missing:"本地化叶子类目信息缺失",launch_date_missing:"首单及开售日期缺失",launch_date_invalid:"首单或开售日期异常",brand_term:"品牌词保护",core_category_term:"核心类目词保护",new_product_term:"新品推广词保护"})[value] || text(value); }
  function recommendationColumns(kind) {
    var common=[objectColumn("seller_name","店铺",140),{field:"country_code",headerName:"站点",width:82},{field:"currency_code",headerName:"币种",width:78},{field:"targeting_type",headerName:"广告类型",width:100,valueFormatter:function(p){return targetingLabel(p.value);}},objectColumn("msku","MSKU",145)];
    var metric=[{field:"clicks",headerName:"点击",width:88,valueFormatter:function(p){return number(p.value,0);}},{field:"cost",headerName:"花费",width:112,valueFormatter:rowMoney},{field:"orders",headerName:"订单",width:88,valueFormatter:function(p){return number(p.value,0);}},{field:"sales",headerName:"销售额",width:120,valueFormatter:rowMoney}];
    var detail={headerName:"详情",width:78,pinned:"right",sortable:false,filter:false,cellRenderer:function(){return '<button class="ap-detail-button">查看</button>';},onCellClicked:function(p){openDetail(p.data);}};
    if(kind==="bid") return common.concat([
      objectColumn("object_text",state.bidType==="ad_group"?"广告组（当前）":state.bidType==="keyword"?"关键词":"竞价对象",190),
      {field:"match_type",headerName:"匹配",width:90,hide:state.bidType==="ad_group"},
      {field:"clicks",headerName:"点击",width:88,valueFormatter:function(p){return number(p.value,0);}},
      {field:"cvr",headerName:"CVR",width:92,valueFormatter:function(p){return percent(p.value);}},
      {field:"acos",headerName:"ACOS",width:92,sortable:false,valueFormatter:function(p){return percent(p.value);}},
      {field:"current_bid",headerName:"当前竞价",width:112,valueFormatter:rowMoney},
      {field:"listing_price",headerName:"Listing价格",width:120,sortable:false,valueFormatter:rowMoney},
      {field:"margin_rate",headerName:"定价毛利率",width:112,sortable:false,valueFormatter:function(p){return percent(p.value);}},
      {field:"theoretical_cpc",headerName:"理论CPC",width:112,sortable:false,valueFormatter:rowMoney},
      {field:"listing_mapping_status",headerName:"定价映射",width:145,sortable:false},
      {field:"monthly_ad_budget_cny",headerName:"月预算",width:125,sortable:false,valueFormatter:function(p){return money(p.value,"CNY");}},
      {field:"month_spend_cny",headerName:"本月已用",width:125,sortable:false,valueFormatter:function(p){return money(p.value,"CNY");}},
      {field:"remaining_budget_cny",headerName:"剩余预算",width:125,sortable:false,valueFormatter:function(p){return money(p.value,"CNY");}},
      {field:"budget_usage_rate",headerName:"预算使用率",width:112,sortable:false,valueFormatter:function(p){return percent(p.value);}},
      {field:"budget_support_status",headerName:"提价支持",width:205,sortable:false,cellRenderer:function(p){var value=budgetSupportLabel(p.data||{});return '<span class="ap-data-warning" title="'+escapeHtml(value)+'">'+escapeHtml(value)+'</span>'; }},
      {field:"max_allowed_bid",headerName:"允许最高建议竞价",width:155,sortable:false,valueFormatter:rowMoney},
      {field:"suggested_bid",headerName:"建议竞价",width:112,valueFormatter:rowMoney},
      {field:"change_amount",headerName:"调整金额",width:125,valueFormatter:function(p){return p.value===null?"—":(Number(p.value)>0?"提高 ":Number(p.value)<0?"降低 ":"保持 ")+money(Math.abs(Number(p.value)),p.data&&p.data.currency_code);}},
      {field:"change_rate",headerName:"调整比例",width:100,valueFormatter:function(p){return percent(p.value);}},
      {field:"cost",headerName:"花费",width:112,valueFormatter:rowMoney},
      {field:"orders",headerName:"订单",width:88,valueFormatter:function(p){return number(p.value,0);}},
      {field:"sales",headerName:"销售额",width:120,valueFormatter:rowMoney},
      {field:"status",headerName:"建议",width:230,valueFormatter:function(p){return statusLabel(p.value);}},detail]);
    return common.concat([objectColumn("suggestion_value",kind==="add"?"候选新增内容":"候选否定内容",210),{field:"suggestion_type",headerName:"建议类型",width:135,valueFormatter:function(p){return suggestionLabel(p.value);}},{field:"status",headerName:"建议动作",width:145,valueFormatter:function(p){return statusLabel(p.value,kind);}},{field:"data_warning",headerName:kind==="negative"?"人工审核原因":"数据提示",width:285,sortable:false,filter:false,cellRenderer:function(p){return '<span class="ap-data-warning" title="'+escapeHtml(text(p.value))+'">'+escapeHtml(text(p.value))+'</span>'; }},{field:"priority",headerName:"优先级",width:90,valueFormatter:function(p){return priorityLabel(p.value);}},objectColumn("campaign_name_current","广告活动（当前）",170),objectColumn("ad_group_name_current","广告组（当前）",170)].concat(metric,[{field:"acos",headerName:"ACOS",width:90,valueFormatter:function(p){return percent(p.value);}},detail]));
  }
  function diagnosisColumns() {
    var n=function(field,header,width,digits){return {field:field,headerName:header,width:width||105,valueFormatter:function(p){return number(p.value,digits);}};};
    var cny=function(field,header,width){return {field:field,headerName:header,width:width||125,valueFormatter:function(p){return money(p.value,"CNY");}};};
    var adMoney=function(field,header,width){return {field:field,headerName:header,width:width||120,valueFormatter:rowMoney};};
    var pc=function(field,header){return {field:field,headerName:header,width:95,valueFormatter:function(p){return percent(p.value);}};};
    return [objectColumn("msku","MSKU",145),objectColumn("asin","ASIN",130),objectColumn("seller_name","店铺",140),{field:"country_code",headerName:"站点",width:76},{field:"targeting_type",headerName:"广告类型",width:100,valueFormatter:function(p){return targetingLabel(p.value);}},
      n("operating_sales_qty","经营销量",105,0),cny("operating_sales_amount","经营销售额",125),cny("operating_gross_profit","经营毛利润",125),pc("operating_gross_margin","毛利率"),n("operating_inventory_qty","FBA可售",100,0),
      n("ad_impressions","曝光",100,0),n("ad_clicks","点击",88,0),pc("ctr","CTR"),adMoney("ad_cost","广告花费",120),adMoney("cpc","CPC",100),n("ad_orders","广告订单",105,0),adMoney("ad_sales","广告销售额",130),pc("cvr","CVR"),pc("acos","ACOS"),pc("tacos","TACOS"),n("roas","ROAS",88),
      cny("monthly_ad_budget_cny","月预算",125),cny("month_spend_cny","本月已用",125),cny("remaining_budget_cny","剩余预算",125),pc("budget_usage_rate","预算使用率"),{field:"budget_support_status",headerName:"提价支持",width:180},
      n("bid_increase_count","提价",76,0),n("bid_decrease_count","降价",76,0),n("bid_manual_review_count","竞价复核",95,0),n("add_recommended_count","建议加词",95,0),n("negative_recommended_count","建议否词",95,0),n("negative_manual_review_count","否词审核",95,0),
      {field:"data_warning",headerName:"数据提示",width:160,sortable:false,cellRenderer:function(p){return '<span class="ap-data-warning">'+escapeHtml(text(p.value))+'</span>'; }},
      {headerName:"详情",width:78,pinned:"right",sortable:false,filter:false,cellRenderer:function(){return '<button class="ap-detail-button">查看</button>';},onCellClicked:function(p){openDetail(p.data);}}];
  }
  function renderDiagnosisRows(payload) {
    payload.rows.forEach(function(row){row.__diagnosis=true;});if(state.grid&&state.grid.destroy)state.grid.destroy();
    state.grid=kanbanGrid.makeGrid("ap-grid",{columnDefs:diagnosisColumns(),rowData:payload.rows,domLayout:"normal",rowHeight:42,headerHeight:44,onSortChanged:function(event){var model=event.api.getColumnState().find(function(c){return c.sort;});if(model&&(model.colId!==state.sort||model.sort!==state.direction)){state.sort=model.colId;state.direction=model.sort;state.page=1;load();}}});
    state.total=payload.total;var pages=Math.max(1,Math.ceil(payload.total/state.pageSize));$("ap-page-summary").textContent="共 "+number(payload.total,0)+" 个广告产品";$("ap-page").textContent=state.page+" / "+pages;$("ap-prev").disabled=state.page<=1;$("ap-next").disabled=state.page>=pages;
  }
  function renderRows(payload) {
    payload.rows.forEach(function(row){row.__view=payload.view;});
    if (state.grid && state.grid.destroy) state.grid.destroy();
    state.grid = kanbanGrid.makeGrid("ap-grid", { columnDefs: columns(payload.view), rowData: payload.rows, domLayout: "normal", rowHeight: 42, headerHeight: 44,
      onSortChanged: function (event) { var model = event.api.getColumnState().find(function(c){return c.sort;}); if (model && (model.colId !== state.sort || model.sort !== state.direction)) { state.sort=model.colId; state.direction=model.sort; state.page=1; load(); } } });
    state.total = payload.total; var pages = Math.max(1, Math.ceil(payload.total / state.pageSize));
    $("ap-page-summary").textContent = "共 " + number(payload.total, 0) + " 条"; $("ap-page").textContent = state.page + " / " + pages;
    $("ap-prev").disabled = state.page <= 1; $("ap-next").disabled = state.page >= pages;
  }
  function renderRecommendationRows(payload) {
    payload.rows.forEach(function(row){row.__recommendation=true;row.__kind=payload.kind;});
    if(state.grid&&state.grid.destroy)state.grid.destroy();
    state.grid=kanbanGrid.makeGrid("ap-grid",{columnDefs:recommendationColumns(payload.kind),rowData:payload.rows,domLayout:"normal",rowHeight:42,headerHeight:44,
      onSortChanged:function(event){var model=event.api.getColumnState().find(function(c){return c.sort;});if(model&&(model.colId!==state.sort||model.sort!==state.direction)){state.sort=model.colId;state.direction=model.sort;state.page=1;load();}}});
    state.total=payload.total;var pages=Math.max(1,Math.ceil(payload.total/state.pageSize));$("ap-page-summary").textContent="共 "+number(payload.total,0)+" 条";$("ap-page").textContent=state.page+" / "+pages;$("ap-prev").disabled=state.page<=1;$("ap-next").disabled=state.page>=pages;
  }
  function renderTags() {
    var tags = []; [["店铺", "ap-store"],["站点", "ap-country"],["投放", "ap-targeting"],["活动", "ap-campaign"],["广告组", "ap-ad-group"],["关键词/投放内容", "ap-keyword-text"],["用户搜索词", "ap-search-term"],["MSKU", "ap-msku"]].forEach(function(x){if(!$(x[1]).closest("label").hidden&&$(x[1]).value) tags.push({label:x[0]+"："+$(x[1]).value,key:x[1]});});
    [["广告账号", "profile_id"],["活动", "campaign_id"],["广告组", "ad_group_id"]].forEach(function(x){if(state.scope[x[1]])tags.push({label:x[0]+"："+state.scope[x[1]],key:x[1],scope:true});});
    $("ap-filter-tags").innerHTML = tags.map(function(t){return '<button type="button" data-clear="'+escapeHtml(t.key)+'" data-scope="'+(t.scope?"1":"0")+'">'+escapeHtml(t.label)+' ×</button>';}).join("");
  }
  function switchView(view, keepScope) {
    state.view=view;state.page=1;state.sort="cost";state.direction="desc";if(!keepScope)state.scope={};
    $("ap-tabs").querySelectorAll("button").forEach(function(x){x.classList.toggle("active",x.dataset.view===view);});
    $("ap-view-title").textContent=viewMeta[view][0];$("ap-view-note").textContent=viewMeta[view][1];
    updateObjectFilterVisibility();
  }
  function updateObjectFilterVisibility() {
    var diagnosis=state.mode==="diagnosis",recommendation=isRecommendationMode(state.mode);
    $("ap-campaign-label").hidden=diagnosis;
    $("ap-ad-group-label").hidden=diagnosis;
    $("ap-keyword-text-label").hidden=diagnosis||(!recommendation&&["keyword","search_term"].indexOf(state.view)<0);
    $("ap-search-term-label").hidden=diagnosis||(recommendation?state.mode==="bid":state.view!=="search_term");
  }
  function fillRecommendationStatuses(mode) {
    var values=mode==="bid"?[["increase","建议提价"],["decrease","建议降价"],["keep","建议保持"],["manual_review","人工复核"],["no_order_below_threshold","无订单未达阈值"],["with_order_below_threshold","有订单未达阈值"],["current_bid_missing","当前竞价缺失"],["calculation_input_missing","计算字段缺失"]]:mode==="add"?[["recommended","建议新增"],["manual_review","先核对商品归属"],["existing","无需新增（已存在）"],["existing_inactive","已存在但未启用"],["observe","暂不新增（未达标准）"]]:[["recommended","建议否定"],["manual_review","人工审核"],["existing","无需否定（已存在）"],["observe","暂不否定（未达标准）"]];
    $("ap-rec-status").innerHTML='<option value="">全部状态</option>'+values.map(function(x){return '<option value="'+x[0]+'">'+x[1]+'</option>';}).join("");
  }
  function renderBidType() {
    $("ap-bid-types").hidden=state.mode!=="bid";
    $("ap-bid-types").querySelectorAll("button").forEach(function(button){
      var active=button.dataset.bidType===state.bidType;
      button.classList.toggle("active",active);button.setAttribute("aria-pressed",String(active));
    });
    if(state.mode==="bid") $("ap-view-note").textContent=state.bidType==="ad_group"?
      "自动广告组默认竞价：展示当前默认竞价、建议竞价和调整金额。":state.bidType==="keyword"?
      "关键词竞价：按所属广告组和匹配方式分别展示当前竞价、建议竞价和调整金额。":"广告组与关键词竞价合并展示，可继续切换具体竞价层级。";
  }
  function switchMode(mode) {
    state.mode=mode;renderBidType();state.page=1;state.sort="cost";state.direction="desc";state.scope={};
    if(mode==="diagnosis")state.sort="ad_cost";
    $("ap-analysis-tabs").querySelectorAll("button[data-mode]").forEach(function(x){x.classList.toggle("active",x.dataset.mode===mode);});
    var recommendation=isRecommendationMode(mode),diagnosis=mode==="diagnosis",governance=mode==="governance";
    $("ap-filter-panel").hidden=governance;$("ap-governance-filter-panel").hidden=!governance;$("ap-governance-panel").hidden=!governance;$("ap-table-panel").hidden=governance;
    $("ap-currency-label").hidden=recommendation;
    $("ap-window-bar").hidden=recommendation||governance;$("ap-kpis").hidden=mode!=="overview";$("ap-trend-panel").hidden=recommendation||governance;$("ap-tabs").hidden=mode!=="overview";$("ap-start-label").hidden=mode!=="overview";$("ap-end-label").hidden=mode!=="overview";
    $("ap-rec-summary-panel").hidden=!recommendation;$("ap-rule-copy").hidden=!recommendation;$("ap-rec-status-label").hidden=!recommendation;$("ap-rec-priority-label").hidden=!recommendation||mode==="bid";
    $("ap-diagnosis-kpis").hidden=!diagnosis;$("ap-diagnosis-period-label").hidden=!diagnosis;$("ap-diagnosis-action-label").hidden=!diagnosis;$("ap-diagnosis-action-panel").hidden=!diagnosis;$("ap-targeting").closest("label").hidden=diagnosis;$("ap-trend-modes").hidden=diagnosis;
    updateObjectFilterVisibility();$("ap-msku-label-text").textContent=diagnosis?"MSKU / ASIN 搜索":"关联 MSKU";$("ap-msku").placeholder=diagnosis?"MSKU 或 ASIN":"MSKU";
    if(governance){var gb=state.governanceOptions&&state.governanceOptions.batch;if(gb){$("ap-governance-batch").textContent="成熟区间 "+gb.mature_start+" 至 "+gb.mature_end;$("ap-data-date").textContent="成熟区间 "+gb.mature_start+" 至 "+gb.mature_end;$("ap-updated").textContent="治理批次 "+gb.batch_id+" · 数据截止 "+gb.cutoff_date;}}
    else if(recommendation){fillRecommendationStatuses(mode);$("ap-view-title").textContent=recMeta[mode][0];$("ap-view-note").textContent=recMeta[mode][1];var rule=(state.recOptions&&state.recOptions.rules||{})[mode]||"";$("ap-rule-copy").querySelector("span").textContent=rule;var batch=state.recOptions&&state.recOptions.batch;if(batch){$("ap-data-date").textContent="成熟区间 "+batch.mature_start+" 至 "+batch.mature_end;$("ap-updated").textContent="数据截止 "+batch.cutoff_date+" · 规则 "+batch.rule_version;}}
    else if(diagnosis){var db=state.diagnosisOptions&&state.diagnosisOptions.batch;$("ap-view-title").textContent="产品诊断";$("ap-view-note").textContent="每行代表店铺＋站点＋MSKU；经营、SP广告和最新建议在同一产品层级展示。";if(db){$("ap-data-date").textContent="截至 "+db.data_end;$("ap-updated").textContent="产品诊断批次 "+db.batch_id+" · 建议批次 "+db.recommendation_batch_id;}}
    else if(state.options){$("ap-data-date").textContent="截至 "+state.options.max_date;$("ap-updated").textContent="批次 "+state.options.batch_id+" · "+text(state.options.updated_at);$("ap-view-title").textContent=viewMeta[state.view][0];$("ap-view-note").textContent=viewMeta[state.view][1];}
  }
  async function loadRecommendations(signal,requestId) {
    renderBidType();
    function recFetch(path){return fetch(recommendationEndpoint(path),{signal:signal}).then(async function(r){if(!r.ok)throw new Error((await r.json()).detail||"建议读取失败");return r.json();});}
    recFetch("summary").then(function(result){if(requestId===state.requestId)renderRecommendationSummary(result.summary);}).catch(function(error){if(error.name!=="AbortError")showError(error);});
    var payload=await recFetch("rows");if(requestId===state.requestId)renderRecommendationRows(payload);
  }
  async function loadDiagnosis(signal,requestId){
    function get(path){return fetch(diagnosisEndpoint(path),{signal:signal}).then(async function(r){if(!r.ok)throw new Error((await r.json()).detail||"产品诊断读取失败");return r.json();});}
    get("summary").then(function(result){if(requestId===state.requestId)renderDiagnosisSummary(result.summary);}).catch(function(error){if(error.name!=="AbortError")showError(error);});
    get("trend").then(function(result){if(requestId===state.requestId)renderDiagnosisTrend(result.rows);}).catch(function(error){if(error.name!=="AbortError")showError(error);});
    var payload=await get("rows");if(requestId===state.requestId)renderDiagnosisRows(payload);
  }
  async function load() {
    if (state.controller) state.controller.abort(); state.controller = new AbortController(); var signal = state.controller.signal, requestId=++state.requestId; hideError(); renderTags();
    $("ap-table-panel").classList.add("ap-loading");$("ap-table-panel").setAttribute("aria-busy","true");$("ap-page-summary").textContent="正在加载"+viewMeta[state.view][0]+"…";
    function sectionError(error){if(requestId===state.requestId&&error.name!=="AbortError")showError(error);}
    if(state.mode==="governance"){try{await loadGovernance();}catch(error){sectionError(error);}finally{if(requestId===state.requestId){$("ap-table-panel").classList.remove("ap-loading");$("ap-table-panel").setAttribute("aria-busy","false");}}return;}
    if(isRecommendationMode(state.mode)){try{await loadRecommendations(signal,requestId);}catch(error){sectionError(error);}finally{if(requestId===state.requestId){$("ap-table-panel").classList.remove("ap-loading");$("ap-table-panel").setAttribute("aria-busy","false");}}return;}
    if(state.mode==="diagnosis"){try{await loadDiagnosis(signal,requestId);}catch(error){sectionError(error);}finally{if(requestId===state.requestId){$("ap-table-panel").classList.remove("ap-loading");$("ap-table-panel").setAttribute("aria-busy","false");}}return;}
    json("summary",signal).then(function(result){if(requestId===state.requestId)renderSummary(result.summary);}).catch(sectionError);
    json("trend",signal).then(function(result){if(requestId===state.requestId)renderTrend(result.rows);}).catch(sectionError);
    try { var rows = await json("rows", signal);if(requestId!==state.requestId)return;renderRows(rows); }
    catch (error) { if (requestId===state.requestId&&error.name !== "AbortError") showError(error); }
    finally {if(requestId===state.requestId){$("ap-table-panel").classList.remove("ap-loading");$("ap-table-panel").setAttribute("aria-busy","false");}}
  }
  function drawerName(row) { return row.msku || row.keyword_text || row.search_term || row.ad_group_name_current || row.campaign_name_current || "效果详情"; }
  async function openDetail(row) {
    if(row.__recommendation){return openRecommendationDetail(row);}
    if(row.__diagnosis){return openDiagnosisDetail(row);}
    var sourceView=row.__view||state.view;
    $("ap-drawer-title").textContent = drawerName(row); $("ap-drawer-content").innerHTML = "<p>正在读取详情…</p>"; $("ap-drawer-backdrop").hidden=false; $("ap-drawer").classList.add("open"); $("ap-drawer").setAttribute("aria-hidden","false");
    try { var detailParams={view:sourceView,key:row.item_key};["profile_id","campaign_id","ad_group_id"].forEach(function(k){if(row[k])detailParams[k]=row[k];});var data=await json("detail", null, detailParams); var item=data.item;
      var labels=[["店铺",item.seller_name],["站点",item.country_code],["MSKU",item.msku],["ASIN",item.asin],["活动（当前）",item.campaign_name_current],["广告组（当前）",item.ad_group_name_current],["关键词",item.keyword_text],["搜索词",item.search_term],["匹配方式",item.match_type],["当前状态",item.object_state_current]];
      var html='<div class="ap-detail-grid">'+labels.filter(function(x){return x[1]!==undefined&&x[1]!==null;}).map(function(x){return '<div><span>'+escapeHtml(x[0])+'</span><strong title="'+escapeHtml(text(x[1]))+'">'+escapeHtml(text(x[1]))+'</strong></div>';}).join("")+'</div><section class="ap-detail-trend-section"><h3>每日趋势</h3><div id="ap-detail-trend"></div></section><div class="ap-window-grid">';
      [1,7,14,30].forEach(function(w){var x=data.windows[String(w)]||{};html+='<div class="ap-window-card"><span>'+w+' 天归因</span><strong>ACOS '+percent(x.acos)+'</strong><small>订单 '+number(x.orders,0)+' · 销售额 '+number(x.sales)+'</small></div>';}); html+='</div>';
      if(sourceView!=="product"&&Number(item.associated_msku_count)>1) html+='<p class="ap-associated-note">当前广告组关联 '+item.associated_msku_count+' 个 MSKU。本页效果属于广告组或投放对象，不能视为某个 MSKU 独占效果。</p>';
      if(sourceView==="product") html+='<div class="ap-drills"><button type="button" data-drill="ad_group">查看相关广告组</button></div>';
      if(sourceView==="campaign") html+='<div class="ap-drills"><button type="button" data-drill="ad_group">查看活动下的广告组</button></div>';
      if(sourceView==="ad_group") html+='<div class="ap-drills"><button type="button" data-drill="keyword">查看关键词</button><button type="button" data-drill="search_term">查看搜索词</button></div>';
      $("ap-drawer-content").innerHTML=html;
      var detailChart=echarts.init($("ap-detail-trend"));detailChart.setOption({animationDuration:220,color:["#2563eb","#f59e0b"],tooltip:{trigger:"axis"},legend:{top:0,data:["花费","销售额"]},grid:{left:46,right:12,top:35,bottom:28},xAxis:{type:"category",data:(data.trend||[]).map(function(x){return x.report_date;})},yAxis:{type:"value",splitLine:{lineStyle:{color:"#edf1f6"}}},series:[{name:"花费",type:"line",symbol:"none",smooth:true,data:(data.trend||[]).map(function(x){return x.cost;})},{name:"销售额",type:"line",symbol:"none",smooth:true,data:(data.trend||[]).map(function(x){return x.sales;})}]});
      $("ap-drawer-content").querySelectorAll("[data-drill]").forEach(function(button){button.onclick=function(){
        var target=button.dataset.drill;state.scope={profile_id:item.profile_id};if(item.campaign_id)state.scope.campaign_id=item.campaign_id;if(item.ad_group_id)state.scope.ad_group_id=item.ad_group_id;
        if(sourceView==="product") $("ap-msku").value=item.msku||"";
        switchView(target,true);if(item.msku)$("ap-view-note").textContent="关联广告组表现，可能包含其他商品；关联筛选不会重复计算指标。";closeDrawer();load();
      };});
    } catch(error){$("ap-drawer-content").innerHTML='<p>详情读取失败：'+escapeHtml(error.message)+'</p>';}
  }
  function switchToRecommendation(kind,item){state.mode=kind;$("ap-store").value=item.seller_name||"";$("ap-country").value=item.country_code||"";$("ap-msku").value=item.msku||"";closeDrawer();switchMode(kind);$("ap-store").value=item.seller_name||"";$("ap-country").value=item.country_code||"";$("ap-msku").value=item.msku||"";load();}
  async function openDiagnosisDetail(row){
    $("ap-drawer-title").textContent=row.msku||"产品诊断";$("ap-drawer-content").innerHTML="<p>正在读取产品诊断…</p>";$("ap-drawer-backdrop").hidden=false;$("ap-drawer").classList.add("open");$("ap-drawer").setAttribute("aria-hidden","false");
    try{var response=await fetch(diagnosisEndpoint("detail",{key:row.diagnosis_key}));if(!response.ok)throw new Error((await response.json()).detail||"详情读取失败");var data=await response.json(),item=data.item;
      var fields=[["店铺",item.seller_name],["站点",item.country_code],["MSKU",item.msku],["ASIN",item.asin],["经营销量",number(item.operating_sales_qty,0)],["经营销售额",money(item.operating_sales_amount,"CNY")],["经营毛利润",money(item.operating_gross_profit,"CNY")],["毛利率",percent(item.operating_gross_margin)],["会话",number(item.operating_sessions,0)],["退货量",number(item.operating_return_count,0)],["退货额",money(item.operating_return_amount,"CNY")],["净销售额",money(item.operating_net_amount,"CNY")],["FBA可售库存",number(item.operating_inventory_qty,0)],["广告花费",money(item.ad_cost,item.currency_code)],["月预算",money(item.monthly_ad_budget_cny,"CNY")],["本月已用",money(item.month_spend_cny,"CNY")],["剩余预算",money(item.remaining_budget_cny,"CNY")],["预算使用率",percent(item.budget_usage_rate)],["提价支持",item.budget_support_status],["预算快照日期",item.budget_snapshot_date],["花费截止日期",item.budget_performance_date],["数据提示",item.data_warning]];
      var html='<p class="ap-readonly-note">仅展示分析和建议，不会修改广告。</p><div class="ap-detail-grid">'+fields.filter(function(x){return x[1]!==null&&x[1]!==undefined;}).map(function(x){return '<div><span>'+escapeHtml(x[0])+'</span><strong>'+escapeHtml(text(x[1]))+'</strong></div>';}).join("")+'</div><div class="ap-window-grid">';
      [1,7,14,30].forEach(function(w){var x=data.windows[String(w)]||{};html+='<div class="ap-window-card"><span>'+w+'天归因</span><strong>ACOS '+percent(x.acos)+'</strong><small>订单 '+number(x.ad_orders,0)+' · 销售额 '+money(x.ad_sales,item.currency_code)+'</small></div>';});
      var counts=data.suggestion_counts||{};
      html+='</div><section class="ap-detail-trend-section"><h3>每日经营与广告趋势</h3><div id="ap-detail-trend"></div></section><section class="ap-reasons"><h3>具体处理建议</h3><p>调整竞价 '+(counts.bid_adjust||0)+' 条 · 建议加词 '+(counts.add||0)+' 条 · 建议否词 '+(counts.negative||0)+' 条 · 人工审核 '+(counts.manual_review||0)+' 条</p><div class="ap-drills"><button data-recommendation="bid">查看竞价建议</button><button data-recommendation="add">查看加词建议</button><button data-recommendation="negative">查看否词建议</button></div></section>';
      $("ap-drawer-content").innerHTML=html;var chart=echarts.init($("ap-detail-trend"));chart.setOption({tooltip:{trigger:"axis"},legend:{data:["经营销售额","广告花费"]},xAxis:{type:"category",data:data.daily.map(function(x){return x.report_date;})},yAxis:{type:"value"},series:[{name:"经营销售额",type:"line",symbol:"none",data:data.daily.map(function(x){return x.operating_sales_amount;})},{name:"广告花费",type:"line",symbol:"none",data:data.daily.map(function(x){return x.ad_cost;})}]});
      $("ap-drawer-content").querySelectorAll("[data-recommendation]").forEach(function(button){button.onclick=function(){switchToRecommendation(button.dataset.recommendation,item);};});
    }catch(error){$("ap-drawer-content").innerHTML='<p>详情读取失败：'+escapeHtml(error.message)+'</p>';}
  }
  async function openRecommendationDetail(row) {
    $("ap-drawer-title").textContent=row.suggestion_value||row.object_text||"建议详情";$("ap-drawer-content").innerHTML="<p>正在读取建议详情…</p>";$("ap-drawer-backdrop").hidden=false;$("ap-drawer").classList.add("open");$("ap-drawer").setAttribute("aria-hidden","false");
    try{var response=await fetch(recommendationEndpoint("detail",{kind:row.__kind,key:row.recommendation_key}));if(!response.ok)throw new Error((await response.json()).detail||"建议详情读取失败");var data=await response.json(),item=data.item;
      var fields=[["建议动作",statusLabel(item.status,row.__kind)],["人工审核原因",item.data_warning],["候选内容",item.suggestion_value||item.object_text],["建议类型",item.suggestion_type?suggestionLabel(item.suggestion_type):item.object_type],["命中品牌",item.protection_brand],["命中核心类目",item.protection_category],["首单/开售日期",item.product_launch_date],["产品天数",item.product_age_days],["当前竞价",money(item.current_bid,item.currency_code)],["建议竞价",money(item.suggested_bid,item.currency_code)],["允许最高建议竞价",money(item.max_allowed_bid,item.currency_code)],["调整金额",money(item.change_amount,item.currency_code)],["调整比例",percent(item.change_rate)],["Listing价格",money(item.listing_price,item.currency_code)],["定价毛利率",percent(item.margin_rate)],["理论CPC",money(item.theoretical_cpc,item.currency_code)],["定价映射",item.listing_mapping_status],["月预算",money(item.monthly_ad_budget_cny,"CNY")],["本月已用",money(item.month_spend_cny,"CNY")],["剩余预算",money(item.remaining_budget_cny,"CNY")],["预算使用率",percent(item.budget_usage_rate)],["提价支持",budgetSupportLabel(item)],["预算快照日期",item.budget_snapshot_date],["预算花费截止",item.budget_performance_date],["店铺",item.seller_name],["站点",item.country_code],["MSKU",item.msku],["活动（当前）",item.campaign_name_current],["广告组（当前）",item.ad_group_name_current],["点击",item.clicks],["CVR",percent(item.cvr)],["ACOS",percent(item.acos)],["花费",money(item.cost,item.currency_code)],["订单",item.orders],["销售额",money(item.sales,item.currency_code)]];
      $("ap-drawer-content").innerHTML='<p class="ap-readonly-note">仅供人工决策参考，不会修改广告。</p><div class="ap-detail-grid">'+fields.filter(function(x){return x[1]!==null&&x[1]!==undefined&&x[1]!=="—";}).map(function(x){return '<div><span>'+escapeHtml(x[0])+'</span><strong title="'+escapeHtml(text(x[1]))+'">'+escapeHtml(text(x[1]))+'</strong></div>';}).join("")+'</div><section class="ap-reasons"><h3>计算与保护原因</h3><p>'+escapeHtml((item.reason_codes||[]).map(reasonLabel).join("、")||"—")+'</p></section>';
    }catch(error){$("ap-drawer-content").innerHTML='<p>详情读取失败：'+escapeHtml(error.message)+'</p>';}
  }
  function closeDrawer(){$("ap-drawer").classList.remove("open");$("ap-drawer").setAttribute("aria-hidden","true");$("ap-drawer-backdrop").hidden=true;}
  async function init() {
    try { state.options=await fetch("/api/ad-performance/options").then(function(r){if(!r.ok)throw new Error("选项读取失败");return r.json();});
      $("ap-start").value=state.options.min_date;$("ap-end").value=state.options.max_date;fillSelect("ap-currency",state.options.currencies,"value");$("ap-currency").value=state.options.default_currency;
      fillDatalist("ap-store-options",state.options.stores);fillDatalist("ap-country-options",state.options.countries);$("ap-data-date").textContent="截至 "+state.options.max_date;$("ap-updated").textContent="批次 "+state.options.batch_id+" · "+text(state.options.updated_at);
      state.recOptions=await fetch("/api/ad-performance/recommendations/options").then(function(r){return r.ok?r.json():{status:"no_data",rules:{}};});
      state.diagnosisOptions=await fetch("/api/ad-performance/product-diagnosis/options").then(function(r){return r.ok?r.json():{status:"no_data"};});
      state.governanceOptions=await fetch("/api/ad-performance/governance/options").then(function(r){return r.ok?r.json():{status:"no_data",base_stores:[],sites:[]};});fillDatalist("ap-governance-store-options",state.governanceOptions.base_stores||[]);fillDatalist("ap-governance-site-options",(state.governanceOptions.sites||[]).map(function(x){return x.seller_name;}));switchMode(state.mode);await load();
    } catch(error){showError(error);}
  }
  $("ap-query").onclick=function(){state.page=1;state.scope={};load();}; $("ap-reset").onclick=function(){["ap-store","ap-country","ap-targeting","ap-campaign","ap-ad-group","ap-keyword-text","ap-search-term","ap-msku","ap-rec-status","ap-rec-priority","ap-diagnosis-action"].forEach(function(id){$(id).value="";});$("ap-diagnosis-period").value="30d";$("ap-currency").value=state.options.default_currency;$("ap-start").value=state.options.min_date;$("ap-end").value=state.options.max_date;state.scope={};state.trendMode="amount";$("ap-trend-modes").querySelectorAll("button[data-mode]").forEach(function(x){x.classList.toggle("active",x.dataset.mode==="amount");});state.page=1;load();};
  ["ap-store","ap-country","ap-campaign","ap-ad-group","ap-keyword-text","ap-search-term","ap-msku"].forEach(function(id){$(id).addEventListener("keydown",function(event){if(event.key==="Enter"){event.preventDefault();$("ap-query").click();}});});
  $("ap-windows").onclick=function(e){var b=e.target.closest("button");if(!b)return;state.window=Number(b.dataset.window);$("ap-windows").querySelectorAll("button").forEach(function(x){x.classList.toggle("active",x===b);});state.page=1;load();};
  $("ap-tabs").onclick=function(e){var b=e.target.closest("button");if(!b)return;switchView(b.dataset.view,false);load();};
  $("ap-page-size").onchange=function(){state.pageSize=Number(this.value);state.page=1;load();};$("ap-prev").onclick=function(){if(state.page>1){state.page--;load();}};$("ap-next").onclick=function(){if(state.page*state.pageSize<state.total){state.page++;load();}};
  $("ap-export").onclick=function(){window.location.href=state.mode==="overview"?endpoint("export"):state.mode==="diagnosis"?diagnosisEndpoint("export"):recommendationEndpoint("export");};$("ap-columns").onclick=function(){if(state.grid&&state.grid.showColumnChooser)state.grid.showColumnChooser();};
  $("ap-trend-toggle").onclick=function(){var chart=$("ap-trend"),hidden=!chart.hidden;chart.hidden=hidden;this.textContent=hidden?"展开":"收起";this.setAttribute("aria-expanded",String(!hidden));if(!hidden&&state.chart)state.chart.resize();};
  $("ap-trend-modes").onclick=function(e){var b=e.target.closest("button[data-mode]");if(!b)return;state.trendMode=b.dataset.mode;$("ap-trend-modes").querySelectorAll("button[data-mode]").forEach(function(x){x.classList.toggle("active",x===b);});renderTrend(state.trendRows);};
  $("ap-filter-tags").onclick=function(e){var b=e.target.closest("button[data-clear]");if(!b)return;if(b.dataset.scope==="1")delete state.scope[b.dataset.clear];else $(b.dataset.clear).value="";state.page=1;load();};
  $("ap-rec-status-cards").onclick=function(e){var button=e.target.closest("button[data-rec-status]");if(button)applyRecommendationStatus(button.dataset.recStatus||"");};
  $("ap-bid-types").onclick=function(e){
    var button=e.target.closest("button[data-bid-type]");if(!button||button.dataset.bidType===state.bidType)return;
    state.bidType=button.dataset.bidType;state.page=1;closeDrawer();renderBidType();load();
  };
  $("ap-analysis-tabs").onclick=function(e){var b=e.target.closest("button[data-mode]");if(!b)return;switchMode(b.dataset.mode);load();};
  $("ap-governance-query").onclick=function(){state.governanceCampaignId=null;state.governanceAdGroupId=null;state.governanceLevel="campaign";renderGovernanceLevel();load();};
  $("ap-governance-reset").onclick=function(){["ap-governance-base-store","ap-governance-store","ap-governance-country","ap-governance-targeting","ap-governance-action","ap-governance-keyword"].forEach(function(id){$(id).value="";});$("ap-governance-state").value="active";state.governanceCampaignId=null;state.governanceAdGroupId=null;state.governanceLevel="campaign";renderGovernanceLevel();load();};
  ["ap-governance-base-store","ap-governance-store","ap-governance-country","ap-governance-keyword"].forEach(function(id){$(id).addEventListener("keydown",function(event){if(event.key==="Enter"){event.preventDefault();$("ap-governance-query").click();}});});
  $("ap-governance-store-list").onclick=function(event){var button=event.target.closest("[data-base-store]");if(!button)return;$("ap-governance-base-store").value=button.dataset.baseStore||"";$("ap-governance-store").value="";$("ap-governance-country").value="";state.governanceCampaignId=null;state.governanceAdGroupId=null;state.governanceLevel="campaign";renderGovernanceLevel();load();};
  $("ap-governance-sites").onclick=function(event){var button=event.target.closest("[data-governance-store]");if(!button)return;$("ap-governance-store").value=button.dataset.governanceStore||"";$("ap-governance-country").value=button.dataset.governanceCountry||"";state.governanceCampaignId=null;state.governanceAdGroupId=null;load();};
  $("ap-governance-levels").onclick=function(event){var button=event.target.closest("button[data-level]");if(!button)return;state.governanceLevel=button.dataset.level;state.governanceCampaignId=null;state.governanceAdGroupId=null;renderGovernanceLevel();loadGovernanceEntities().catch(showError);};
  $("ap-governance-panel").querySelector(".ap-governance-action-cards").onclick=function(event){var button=event.target.closest("[data-governance-card]");if(button)switchGovernanceRecommendation(button.dataset.governanceCard,null);};
  $("ap-diagnosis-period").onchange=function(){state.page=1;load();};$("ap-diagnosis-action").onchange=function(){state.page=1;load();};
  $("ap-drawer-close").onclick=closeDrawer;$("ap-drawer-backdrop").onclick=closeDrawer;$("ap-error").querySelector("button").onclick=load;window.addEventListener("resize",function(){if(state.chart)state.chart.resize();if(state.recStatusChart)state.recStatusChart.resize();});init();
}());

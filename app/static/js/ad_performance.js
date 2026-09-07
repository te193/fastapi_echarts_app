(function () {
  "use strict";
  var state = { mode: "overview", bidType: "ad_group", view: "product", window: 7, page: 1, pageSize: 50, sort: "cost", direction: "desc", total: 0, options: null, recOptions: null, grid: null, chart: null, controller: null, requestId: 0, trendMode: "amount", trendRows: [], scope: {} };
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
  function params(extra) {
    var p = new URLSearchParams({ view: state.view, window: state.window, start: $("ap-start").value, end: $("ap-end").value,
      currency: $("ap-currency").value, store: $("ap-store").value, country: $("ap-country").value,
      targeting: $("ap-targeting").value, keyword: $("ap-keyword").value.trim(), msku: $("ap-msku").value.trim(),
      page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction });
    Object.keys(state.scope).forEach(function (key) { if (state.scope[key] !== null && state.scope[key] !== undefined && state.scope[key] !== "") p.set(key, state.scope[key]); });
    Object.keys(extra || {}).forEach(function (key) { p.set(key, extra[key]); });
    return p;
  }
  function endpoint(path, extra) { return "/api/ad-performance/" + path + "?" + params(extra).toString(); }
  function recommendationParams(extra) {
    var p = new URLSearchParams({ kind: state.mode, currency: $("ap-currency").value, store: $("ap-store").value,
      country: $("ap-country").value, targeting: $("ap-targeting").value, status: $("ap-rec-status").value,
      priority: $("ap-rec-priority").value, keyword: $("ap-keyword").value.trim(), msku: $("ap-msku").value.trim(),
      page: state.page, page_size: state.pageSize, sort: state.sort, direction: state.direction });
    if (state.mode === "bid") p.set("object_type", state.bidType);
    Object.keys(extra || {}).forEach(function (key) { p.set(key, extra[key]); }); return p;
  }
  function recommendationEndpoint(path, extra) { return "/api/ad-performance/recommendations/" + path + "?" + recommendationParams(extra).toString(); }
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
  function renderRecommendationSummary(row) {
    $("ap-rec-total").textContent=number(row.total,0);$("ap-rec-recommended").textContent=number(row.recommended,0);
    $("ap-rec-review").textContent=number(row.manual_review,0);$("ap-rec-cost").textContent=number(row.cost);
    $("ap-rec-sales").textContent=number(row.sales);$("ap-rec-currency").textContent=$("ap-currency").selectedOptions[0] ? $("ap-currency").selectedOptions[0].textContent : "成熟30天";
  }
  function renderSummary(row) {
    $("ap-cost").textContent = number(row.cost); $("ap-sales").textContent = number(row.sales); $("ap-orders").textContent = number(row.orders, 0);
    $("ap-impressions").textContent = number(row.impressions, 0); $("ap-clicks").textContent = number(row.clicks, 0); $("ap-acos").textContent = percent(row.acos);
    $("ap-cvr").textContent = "CVR " + percent(row.cvr); $("ap-ctr").textContent = "CTR " + percent(row.ctr); $("ap-cpc").textContent = "CPC " + number(row.cpc);
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
      { field: "ctr", headerName: "CTR", width: 90, valueFormatter: function(p){return percent(p.value);} }, { field: "cost", headerName: "花费", width: 105, valueFormatter: function(p){return number(p.value);} },
      { field: "cpc", headerName: "CPC", width: 90, valueFormatter: function(p){return number(p.value);} }, { field: "orders", headerName: "订单", width: 90, valueFormatter: function(p){return number(p.value,0);} },
      { field: "units", headerName: "销量", width: 90, valueFormatter: function(p){return number(p.value,0);} }, { field: "sales", headerName: "销售额", width: 110, valueFormatter: function(p){return number(p.value);} },
      { field: "cvr", headerName: "CVR", width: 90, valueFormatter: function(p){return percent(p.value);} }, { field: "acos", headerName: "ACOS", width: 95, valueFormatter: function(p){return percent(p.value);} },
      { field: "roas", headerName: "ROAS", width: 95, valueFormatter: function(p){return number(p.value);} },
      { field: "same_orders", headerName: "直接订单", width: 105, hide: true }, { field: "same_sales", headerName: "直接销售额", width: 120, hide: true },
      { headerName: "详情", width: 82, pinned: "right", sortable: false, filter: false, cellRenderer: function(){return '<button class="ap-detail-button">查看</button>';}, onCellClicked: function(p){openDetail(p.data);} }];
    return common.concat(objects, metrics);
  }
  function statusLabel(value, kind) {
    if(kind==="add") return ({recommended:"建议新增",manual_review:"先核对商品归属",existing:"无需新增（已存在）",observe:"暂不新增（未达标准）"})[value] || text(value);
    if(kind==="negative") return ({recommended:"建议否定",manual_review:"人工审核",existing:"无需否定（已存在）",observe:"暂不否定（未达标准）"})[value] || text(value);
    return ({increase:"建议提价",decrease:"建议降价",keep:"建议保持",manual_review:"人工复核",insufficient_data:"数据不足"})[value] || text(value);
  }
  function suggestionLabel(value) { return ({exact_keyword:"新增精准关键词",product_target:"新增商品投放",negative_exact:"精准否定",negative_product_target:"否定商品投放"})[value] || text(value); }
  function priorityLabel(value) { return ({highest:"最高",high:"高",medium:"中",none:"—"})[value] || text(value); }
  function reasonLabel(value) { return ({theoretical_cpc_guard:"按定价毛利段理论CPC调整",inventory_blocks_increase:"库存保护阻止提价",budget_blocks_increase:"自然月预算保护阻止提价",metric_missing:"点击、订单、当前竞价或价格数据不足",multiple_msku:"广告组关联多个MSKU",msku_missing:"广告组未映射MSKU",price_not_mapped:"Listing价格未匹配",margin_ladder_missing:"毛利价格阶梯缺失",below_zero_margin_price:"当前价格低于0%毛利价格",existing_enabled:"同广告组已存在启用对象",orders_ge_10_acos_le_10:"订单不少于10且ACOS不高于10%",orders_ge_10_acos_le_15:"订单不少于10且ACOS不高于15%",clicks_ge_10_orders_zero:"点击不少于10且订单为0",threshold_not_met:"未达到建议阈值",term_protection_context_missing:"未匹配Listing保护信息",brand_context_missing:"产品品牌信息缺失",category_context_missing:"本地化叶子类目信息缺失",launch_date_missing:"首单及开售日期缺失",launch_date_invalid:"首单或开售日期异常",brand_term:"品牌词保护",core_category_term:"核心类目词保护",new_product_term:"新品推广词保护"})[value] || text(value); }
  function recommendationColumns(kind) {
    var common=[objectColumn("seller_name","店铺",140),{field:"country_code",headerName:"站点",width:82},objectColumn("msku","MSKU",145)];
    var metric=[{field:"clicks",headerName:"点击",width:88,valueFormatter:function(p){return number(p.value,0);}},{field:"cost",headerName:"花费",width:98,valueFormatter:function(p){return number(p.value);}},{field:"orders",headerName:"订单",width:88,valueFormatter:function(p){return number(p.value,0);}},{field:"sales",headerName:"销售额",width:105,valueFormatter:function(p){return number(p.value);}}];
    var detail={headerName:"详情",width:78,pinned:"right",sortable:false,filter:false,cellRenderer:function(){return '<button class="ap-detail-button">查看</button>';},onCellClicked:function(p){openDetail(p.data);}};
    if(kind==="bid") return common.concat([objectColumn("object_text",state.bidType==="ad_group"?"广告组（当前）":"关键词",190),{field:"match_type",headerName:"匹配",width:90,hide:state.bidType==="ad_group"},{field:"current_bid",headerName:"当前竞价",width:105,valueFormatter:function(p){return number(p.value);}},{field:"suggested_bid",headerName:"建议竞价",width:105,valueFormatter:function(p){return number(p.value);}},{field:"change_amount",headerName:"调整金额",width:108,valueFormatter:function(p){return p.value===null?"—":(Number(p.value)>0?"提高 ":Number(p.value)<0?"降低 ":"保持 ")+number(Math.abs(Number(p.value)));}},{field:"change_rate",headerName:"调整比例",width:100,valueFormatter:function(p){return percent(p.value);}},{field:"theoretical_cpc",headerName:"理论CPC",width:105,valueFormatter:function(p){return number(p.value);} }].concat(metric,[{field:"status",headerName:"建议",width:105,valueFormatter:function(p){return statusLabel(p.value);}},detail]));
    return common.concat([objectColumn("suggestion_value",kind==="add"?"候选新增内容":"候选否定内容",210),{field:"suggestion_type",headerName:"建议类型",width:135,valueFormatter:function(p){return suggestionLabel(p.value);}},{field:"status",headerName:"建议动作",width:145,valueFormatter:function(p){return statusLabel(p.value,kind);}},{field:"data_warning",headerName:kind==="negative"?"人工审核原因":"数据提示",width:285,sortable:false,filter:false,cellRenderer:function(p){return '<span class="ap-data-warning" title="'+escapeHtml(text(p.value))+'">'+escapeHtml(text(p.value))+'</span>'; }},{field:"priority",headerName:"优先级",width:90,valueFormatter:function(p){return priorityLabel(p.value);}},objectColumn("campaign_name_current","广告活动（当前）",170),objectColumn("ad_group_name_current","广告组（当前）",170)].concat(metric,[{field:"acos",headerName:"ACOS",width:90,valueFormatter:function(p){return percent(p.value);}},detail]));
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
    var tags = []; [["店铺", "ap-store"],["站点", "ap-country"],["投放", "ap-targeting"],["搜索", "ap-keyword"],["MSKU", "ap-msku"]].forEach(function(x){if($(x[1]).value) tags.push({label:x[0]+"："+$(x[1]).value,key:x[1]});});
    [["广告账号", "profile_id"],["活动", "campaign_id"],["广告组", "ad_group_id"]].forEach(function(x){if(state.scope[x[1]])tags.push({label:x[0]+"："+state.scope[x[1]],key:x[1],scope:true});});
    $("ap-filter-tags").innerHTML = tags.map(function(t){return '<button type="button" data-clear="'+escapeHtml(t.key)+'" data-scope="'+(t.scope?"1":"0")+'">'+escapeHtml(t.label)+' ×</button>';}).join("");
  }
  function switchView(view, keepScope) {
    state.view=view;state.page=1;state.sort="cost";state.direction="desc";if(!keepScope)state.scope={};
    $("ap-tabs").querySelectorAll("button").forEach(function(x){x.classList.toggle("active",x.dataset.view===view);});
    $("ap-view-title").textContent=viewMeta[view][0];$("ap-view-note").textContent=viewMeta[view][1];
  }
  function fillRecommendationStatuses(mode) {
    var values=mode==="bid"?[["increase","建议提价"],["decrease","建议降价"],["keep","建议保持"],["manual_review","人工复核"],["insufficient_data","数据不足"]]:mode==="add"?[["recommended","建议新增"],["existing","无需新增（已存在）"],["observe","暂不新增（未达标准）"]]:[["recommended","建议否定"],["manual_review","人工审核"],["existing","无需否定（已存在）"],["observe","暂不否定（未达标准）"]];
    $("ap-rec-status").innerHTML='<option value="">全部状态</option>'+values.map(function(x){return '<option value="'+x[0]+'">'+x[1]+'</option>';}).join("");
  }
  function renderBidType() {
    $("ap-bid-types").hidden=state.mode!=="bid";
    $("ap-bid-types").querySelectorAll("button").forEach(function(button){
      var active=button.dataset.bidType===state.bidType;
      button.classList.toggle("active",active);button.setAttribute("aria-pressed",String(active));
    });
    if(state.mode==="bid") $("ap-view-note").textContent=state.bidType==="ad_group"?
      "自动广告组默认竞价：展示当前默认竞价、建议竞价和调整金额。":
      "关键词竞价：按所属广告组和匹配方式分别展示当前竞价、建议竞价和调整金额。";
  }
  function switchMode(mode) {
    state.mode=mode;renderBidType();state.page=1;state.sort="cost";state.direction="desc";state.scope={};
    $("ap-analysis-tabs").querySelectorAll("button[data-mode]").forEach(function(x){x.classList.toggle("active",x.dataset.mode===mode);});
    var recommendation=mode!=="overview";["ap-window-bar","ap-kpis","ap-trend-panel","ap-tabs","ap-start-label","ap-end-label"].forEach(function(id){$(id).hidden=recommendation;});
    $("ap-rec-kpis").hidden=!recommendation;$("ap-rule-copy").hidden=!recommendation;$("ap-rec-status-label").hidden=!recommendation;$("ap-rec-priority-label").hidden=!recommendation||mode==="bid";
    if(recommendation){fillRecommendationStatuses(mode);$("ap-view-title").textContent=recMeta[mode][0];$("ap-view-note").textContent=recMeta[mode][1];var rule=(state.recOptions&&state.recOptions.rules||{})[mode]||"";$("ap-rule-copy").querySelector("span").textContent=rule;var batch=state.recOptions&&state.recOptions.batch;if(batch){$("ap-data-date").textContent="成熟区间 "+batch.mature_start+" 至 "+batch.mature_end;$("ap-updated").textContent="数据截止 "+batch.cutoff_date+" · 规则 "+batch.rule_version;}}
    else if(state.options){$("ap-data-date").textContent="截至 "+state.options.max_date;$("ap-updated").textContent="批次 "+state.options.batch_id+" · "+text(state.options.updated_at);$("ap-view-title").textContent=viewMeta[state.view][0];$("ap-view-note").textContent=viewMeta[state.view][1];}
  }
  async function loadRecommendations(signal,requestId) {
    renderBidType();
    function recFetch(path){return fetch(recommendationEndpoint(path),{signal:signal}).then(async function(r){if(!r.ok)throw new Error((await r.json()).detail||"建议读取失败");return r.json();});}
    recFetch("summary").then(function(result){if(requestId===state.requestId)renderRecommendationSummary(result.summary);}).catch(function(error){if(error.name!=="AbortError")showError(error);});
    var payload=await recFetch("rows");if(requestId===state.requestId)renderRecommendationRows(payload);
  }
  async function load() {
    if (state.controller) state.controller.abort(); state.controller = new AbortController(); var signal = state.controller.signal, requestId=++state.requestId; hideError(); renderTags();
    $("ap-table-panel").classList.add("ap-loading");$("ap-table-panel").setAttribute("aria-busy","true");$("ap-page-summary").textContent="正在加载"+viewMeta[state.view][0]+"…";
    function sectionError(error){if(requestId===state.requestId&&error.name!=="AbortError")showError(error);}
    if(state.mode!=="overview"){try{await loadRecommendations(signal,requestId);}catch(error){sectionError(error);}finally{if(requestId===state.requestId){$("ap-table-panel").classList.remove("ap-loading");$("ap-table-panel").setAttribute("aria-busy","false");}}return;}
    json("summary",signal).then(function(result){if(requestId===state.requestId)renderSummary(result.summary);}).catch(sectionError);
    json("trend",signal).then(function(result){if(requestId===state.requestId)renderTrend(result.rows);}).catch(sectionError);
    try { var rows = await json("rows", signal);if(requestId!==state.requestId)return;renderRows(rows); }
    catch (error) { if (requestId===state.requestId&&error.name !== "AbortError") showError(error); }
    finally {if(requestId===state.requestId){$("ap-table-panel").classList.remove("ap-loading");$("ap-table-panel").setAttribute("aria-busy","false");}}
  }
  function drawerName(row) { return row.msku || row.keyword_text || row.search_term || row.ad_group_name_current || row.campaign_name_current || "效果详情"; }
  async function openDetail(row) {
    if(row.__recommendation){return openRecommendationDetail(row);}
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
  async function openRecommendationDetail(row) {
    $("ap-drawer-title").textContent=row.suggestion_value||row.object_text||"建议详情";$("ap-drawer-content").innerHTML="<p>正在读取建议详情…</p>";$("ap-drawer-backdrop").hidden=false;$("ap-drawer").classList.add("open");$("ap-drawer").setAttribute("aria-hidden","false");
    try{var response=await fetch(recommendationEndpoint("detail",{kind:row.__kind,key:row.recommendation_key}));if(!response.ok)throw new Error((await response.json()).detail||"建议详情读取失败");var data=await response.json(),item=data.item;
      var fields=[["建议动作",statusLabel(item.status,row.__kind)],["人工审核原因",item.data_warning],["候选内容",item.suggestion_value||item.object_text],["建议类型",item.suggestion_type?suggestionLabel(item.suggestion_type):item.object_type],["命中品牌",item.protection_brand],["命中核心类目",item.protection_category],["首单/开售日期",item.product_launch_date],["产品天数",item.product_age_days],["当前竞价",item.current_bid],["建议竞价",item.suggested_bid],["调整金额",item.change_amount],["调整比例",percent(item.change_rate)],["理论CPC",item.theoretical_cpc],["店铺",item.seller_name],["站点",item.country_code],["MSKU",item.msku],["活动（当前）",item.campaign_name_current],["广告组（当前）",item.ad_group_name_current],["点击",item.clicks],["花费",item.cost],["订单",item.orders],["销售额",item.sales]];
      $("ap-drawer-content").innerHTML='<p class="ap-readonly-note">仅供人工决策参考，不会修改广告。</p><div class="ap-detail-grid">'+fields.filter(function(x){return x[1]!==null&&x[1]!==undefined&&x[1]!=="—";}).map(function(x){return '<div><span>'+escapeHtml(x[0])+'</span><strong title="'+escapeHtml(text(x[1]))+'">'+escapeHtml(text(x[1]))+'</strong></div>';}).join("")+'</div><section class="ap-reasons"><h3>计算与保护原因</h3><p>'+escapeHtml((item.reason_codes||[]).map(reasonLabel).join("、")||"—")+'</p></section>';
    }catch(error){$("ap-drawer-content").innerHTML='<p>详情读取失败：'+escapeHtml(error.message)+'</p>';}
  }
  function closeDrawer(){$("ap-drawer").classList.remove("open");$("ap-drawer").setAttribute("aria-hidden","true");$("ap-drawer-backdrop").hidden=true;}
  async function init() {
    try { state.options=await fetch("/api/ad-performance/options").then(function(r){if(!r.ok)throw new Error("选项读取失败");return r.json();});
      $("ap-start").value=state.options.min_date;$("ap-end").value=state.options.max_date;fillSelect("ap-currency",state.options.currencies,"value");$("ap-currency").value=state.options.default_currency;
      fillSelect("ap-store",state.options.stores);fillSelect("ap-country",state.options.countries);$("ap-data-date").textContent="截至 "+state.options.max_date;$("ap-updated").textContent="批次 "+state.options.batch_id+" · "+text(state.options.updated_at);
      state.recOptions=await fetch("/api/ad-performance/recommendations/options").then(function(r){return r.ok?r.json():{status:"no_data",rules:{}};});switchMode(state.mode);await load();
    } catch(error){showError(error);}
  }
  $("ap-query").onclick=function(){state.page=1;state.scope={};load();}; $("ap-reset").onclick=function(){["ap-store","ap-country","ap-targeting","ap-keyword","ap-msku","ap-rec-status","ap-rec-priority"].forEach(function(id){$(id).value="";});$("ap-currency").value=state.options.default_currency;$("ap-start").value=state.options.min_date;$("ap-end").value=state.options.max_date;state.scope={};state.trendMode="amount";$("ap-trend-modes").querySelectorAll("button[data-mode]").forEach(function(x){x.classList.toggle("active",x.dataset.mode==="amount");});state.page=1;load();};
  $("ap-windows").onclick=function(e){var b=e.target.closest("button");if(!b)return;state.window=Number(b.dataset.window);$("ap-windows").querySelectorAll("button").forEach(function(x){x.classList.toggle("active",x===b);});state.page=1;load();};
  $("ap-tabs").onclick=function(e){var b=e.target.closest("button");if(!b)return;switchView(b.dataset.view,false);load();};
  $("ap-page-size").onchange=function(){state.pageSize=Number(this.value);state.page=1;load();};$("ap-prev").onclick=function(){if(state.page>1){state.page--;load();}};$("ap-next").onclick=function(){if(state.page*state.pageSize<state.total){state.page++;load();}};
  $("ap-export").onclick=function(){window.location.href=state.mode==="overview"?endpoint("export"):recommendationEndpoint("export");};$("ap-columns").onclick=function(){if(state.grid&&state.grid.showColumnChooser)state.grid.showColumnChooser();};
  $("ap-trend-toggle").onclick=function(){var chart=$("ap-trend"),hidden=!chart.hidden;chart.hidden=hidden;this.textContent=hidden?"展开":"收起";this.setAttribute("aria-expanded",String(!hidden));if(!hidden&&state.chart)state.chart.resize();};
  $("ap-trend-modes").onclick=function(e){var b=e.target.closest("button[data-mode]");if(!b)return;state.trendMode=b.dataset.mode;$("ap-trend-modes").querySelectorAll("button[data-mode]").forEach(function(x){x.classList.toggle("active",x===b);});renderTrend(state.trendRows);};
  $("ap-filter-tags").onclick=function(e){var b=e.target.closest("button[data-clear]");if(!b)return;if(b.dataset.scope==="1")delete state.scope[b.dataset.clear];else $(b.dataset.clear).value="";state.page=1;load();};
  $("ap-bid-types").onclick=function(e){
    var button=e.target.closest("button[data-bid-type]");if(!button||button.dataset.bidType===state.bidType)return;
    state.bidType=button.dataset.bidType;state.page=1;closeDrawer();renderBidType();load();
  };
  $("ap-analysis-tabs").onclick=function(e){var b=e.target.closest("button[data-mode]");if(!b)return;switchMode(b.dataset.mode);load();};
  $("ap-drawer-close").onclick=closeDrawer;$("ap-drawer-backdrop").onclick=closeDrawer;$("ap-error").querySelector("button").onclick=load;window.addEventListener("resize",function(){if(state.chart)state.chart.resize();});init();
}());

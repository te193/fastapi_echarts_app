(function () {
  "use strict";

  function savedPageSize() {
    try {
      var saved = Number(localStorage.getItem("adBudgetPageSize"));
      return [20, 50, 100, 200].indexOf(saved) >= 0 ? saved : 50;
    } catch (error) { return 50; }
  }
  var state = { page: 1, pageSize: savedPageSize(), total: 0, meta: null, countryChart: null, anomalyChart: null, detailChart: null };
  var ids = {
    market: "ab-market", country: "ab-country", store: "ab-store", productType: "ab-product-type",
    inventory: "ab-inventory", anomaly: "ab-anomaly", keyword: "ab-keyword"
  };

  function el(id) { return document.getElementById(id); }
  function esc(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) { return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[char]; }); }
  function num(value, digits) { if (value == null || value === "") return "—"; return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits == null ? 2 : digits }); }
  function money(value) { return value == null ? "—" : "¥" + num(value, 2); }
  function pct(value) { return value == null ? "—" : (Number(value) * 100).toFixed(1) + "%"; }
  function api(url) { return fetch(url, { headers: { Accept: "application/json" } }).then(function (response) { if (!response.ok) throw new Error("请求失败（" + response.status + "）"); return response.json(); }); }
  function option(value) { return '<option value="' + esc(value) + '">' + esc(value) + "</option>"; }
  function fillSelect(id, values) { el(id).insertAdjacentHTML("beforeend", (values || []).map(option).join("")); }

  function query() {
    var params = new URLSearchParams({
      country_category: el(ids.market).value, country: el(ids.country).value,
      seller_name_new: el(ids.store).value, product_type: el(ids.productType).value,
      inventory_status: el(ids.inventory).value, anomaly: el(ids.anomaly).value,
      keyword: el(ids.keyword).value.trim(), page: String(state.page), page_size: String(state.pageSize),
      sort_field: "anomaly_priority", sort_dir: "desc"
    });
    return params.toString();
  }

  function renderDates(meta) {
    el("ad-budget-dates").innerHTML = '<strong>表现数据 ' + esc(meta.performance_date || "暂无") + '</strong><span>预算快照 ' + esc(meta.budget_date || "暂无") + "</span>";
    var stale = el("ab-stale");
    stale.hidden = !meta.budget_stale;
    stale.textContent = meta.budget_date ? "预算快照比表现数据滞后 " + num(meta.budget_lag_days, 0) + " 天，请谨慎判断预算消耗率。" : "尚未同步广告预算快照；有花费的产品仍会展示为未配置预算。";
  }

  function kpi(label, value, sub, tone) { return '<article class="ad-budget-kpi" style="--accent:' + tone + '"><span>' + label + "</span><strong>" + value + "</strong><small>" + sub + "</small></article>"; }
  function renderKpis(data) {
    var o = data.overview || {};
    el("ab-kpis").innerHTML = [
      kpi("市场库存池总预算", money(o.market_pool_budget), "按市场 / 店铺 / MSKU 去重", "#287b8f"),
      kpi("站点总预算", money(o.site_total_budget), "各国家站点额度合计", "#0f766e"),
      kpi("月预算消耗", money(o.month_spend) + " / " + money(o.monthly_budget), "预算消耗率 " + pct(o.monthly_execution_rate), "#2563eb"),
      kpi("近 7 天预算消耗", money(o.spend_7d) + " / " + money(o.weekly_budget), "预算消耗率 " + pct(o.weekly_execution_rate), "#d97706")
    ].join("");
  }

  function initChart(current, id) { if (current) current.dispose(); return echarts.init(el(id)); }
  function renderCharts(data) {
    state.countryChart = initChart(state.countryChart, "ab-country-chart");
    var countries = data.country_comparison || [];
    state.countryChart.setOption({
      tooltip:{trigger:"axis",valueFormatter:function(v){return money(v);}}, grid:{left:62,right:20,top:25,bottom:42},
      legend:{bottom:4,data:["月预算","本月花费"]}, xAxis:{type:"category",data:countries.map(function(x){return x.country;}),axisTick:{show:false}},
      yAxis:{type:"value",splitLine:{lineStyle:{color:"#edf2f5"}}},
      series:[{name:"月预算",type:"bar",data:countries.map(function(x){return x.monthly_budget;}),itemStyle:{color:"#b9d5ff",borderRadius:[5,5,0,0]}},{name:"本月花费",type:"bar",data:countries.map(function(x){return x.month_spend;}),itemStyle:{color:"#2563eb",borderRadius:[5,5,0,0]}}]
    });
    state.countryChart.on("click", function(params){ el(ids.country).value = params.name; state.page=1; load(); });
    state.anomalyChart = initChart(state.anomalyChart, "ab-anomaly-chart");
    var anomalies = data.anomaly_distribution || [];
    state.anomalyChart.setOption({tooltip:{trigger:"item"},series:[{type:"pie",radius:["48%","72%"],center:["50%","48%"],label:{formatter:"{b}\n{c}"},data:anomalies.map(function(x){return {name:x.name,value:x.count};}),color:["#c2414b","#e07a34","#eab308","#2563eb","#0f766e","#7c3aed"]}]});
    state.anomalyChart.on("click", function(params){ el(ids.anomaly).value=params.name; state.page=1; load(); });
  }

  function progress(rate) { var over = Number(rate || 0) > 1; return '<div class="ab-progress ' + (over ? "over" : "") + '"><i style="width:' + Math.min(Number(rate || 0) * 100,100) + '%"></i></div>'; }
  function badges(row) {
    if (!row.anomalies || !row.anomalies.length) return '<span class="ab-badge good">正常</span>';
    return row.anomalies.map(function(label){ var cls = /异常|超支|无月预算|无广告销售/.test(label) ? "danger" : "warning"; return '<span class="ab-badge ' + cls + '">' + esc(label) + "</span>"; }).join("");
  }
  function identifierLine(label, rawValue, primary) {
    var value = String(rawValue || "").trim();
    var line = document.createElement("span");
    line.className = "ab-identifier-line " + (primary ? "primary" : "secondary");
    line.innerHTML = '<code>' + esc(value || "—") + '</code><button type="button" class="ab-copy-button" data-copy-value="' + esc(value) + '" data-copy-label="' + esc(label) + '" aria-label="复制' + esc(label) + '" title="复制' + esc(label) + '"' + (value ? "" : " disabled") + '><span class="ab-copy-glyph" aria-hidden="true"></span></button>';
    var button = line.querySelector("button");
    button.disabled = !value;
    button.addEventListener("click", function (event) { event.stopPropagation(); copyCode(value, button); });
    return line;
  }
  function identifierCell(row) {
    var cell = document.createElement("div");
    cell.className = "ab-identifier-cell";
    cell.appendChild(identifierLine("MSKU", row.seller_sku_adj, true));
    cell.appendChild(identifierLine("ASIN", row.asin, false));
    return cell;
  }
  function legacyCopy(value) {
    var textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    var copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("copy command failed");
  }
  function writeCode(value) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value).catch(function () { legacyCopy(value); });
    }
    return new Promise(function (resolve, reject) {
      try { legacyCopy(value); resolve(); } catch (error) { reject(error); }
    });
  }
  function copyCode(value, button) {
    if (!value) return;
    clearTimeout(button._copyTimer);
    writeCode(value).then(function () {
      button.classList.add("copied");
      button.title = "已复制";
      button.setAttribute("aria-label", button.dataset.copyLabel + "已复制");
    }).catch(function () {
      button.classList.add("failed");
      button.title = "复制失败";
    }).finally(function () {
      button._copyTimer = setTimeout(function () {
        button.classList.remove("copied", "failed");
        button.title = "复制" + button.dataset.copyLabel;
        button.setAttribute("aria-label", "复制" + button.dataset.copyLabel);
      }, 1400);
    });
  }
  function productCell(row) {
    return '<div class="ab-product"><strong class="ab-product-name" title="' + esc(row.product_name) + '">' + esc(row.product_name || row.seller_sku_adj) + '</strong>' +
      '<span class="ab-product-site"><b>站点：</b>' + esc(row.country_category || "—") + ' / ' + esc(row.country || "—") + '</span>' +
      '<span class="ab-product-store"><b>店铺：</b>' + esc(row.seller_name_new || "—") + '</span></div>';
  }
  function capCell(row) {
    var capClass = row.status === "valid" ? "good" : row.status === "invalid" ? "danger" : "warning";
    return '<div class="ab-cap-cell"><span class="ab-badge ' + capClass + '">' + esc(row.label) + '</span><small>' + esc(row.excess_level || "周 ≤ 月 ≤ 站点总预算") + (row.status === "invalid" ? " · 超出 " + money(row.excess_amount) : "") + '</small></div>';
  }
  function budgetMetric(budget, spend, remaining, rate) {
    return '<div class="ab-metric"><strong>' + money(budget) + ' / ' + money(spend) + '</strong><small>剩余 ' + money(remaining) + ' · ' + pct(rate) + '</small>' + progress(rate) + '</div>';
  }
  function metricCell(main, sub) {
    return '<div class="ab-metric"><strong>' + main + '</strong><small title="' + esc(sub) + '">' + sub + '</small></div>';
  }
  function gridColumns() {
    return [
      {headerName:"产品",pinned:"left",width:265,minWidth:230,cellRenderer:function(p){return productCell(p.data);}},
      {headerName:"MSKU / ASIN",pinned:"left",width:155,minWidth:145,cellRenderer:function(p){return identifierCell(p.data);}},
      {headerName:"预算约束",width:170,cellRenderer:function(p){return capCell(p.data);}},
      {headerName:"广告总预算",field:"total_budget_pool_cny",width:125,valueFormatter:function(p){return money(p.value);}},
      {headerName:"月预算 / 花费",width:155,cellRenderer:function(p){var r=p.data;return budgetMetric(r.monthly_ad_budget_cny,r.month_spend,r.monthly_remaining,r.monthly_execution_rate);}},
      {headerName:"周预算 / 近7天",width:155,cellRenderer:function(p){var r=p.data;return budgetMetric(r.weekly_ad_budget_cny,r.spend_7d,r.weekly_remaining,r.weekly_execution_rate);}},
      {headerName:"曝光 / 点击",width:130,cellRenderer:function(p){var r=p.data;return metricCell(num(r.ad_impressions,0)+" / "+num(r.ad_clicks,0),"CTR "+pct(r.ctr));}},
      {headerName:"广告转化",width:205,cellRenderer:function(p){var r=p.data;return metricCell(num(r.ad_orders,0)+" 单","广告 CVR "+pct(r.ad_cvr)+" · 销售 "+money(r.ad_sales));}},
      {headerName:"TACOS / ACOS",width:130,cellRenderer:function(p){var r=p.data;return metricCell(pct(r.tacos),"ACOS "+pct(r.acos));}},
      {headerName:"流量 / 销量",width:125,cellRenderer:function(p){var r=p.data;return metricCell(num(r.sessions_total,0)+" Sessions","销量 "+num(r.sales_qty,0));}},
      {headerName:"异常",width:250,minWidth:180,cellRenderer:function(p){return '<div class="ab-anomaly-cell">'+badges(p.data)+'</div>';}}
    ];
  }
  function renderTable(data) {
    state.total = data.total || 0;
    var pages = Math.max(1, Math.ceil(state.total/state.pageSize));
    el("ab-table-count").textContent = "共 " + num(state.total,0) + " 个站点产品";
    window.kanbanGrid.makeGrid("ab-grid", {
      rowData: data.rows || [],
      columnDefs: gridColumns(),
      domLayout: "normal",
      rowHeight: 84,
      headerHeight: 44,
      defaultColDef: {sortable:false,filter:false,resizable:true,minWidth:96},
      getRowId: function(p){var r=p.data;return [r.country_category,r.country,r.seller_name_new,r.seller_sku_adj].join("|");},
      onRowClicked: function(p){if(!p.event.target.closest(".ab-copy-button"))openDetail(p.data);}
    });
    el("ab-page").textContent = "第 " + state.page + " / " + pages + " 页";
    el("ab-page-summary").textContent = "共 " + num(state.total,0) + " 条，第 " + state.page + " / " + pages + " 页";
    el("ab-prev").disabled = state.page <= 1; el("ab-next").disabled = state.page * state.pageSize >= state.total;
  }
  function load() {
    el("ab-table-count").textContent = "正在加载…";
    api("/api/ad-budget?" + query()).then(function(data){ renderKpis(data); renderCharts(data); renderTable(data); }).catch(function(error){ window.kanbanGrid.destroy("ab-grid");el("ab-grid").innerHTML='<div class="ab-error">' + esc(error.message) + '</div>';el("ab-table-count").textContent="加载失败"; });
  }

  function openDetail(identity) {
    var drawer=el("ab-drawer"), backdrop=el("ab-drawer-backdrop"); drawer.classList.add("open"); drawer.setAttribute("aria-hidden","false"); backdrop.hidden=false; el("ab-drawer-title").textContent=identity.seller_sku_adj; el("ab-drawer-content").innerHTML='<div class="ab-empty">正在读取详情…</div>';
    api("/api/ad-budget/detail?" + new URLSearchParams(identity).toString()).then(renderDetail).catch(function(error){el("ab-drawer-content").innerHTML='<div class="ab-error">' + esc(error.message) + "</div>";});
  }
  function closeDetail(){el("ab-drawer").classList.remove("open");el("ab-drawer").setAttribute("aria-hidden","true");el("ab-drawer-backdrop").hidden=true;if(state.detailChart){state.detailChart.dispose();state.detailChart=null;}}
  function card(label,value){return '<article class="ab-detail-card"><span>'+esc(label)+'</span><strong>'+value+'</strong></article>';}
  function renderDetail(data){
    var r=data.row||{};
    el("ab-drawer-title").textContent=(r.product_name||r.seller_sku_adj)+" · "+r.country;
    var capDetail='<span class="ab-badge '+(r.status==="valid"?"good":r.status==="invalid"?"danger":"warning")+'">'+esc(r.label)+'</span>'+(r.status==="invalid"?'<small>'+esc(r.excess_level)+' · 超出 '+money(r.excess_amount)+'</small>':'');
    var monthRemaining=r.monthly_ad_budget_cny==null?"—":money(Number(r.monthly_ad_budget_cny)-Number(r.month_spend||0));
    el("ab-drawer-content").innerHTML='<div class="ab-detail-grid">'+card("加权日销",num(r.daily_avg_sales,2))+card("站点销量占比",pct(r.sales_share))+card("预算库存池",num(r.total_budget_inventory,0))+card("30天库存",r.inventory_sufficient_flag?"充足":"不足")+card("7天库存",r.weekly_inventory_sufficient_flag?"充足":"不足")+card("预算约束",capDetail)+'</div><div class="ab-budget-steps"><div class="ab-budget-step">月预算<strong>'+money(r.monthly_ad_budget_cny)+'</strong></div><div class="ab-budget-step">本月花费<strong>'+money(r.month_spend)+'</strong></div><div class="ab-budget-step">月剩余额度<strong>'+monthRemaining+'</strong></div></div><section class="ab-business-summary"><header><span>本月至今经营数据</span><small>当月 1 日至最新表现日</small></header><div><article><span>经营销售额</span><strong>'+money(r.sales_amount)+'</strong></article><article><span>产品销量</span><strong>'+num(r.sales_qty,0)+'</strong></article><article><span>Sessions</span><strong>'+num(r.sessions_total,0)+'</strong></article><article><span>广告销售占比</span><strong>'+pct(r.ad_sales_share)+'</strong></article></div></section><section class="ab-funnel"><header><span>本月至今广告漏斗</span><strong>花费 '+money(r.month_spend)+'</strong></header><div><article><span>曝光</span><strong>'+num(r.ad_impressions,0)+'</strong></article><i>CTR '+pct(r.ctr)+'</i><article><span>点击</span><strong>'+num(r.ad_clicks,0)+'</strong></article><i>CVR '+pct(r.ad_cvr)+'</i><article><span>广告订单</span><strong>'+num(r.ad_orders,0)+'</strong></article><i>销售 '+money(r.ad_sales)+'</i></div><footer>TACOS '+pct(r.tacos)+' · ACOS '+pct(r.acos)+'</footer></section><div id="ab-detail-chart" class="ab-detail-chart"></div>';
    state.detailChart=echarts.init(el("ab-detail-chart"));var trend=data.trend||[];state.detailChart.setOption({tooltip:{trigger:"axis"},legend:{bottom:4,data:["累计广告花费","累计广告销售额"]},grid:{left:55,right:20,top:28,bottom:46},xAxis:{type:"category",data:trend.map(function(x){return x.dt_date.slice(5);})},yAxis:{type:"value",splitLine:{lineStyle:{color:"#edf2f5"}}},series:[{name:"累计广告花费",type:"line",smooth:true,data:trend.map(function(x){return x.cumulative_ad_spend;}),lineStyle:{color:"#d97706"},itemStyle:{color:"#d97706"}},{name:"累计广告销售额",type:"line",smooth:true,data:trend.map(function(x){return x.cumulative_ad_sales;}),lineStyle:{color:"#2563eb"},itemStyle:{color:"#2563eb"},areaStyle:{color:"rgba(37,99,235,.08)"}}]});
  }

  function bind(){Object.keys(ids).forEach(function(key){var node=el(ids[key]);var event=node.tagName==="INPUT"?"input":"change";var timer;node.addEventListener(event,function(){clearTimeout(timer);timer=setTimeout(function(){state.page=1;load();},node.tagName==="INPUT"?250:0);});});el("ab-reset").addEventListener("click",function(){Object.keys(ids).forEach(function(key){var node=el(ids[key]);node.value=node.tagName==="INPUT"?"":"all";});state.page=1;load();});el("ab-page-size").value=String(state.pageSize);el("ab-page-size").addEventListener("change",function(){state.pageSize=Number(this.value);state.page=1;try{localStorage.setItem("adBudgetPageSize",String(state.pageSize));}catch(error){}load();});el("ab-prev").addEventListener("click",function(){if(state.page>1){state.page--;load();}});el("ab-next").addEventListener("click",function(){if(state.page*state.pageSize<state.total){state.page++;load();}});el("ab-drawer-close").addEventListener("click",closeDetail);el("ab-drawer-backdrop").addEventListener("click",closeDetail);window.addEventListener("resize",function(){[state.countryChart,state.anomalyChart,state.detailChart].forEach(function(chart){if(chart)chart.resize();});});}
  function init(){api("/api/ad-budget/meta").then(function(meta){state.meta=meta;renderDates(meta);fillSelect(ids.market,meta.country_categories);fillSelect(ids.country,meta.countries);fillSelect(ids.store,meta.stores);fillSelect(ids.productType,meta.product_types);fillSelect(ids.anomaly,meta.anomalies);bind();load();}).catch(function(error){el("ad-budget-dates").innerHTML='<span class="ab-error">'+esc(error.message)+"</span>";});}
  init();
}());

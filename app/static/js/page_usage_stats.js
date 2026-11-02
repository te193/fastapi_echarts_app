(function () {
  "use strict";
  var items = [];
  var environment = document.getElementById("usageEnvironment");
  var search = document.getElementById("usageSearch");
  var zeroOnly = document.getElementById("usageZeroOnly");
  var refresh = document.getElementById("usageRefresh");
  var status = document.getElementById("usageStatus");
  var body = document.getElementById("usageRows");
  var sequence = 0;
  function number(value) { return Number(value || 0).toLocaleString("zh-CN"); }

  function render() {
    var keyword = search.value.trim().toLowerCase();
    var visible = items.filter(function (item) {
      return (!zeroOnly.checked || item.views_30d === 0) &&
        (!keyword || (item.name + " " + item.path + " " + item.group).toLowerCase().indexOf(keyword) !== -1);
    });
    body.replaceChildren();
    visible.forEach(function (item) {
      var tr = document.createElement("tr");
      if (!item.views_30d) tr.className = "usage-zero";
      var name = document.createElement("td");
      var link = document.createElement("a");
      link.href = item.path;
      link.textContent = item.name;
      var path = document.createElement("small");
      path.textContent = item.path;
      name.append(link, path);
      tr.append(name);
      [item.group, number(item.views_7d), number(item.views_30d), number(item.browsers_30d),
        number(item.active_days_30d), item.last_seen || "尚未访问"].forEach(function (value) {
        var td = document.createElement("td");
        td.textContent = value;
        tr.append(td);
      });
      body.append(tr);
    });
    status.textContent = visible.length ? "显示 " + visible.length + " / " + items.length + " 个页面，零访问页面优先。" : "没有符合条件的页面。";
  }

  async function load() {
    var request = ++sequence;
    refresh.disabled = true;
    status.className = "";
    status.textContent = "正在加载…";
    try {
      var response = await fetch("/api/page-usage?environment=" + encodeURIComponent(environment.value), {cache: "no-store"});
      if (!response.ok) throw new Error("统计数据暂不可用，请稍后重试。");
      var data = await response.json();
      if (request !== sequence) return;
      items = data.items;
      document.getElementById("usagePages").textContent = number(data.summary.pages);
      document.getElementById("usageViews").textContent = number(data.summary.views_30d);
      document.getElementById("usageBrowsers").textContent = number(data.summary.browsers_30d);
      document.getElementById("usageZeroPages").textContent = number(data.summary.zero_pages);
      document.getElementById("usageObservation").textContent = "开始记录：" + data.observation_started_at +
        " · 已观察 " + data.observed_days + " 天 · 近30天区间：" + data.window_30d_start + " 至 " + data.window_end +
        (data.review_ready ? "。已满30天，可结合业务频率排查零访问页面。" : "。尚未满30天，零访问页面仅供观察。");
      render();
    } catch (error) {
      if (request !== sequence) return;
      items = [];
      body.replaceChildren();
      ["usagePages", "usageViews", "usageBrowsers", "usageZeroPages"].forEach(function (id) { document.getElementById(id).textContent = "—"; });
      document.getElementById("usageObservation").textContent = "暂时无法读取观察周期。";
      status.textContent = error.message || "统计数据加载失败，请重试。";
      status.className = "usage-error";
    } finally {
      if (request === sequence) refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", load);
  environment.addEventListener("change", load);
  search.addEventListener("input", render);
  zeroOnly.addEventListener("change", render);
  load();
})();

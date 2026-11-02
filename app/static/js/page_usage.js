(function () {
  "use strict";
  // Independent of business scripts, charts and their requests.
  var page = document.body && document.body.dataset.page;
  if (!page) return;
  var sent = false;
  var validId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  function read(storage, key) {
    try { return window[storage].getItem(key); } catch (_) { return null; }
  }
  function write(storage, key, value) {
    try { window[storage].setItem(key, value); } catch (_) { /* Storage may be blocked. */ }
  }
  function id() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    // Anonymous identifiers only; HTTP LAN origins may lack randomUUID().
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.floor(Math.random() * 16);
      return (c === "x" ? r : (r & 3) | 8).toString(16);
    });
  }
  var browser = read("localStorage", "dashboard.usage.browser");
  if (!browser || !validId.test(browser)) {
    browser = id();
    write("localStorage", "dashboard.usage.browser", browser);
  }
  var testFlag = new URLSearchParams(window.location.search).get("usage_test");
  if (testFlag === "1" || testFlag === "0") write("sessionStorage", "dashboard.usage.test", testFlag);
  var environment = (navigator.webdriver || window.location.port === "8001" || testFlag === "1" ||
    (testFlag !== "0" && read("sessionStorage", "dashboard.usage.test") === "1")) ? "test" : "production";
  var cooldownKey = "dashboard.usage.last." + environment + "." + page;

  function record() {
    if (sent || document.visibilityState === "hidden") return;
    var timestamp = Date.now();
    var previous = Number(read("sessionStorage", cooldownKey));
    if (previous > 0 && timestamp >= previous && timestamp - previous < 30000) {
      sent = true;
      return;
    }
    sent = true;
    try {
      window.fetch("/api/page-usage/visits", {
        method: "POST", headers: {"Content-Type": "application/json"},
        credentials: "same-origin", keepalive: true,
        body: JSON.stringify({page_id: page, browser_id: browser, visit_id: id(), environment: environment})
      }).then(function (response) {
        if (!response.ok) return null;
        return response.json();
      }).then(function (result) {
        if (result && result.recorded) write("sessionStorage", cooldownKey, String(timestamp));
      }).catch(function () { /* Analytics must never interrupt business pages. */ });
    } catch (_) { /* Unsupported or blocked fetch must not interrupt the page. */ }
  }
  document.addEventListener("visibilitychange", record);
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) { sent = false; record(); }
  });
  record();
})();

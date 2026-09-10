(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AdCurrency = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";
  var symbols = {
    EUR: "€", GBP: "£", USD: "$", CNY: "¥", RMB: "¥", JPY: "¥",
    CAD: "C$", AUD: "A$", SGD: "S$", MXN: "MX$", BRL: "R$",
    PLN: "zł", SEK: "kr", AED: "د.إ", SAR: "ر.س", INR: "₹"
  };

  function format(value, currency, digits) {
    if (value === null || value === undefined || value === "") return "—";
    var code = String(currency || "").trim().toUpperCase();
    var amount = Number(value).toLocaleString("zh-CN", {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits
    });
    if (symbols[code]) return symbols[code] + amount;
    return code ? code + " " + amount : amount;
  }

  return { format: format, symbol: function (currency) { return symbols[String(currency || "").toUpperCase()] || String(currency || ""); } };
});

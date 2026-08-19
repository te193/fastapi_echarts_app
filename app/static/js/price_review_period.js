(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PriceReviewPeriod = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var supportedDays = ["3", "7", "14", "28"];

  return {
    defaultDays: "3",
    supportedDays: supportedDays.slice(),
    isSupported: function (value) {
      return supportedDays.indexOf(String(value || "")) >= 0;
    }
  };
});

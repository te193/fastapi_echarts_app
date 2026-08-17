(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.priceReviewFinanceFlow = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function buildModel(rawBands, rawItems) {
    var bands = (rawBands || []).map(function (band, index) {
      return {
        key: String(band.key || ""),
        label: String(band.label || band.key || ""),
        index: index
      };
    }).filter(function (band) { return band.key; });
    var bandIndex = {};
    bands.forEach(function (band) { bandIndex[band.key] = band.index; });

    var counts = {};
    (rawItems || []).forEach(function (item) {
      var before = String(item.before || "");
      var after = String(item.after || "");
      var count = Number(item.count || 0);
      if (!(before in bandIndex) || !(after in bandIndex) || count <= 0) return;
      var key = before + "\u0000" + after;
      if (!counts[key]) {
        counts[key] = {
          before: before,
          beforeLabel: bands[bandIndex[before]].label,
          after: after,
          afterLabel: bands[bandIndex[after]].label,
          sourceIndex: bandIndex[before],
          targetIndex: bandIndex[after],
          count: 0
        };
      }
      counts[key].count += count;
    });

    var links = Object.keys(counts).map(function (key) {
      var link = counts[key];
      link.direction = link.targetIndex > link.sourceIndex
        ? "up"
        : link.targetIndex < link.sourceIndex ? "down" : "stable";
      return link;
    });
    var maxCount = links.reduce(function (maximum, link) {
      return Math.max(maximum, link.count);
    }, 0);

    links.forEach(function (link) {
      link.strokeWidth = maxCount
        ? 1.5 + Math.sqrt(link.count / maxCount) * 11.5
        : 0;
    });
    links.sort(function (a, b) { return a.count - b.count; });

    function nodesFor(side) {
      return bands.map(function (band) {
        var total = links.reduce(function (sum, link) {
          return sum + (side === "left" && link.before === band.key
            ? link.count
            : side === "right" && link.after === band.key ? link.count : 0);
        }, 0);
        return { key: band.key, label: band.label, index: band.index, count: total };
      });
    }

    return {
      leftNodes: nodesFor("left"),
      rightNodes: nodesFor("right"),
      links: links,
      maxCount: maxCount
    };
  }

  return { buildModel: buildModel };
});

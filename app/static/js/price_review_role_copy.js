(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PriceReviewRoleCopy = api;
})(typeof window !== "undefined" ? window : globalThis, function (root) {
  "use strict";

  var COPY_SELECTOR = "[data-copy-role-msku]";

  function isMskuCopyTarget(event) {
    return Boolean(event && event.target && event.target.closest && event.target.closest(COPY_SELECTOR));
  }

  function fallbackCopyText(value) {
    var documentRef = root && root.document;
    if (!documentRef || !documentRef.body || !documentRef.execCommand) {
      return Promise.reject(new Error("clipboard unavailable"));
    }
    var textarea = documentRef.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    documentRef.body.appendChild(textarea);
    textarea.select();
    var copied = documentRef.execCommand("copy");
    textarea.remove();
    return copied ? Promise.resolve() : Promise.reject(new Error("copy command failed"));
  }

  function copyText(value) {
    var navigatorRef = root && root.navigator;
    if (navigatorRef && navigatorRef.clipboard && navigatorRef.clipboard.writeText) {
      return navigatorRef.clipboard.writeText(value).catch(function () {
        return fallbackCopyText(value);
      });
    }
    return fallbackCopyText(value);
  }

  function updateButtonState(button, state, value) {
    button.dataset.copyState = state;
    var label = state === "success" ? "已复制" : state === "error" ? "复制失败" : "复制";
    button.setAttribute("aria-label", label + " MSKU " + value);
    button.setAttribute("title", label);
  }

  function renderMskuCell(value, escapeHtml) {
    var escapedValue = escapeHtml(value);
    return '<div class="role-detail-msku-cell"><button type="button" class="role-detail-msku-button"><strong>' + escapedValue + '</strong></button><button type="button" class="role-msku-copy-button" data-copy-role-msku="' + escapedValue + '" data-copy-state="idle" aria-label="复制 MSKU ' + escapedValue + '" title="复制"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"></rect><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path></svg></button></div>';
  }

  function handleMskuCopyClick(event, options) {
    var button = event && event.target && event.target.closest ? event.target.closest(COPY_SELECTOR) : null;
    if (!button) return false;

    event.preventDefault();
    event.stopPropagation();
    var value = String(button.dataset.copyRoleMsku || "").trim();
    var dependencies = options || {};
    var write = dependencies.copyText || copyText;
    var schedule = dependencies.schedule || function (callback, delay) { return root.setTimeout(callback, delay); };

    Promise.resolve().then(function () {
      if (!value) throw new Error("empty MSKU");
      return write(value);
    }).then(function () {
      updateButtonState(button, "success", value);
    }).catch(function () {
      updateButtonState(button, "error", value);
    }).then(function () {
      schedule(function () { updateButtonState(button, "idle", value); }, 1400);
    });
    return true;
  }

  return {
    copyText: copyText,
    handleMskuCopyClick: handleMskuCopyClick,
    isMskuCopyTarget: isMskuCopyTarget,
    renderMskuCell: renderMskuCell
  };
});

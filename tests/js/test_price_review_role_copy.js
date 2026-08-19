const assert = require("node:assert/strict");
const test = require("node:test");

const {
  handleMskuCopyClick,
  isMskuCopyTarget,
  renderMskuCell
} = require("../../app/static/js/price_review_role_copy.js");

function copyEvent(button) {
  return {
    defaultPrevented: false,
    propagationStopped: false,
    target: {
      closest(selector) {
        return selector === "[data-copy-role-msku]" ? button : null;
      }
    },
    preventDefault() {
      this.defaultPrevented = true;
    },
    stopPropagation() {
      this.propagationStopped = true;
    }
  };
}

test("copying an MSKU consumes the row click and writes the exact value", async () => {
  const button = {
    dataset: { copyRoleMsku: "CJ002a" },
    setAttribute() {}
  };
  const event = copyEvent(button);
  const copiedValues = [];

  const handled = handleMskuCopyClick(event, {
    copyText(value) {
      copiedValues.push(value);
      return Promise.resolve();
    },
    schedule() {}
  });
  await Promise.resolve();

  assert.equal(handled, true);
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.propagationStopped, true);
  assert.deepEqual(copiedValues, ["CJ002a"]);
});

test("ordinary row targets remain available for opening the diagnostic drawer", () => {
  const event = {
    target: { closest() { return null; } },
    preventDefault() { throw new Error("ordinary row click must not be prevented"); },
    stopPropagation() { throw new Error("ordinary row click must not be stopped"); }
  };

  assert.equal(handleMskuCopyClick(event, { copyText() {} }), false);
  assert.equal(isMskuCopyTarget(event), false);
});

test("keyboard activation on the copy button is identifiable before row key handling", () => {
  const button = { dataset: { copyRoleMsku: "CJ002a" } };

  assert.equal(isMskuCopyTarget(copyEvent(button)), true);
});

test("the MSKU cell keeps diagnosis on the MSKU text without rendering a diagnosis label", () => {
  const html = renderMskuCell("CJ&002a", value => String(value).replace("&", "&amp;"));

  assert.match(html, /<strong>CJ&amp;002a<\/strong>/);
  assert.match(html, /data-copy-role-msku="CJ&amp;002a"/);
  assert.doesNotMatch(html, /查看诊断/);
});

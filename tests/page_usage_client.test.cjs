const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');
const source = readFileSync('app/static/js/page_usage.js', 'utf8');

function storage() {
  const values = new Map();
  return {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value))};
}
function browser(options = {}) {
  const handlers = {};
  const calls = [];
  const context = {
    document: {body: {dataset: {page: options.page || 'replenishment'}},
      visibilityState: options.hidden ? 'hidden' : 'visible',
      addEventListener: (key, callback) => handlers[key] = callback},
    navigator: {webdriver: options.webdriver || false},
    location: {port: options.port || '8000', search: options.search || ''},
    localStorage: options.local || storage(), sessionStorage: options.session || storage(),
    crypto: {randomUUID}, URLSearchParams,
    Date: class extends Date {static now() {return options.time || 100000;}},
    fetch: (url, init) => {calls.push({url, ...init}); return options.fail ? Promise.reject(new Error('offline')) : Promise.resolve({ok: !options.notOk, json: () => Promise.resolve({recorded: options.recorded !== false})});},
    addEventListener: (key, callback) => handlers[key] = callback,
  };
  context.window = context;
  vm.runInNewContext(source, context);
  return {context, calls, handlers};
}
const settled = () => new Promise(resolve => setImmediate(resolve));

test('a visible page visit is sent directly without a menu click or business parameters', async () => {
  const {calls} = browser({search: '?keyword=private-sku'});
  await settled();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/page-usage/visits');
  const body = JSON.parse(calls[0].body);
  assert.equal(body.page_id, 'replenishment');
  assert.equal(body.environment, 'production');
  assert.equal(calls[0].keepalive, true);
  assert.equal(JSON.stringify(body).includes('private-sku'), false);
});

test('hidden tabs count only on first visibility and focus switches do not inflate visits', async () => {
  const b = browser({hidden: true});
  assert.equal(b.calls.length, 0);
  b.context.document.visibilityState = 'visible';
  b.handlers.visibilitychange();
  b.handlers.visibilitychange();
  await settled();
  assert.equal(b.calls.length, 1);
});

test('same-tab refresh is deduplicated for 30 seconds while other pages and later returns count', async () => {
  const local = storage(), session = storage();
  browser({local, session, time: 100000});
  await settled();
  assert.equal(browser({local, session, time: 129999}).calls.length, 0);
  assert.equal(browser({local, session, time: 130000}).calls.length, 1);
  assert.equal(browser({local, session, page: 'alerts', time: 130000}).calls.length, 1);
});

test('failed requests do not suppress the next visit and do not cause an unhandled error', async () => {
  const local = storage(), session = storage();
  browser({local, session, fail: true});
  await settled();
  assert.equal(browser({local, session, time: 100001}).calls.length, 1);
  await settled();
});

test('a server-rejected cross-tab duplicate must not extend the local cooldown', async () => {
  const local = storage(), session = storage();
  browser({local, session, time: 129000, recorded: false});
  await settled();
  assert.equal(browser({local, session, time: 131000}).calls.length, 1);
  await settled();
});

test('blocked browser storage does not break the business page', async () => {
  const blocked = {getItem() {throw Error('blocked');}, setItem() {throw Error('blocked');}};
  assert.equal(browser({local: blocked, session: blocked}).calls.length, 1);
  await settled();
});

for (const options of [{port: '8001'}, {webdriver: true}, {search: '?usage_test=1'}]) {
  test(`test traffic is labelled: ${JSON.stringify(options)}`, async () => {
    const {calls} = browser(options);
    assert.equal(JSON.parse(calls[0].body).environment, 'test');
    await settled();
  });
}

test('back/forward cache return can count again after the cooldown', async () => {
  const options = {time: 100000};
  const b = browser(options);
  await settled();
  options.time = 131000;
  b.handlers.pageshow({persisted: true});
  await settled();
  assert.equal(b.calls.length, 2);
});

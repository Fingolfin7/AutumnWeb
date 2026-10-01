const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('only Luna is fetched and failure leaves deterministic suggestions untouched', async () => {
  const pending = {};
  const timers = [];
  const message = { textContent: 'Considering your recent work…' };
  const luna = { hidden: false, innerHTML: '', getAttribute: () => 'luna', querySelector: () => message };
  const fetch = (url) => new Promise((resolve, reject) => { pending[url] = { resolve, reject }; });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../core/static/core/js/luna_timer_recommendations.js'), 'utf8'), {
    window: { fetch, addEventListener: () => {}, setTimeout: (_, delay) => { timers.push(delay); return delay; }, clearTimeout: () => {} },
    document: { querySelector: () => null, querySelectorAll: (selector) => { assert.equal(selector, '[data-luna-url]'); return [luna]; },
                getElementById: () => null }, fetch,
  });
  assert.deepEqual(Object.keys(pending), ['luna']);
  assert.deepEqual(timers, [195000]);
  pending.luna.reject(new Error('timeout'));
  await new Promise(setImmediate);
  assert.match(message.textContent, /Luna is unavailable/);
  assert.equal(luna.innerHTML, '');
});

test('pending generation is polled and rendered without blanking the panel', async () => {
  const callbacks = [];
  let calls = 0;
  const mount = { innerHTML: 'Loading', hidden: false, hasAttribute: () => true,
    getAttribute: () => 'luna', querySelector: () => ({ textContent: '' }) };
  const fetch = async () => ++calls === 1 ? { status: 202 } : {
    status: 200, ok: true, text: async () => '<p>Shared result</p>'
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../core/static/core/js/luna_timer_recommendations.js'), 'utf8'), {
    window: { fetch, addEventListener: () => {}, setTimeout: (cb, delay) => { if (delay === 5000) callbacks.push(cb); return delay; }, clearTimeout: () => {} },
    document: { querySelector: () => null, querySelectorAll: () => [mount], getElementById: () => null }, fetch,
  });
  await new Promise(setImmediate);
  assert.equal(mount.innerHTML, 'Loading');
  assert.equal(calls, 1);
  callbacks.shift()();
  await new Promise(setImmediate);
  assert.equal(calls, 2);
  assert.equal(mount.innerHTML, '<p>Shared result</p>');
});

test('effort uses the current account saved value instead of restored browser state', () => {
  const source = fs.readFileSync(path.join(__dirname, '../../core/static/core/js/luna_timer_recommendations.js'), 'utf8');
  for (const saved of ['high', 'xhigh']) {
    const effort = { value: saved === 'high' ? 'xhigh' : 'high', getAttribute: () => saved };
    let pageshow;
    let reloads = 0;
    vm.runInNewContext(source, {
      window: { addEventListener: (type, cb) => { assert.equal(type, 'pageshow'); pageshow = cb; },
                location: { reload: () => { reloads++; } } },
      document: { querySelector: () => effort },
    });
    assert.equal(effort.value, saved);
    effort.value = 'max';  // Simulate browser restoring the previous account's choice after script load.
    pageshow({ persisted: false });
    assert.equal(effort.value, saved);
    pageshow({ persisted: true });
    assert.equal(reloads, 1);  // Back/forward restores must re-check the signed-in account.
  }
});

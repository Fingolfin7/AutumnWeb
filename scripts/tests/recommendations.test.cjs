const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('Jev renders independently while Luna waits, and Luna failure stays local', async () => {
  const pending = {};
  const timers = [];
  const message = { textContent: 'Considering your recent work…' };
  const mount = (provider) => ({
    hidden: provider === 'jev', innerHTML: '',
    hasAttribute: (name) => name === `data-${provider}-url`,
    getAttribute: () => provider,
    querySelector: () => message,
  });
  const jev = mount('jev');
  const luna = mount('luna');
  const fetch = (url) => new Promise((resolve, reject) => { pending[url] = { resolve, reject }; });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../core/static/core/js/jev_timer_recommendations.js'), 'utf8'), {
    window: { fetch, setTimeout: (_, delay) => { timers.push(delay); return delay; }, clearTimeout: () => {} },
    document: { querySelectorAll: () => [jev, luna], getElementById: () => null },
    fetch,
  });
  assert.deepEqual(Object.keys(pending), ['jev', 'luna']);
  assert.deepEqual(timers, [8000, 195000]);
  pending.jev.resolve({ status: 200, ok: true, text: async () => '<p>Jev advice</p>' });
  await new Promise(setImmediate);
  assert.equal(jev.innerHTML, '<p>Jev advice</p>');
  assert.equal(jev.hidden, false);
  assert.equal(luna.innerHTML, '');
  pending.luna.reject(new Error('timeout'));
  await new Promise(setImmediate);
  assert.match(message.textContent, /Luna is unavailable/);
  assert.equal(jev.innerHTML, '<p>Jev advice</p>');
});

test('pending generation is polled and rendered without blanking the panel', async () => {
  const callbacks = [];
  let calls = 0;
  const mount = { innerHTML: 'Loading', hidden: false, hasAttribute: () => true,
    getAttribute: () => 'luna', querySelector: () => ({ textContent: '' }) };
  const fetch = async () => ++calls === 1 ? { status: 202 } : {
    status: 200, ok: true, text: async () => '<p>Shared result</p>'
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../core/static/core/js/jev_timer_recommendations.js'), 'utf8'), {
    window: { fetch, setTimeout: (cb, delay) => { if (delay === 5000) callbacks.push(cb); return delay; }, clearTimeout: () => {} },
    document: { querySelectorAll: () => [mount], getElementById: () => null }, fetch,
  });
  await new Promise(setImmediate);
  assert.equal(mount.innerHTML, 'Loading');
  assert.equal(calls, 1);
  callbacks.shift()();
  await new Promise(setImmediate);
  assert.equal(calls, 2);
  assert.equal(mount.innerHTML, '<p>Shared result</p>');
});

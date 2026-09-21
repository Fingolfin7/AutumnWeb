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
  assert.deepEqual(timers, [8000, 135000]);
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

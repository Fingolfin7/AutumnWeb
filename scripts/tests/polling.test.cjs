const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

// Run the shipped scripts with a controlled clock and network. No browser or
// third-party package is needed to enforce the background request budget.
function page(filename, { hidden = false, dashboard = false } = {}) {
  const callbacks = new Map();
  const timers = new Map();
  const requests = [];
  const events = [];
  let nextId = 0;
  const fragment = {
    dirty: false,
    outerHTML: 'original',
    getAttribute(name) {
      return {
        'data-refresh-url': '/timers/fragment/',
        'data-timer-surface': 'dashboard',
        'data-timeline-url': '/timeline/',
        'data-timeline-range': 'today',
      }[name] || null;
    },
    querySelector() { return this.dirty ? {} : null; },
    querySelectorAll() { return []; },
  };
  const document = {
    hidden,
    readyState: 'complete',
    activeElement: null,
    querySelector(selector) {
      return selector === (dashboard ? '[data-timeline]' : '#active-timers') ? fragment : null;
    },
    querySelectorAll() { return []; },
    addEventListener(name, callback) {
      callbacks.set(name, [...(callbacks.get(name) || []), callback]);
    },
    dispatchEvent(event) { events.push(event.type); },
  };
  const context = {
    document,
    window: { addEventListener() {}, location: { reload() {} } },
    CustomEvent: class { constructor(type) { this.type = type; } },
    setTimeout(fn, delay) { timers.set(++nextId, { fn, delay }); return nextId; },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, delay) { timers.set(++nextId, { fn, delay, repeat: true }); return nextId; },
    clearInterval(id) { timers.delete(id); },
    fetch() {
      return new Promise((resolve, reject) => requests.push({ resolve, reject }));
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../core/static/core/js', filename), 'utf8'), context);
  return {
    document, fragment, timers, requests, events,
    visibility(hidden) {
      document.hidden = hidden;
      for (const callback of callbacks.get('visibilitychange') || []) callback();
    },
    tick() {
      for (const [id, timer] of [...timers]) {
        if (!timer.repeat) timers.delete(id);
        timer.fn();
      }
    },
  };
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const success = { ok: true, text: async () => 'updated' };

test('hidden timer tabs have no scheduled work and refresh immediately on return', async () => {
  const p = page('timer_poll.js', { hidden: true });
  assert.equal(p.timers.size, 0);
  p.visibility(false);
  assert.equal(p.requests.length, 1);
  p.requests[0].resolve(success);
  await settle();
  assert.equal(p.fragment.outerHTML, 'updated');
  assert.equal(p.timers.size, 1);
  p.visibility(true);
  assert.equal(p.timers.size, 0);
});

test('timer requests do not overlap and in-flight responses preserve edits', async () => {
  const p = page('timer_poll.js');
  p.tick();
  p.visibility(true);
  p.visibility(false);
  assert.equal(p.requests.length, 1);
  p.fragment.dirty = true;
  p.requests[0].resolve(success);
  await settle();
  assert.equal(p.fragment.outerHTML, 'original');
  p.tick();
  assert.equal(p.requests.length, 1);
  assert.equal(p.timers.size, 1);
});

test('hiding during a request prevents replacement and further polling', async () => {
  const p = page('timer_poll.js');
  p.tick();
  p.visibility(true);
  p.requests[0].resolve(success);
  await settle();
  assert.equal(p.fragment.outerHTML, 'original');
  assert.equal(p.timers.size, 0);
  assert.deepEqual(p.events, []);
});

test('failed timer requests back off to one per minute then recover', async () => {
  const p = page('timer_poll.js');
  for (const delay of [10000, 20000, 40000, 60000, 60000]) {
    p.tick();
    p.requests.at(-1).reject(new Error('offline'));
    await settle();
    assert.equal([...p.timers.values()][0].delay, delay);
  }
  p.tick();
  p.requests.at(-1).resolve(success);
  await settle();
  assert.equal([...p.timers.values()][0].delay, 5000);
});

test('dashboard timers and timeline requests pause while hidden', async () => {
  const p = page('dashboard_desk.js', { dashboard: true, hidden: true });
  assert.equal(p.timers.size, 0);
  p.visibility(false);
  assert.equal(p.timers.size, 3);
  assert.equal(p.requests.length, 1);
  p.visibility(true);
  assert.equal(p.timers.size, 0);
  p.requests[0].resolve(success);
  await settle();
  p.tick();
  assert.equal(p.requests.length, 1);
});

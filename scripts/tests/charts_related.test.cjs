const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// The Charts "Including related" pill must follow the chart on screen: a
// cached payload brings back its own X-Autumn-Related state, and a response
// that arrives for an older render never overwrites the current one.
function loadCharts() {
  let pill = {
    text: 'Including related', title: '',
    replaceChildren(...parts) { this.text = parts.map((part) => part.textContent).join(''); },
    removeAttribute() { this.title = ''; },
  };
  const pending = [];
  const $ = () => ({ val: () => '/api/v2/reports/charts/', ready() {} });
  $.ajax = (options) => pending.push(options);
  const context = {
    window: {}, $, URLSearchParams, console: { log() {} },
    document: {
      getElementById: (id) => (id === 'related-pill' ? pill : null),
      createElement: () => ({ textContent: '' }),
      createTextNode: (text) => ({ textContent: text }),
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../core/static/core/js/charts/core.js'), 'utf8'), context);
  const fetch = (type) => context.get_project_data(type, '', '', 'oauth', '', [], [], [], '', true);
  const reply = (index, state) => pending[index].success([{ count: 1 }], 'success', { getResponseHeader: () => state });
  // What render() does once its generation check passes.
  const showCurrent = () => vm.runInContext('updateRelatedPill(relatedStateByUrl.get(lastChartDataUrl))', context);
  return { fetch, reply, showCurrent, pending, pill: () => pill, removePill: () => { pill = null; }, context };
}

test('related requests carry related=true', () => {
  const charts = loadCharts();
  charts.fetch('pie');
  assert.match(charts.pending[0].url, /[?&]related=true(&|$)/);
});

test('a cached chart shows its own related state', async () => {
  const charts = loadCharts();
  const pie = charts.fetch('pie'); charts.reply(0, 'included'); await pie; charts.showCurrent();
  const bar = charts.fetch('bar'); charts.reply(1, 'unavailable'); await bar; charts.showCurrent();
  assert.equal(charts.pill().text, 'Related unavailable');
  await charts.fetch('pie'); charts.showCurrent();
  assert.equal(charts.pending.length, 2);
  assert.equal(charts.pill().text, 'Including related');
});

test('a late response for an older chart does not change the pill', async () => {
  const charts = loadCharts();
  const old = charts.fetch('pie');
  const current = charts.fetch('bar'); charts.reply(1, 'included'); await current; charts.showCurrent();
  charts.reply(0, 'unavailable'); await old;
  assert.equal(charts.pill().text, 'Including related');
});

test('a page without the pill is left alone', () => {
  const charts = loadCharts();
  charts.removePill();
  assert.doesNotThrow(() => charts.context.updateRelatedPill('unavailable'));
});

test('a response that outlived a Refresh does not overwrite the newer state', async () => {
  const charts = loadCharts();
  const old = charts.fetch('pie');
  charts.context.invalidateChartData();
  const fresh = charts.fetch('pie'); charts.reply(1, 'included'); await fresh;
  charts.reply(0, 'unavailable'); await old;
  charts.fetch('bar'); // switch away (still loading)...
  await charts.fetch('pie'); charts.showCurrent(); // ...and back to the cached pie
  assert.equal(charts.pill().text, 'Including related');
});

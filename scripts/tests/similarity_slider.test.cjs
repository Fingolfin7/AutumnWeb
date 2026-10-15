const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// The Related slider's arithmetic: which per-step count the readout shows
// while dragging, and the URL that re-runs the search when it is let go.
function loadSlider() {
  const context = { window: {}, URL };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, '../../core/static/core/js/similarity_slider.js'), 'utf8'),
    context,
  );
  return context.window.AutumnSimilarity;
}

test('the readout counts the step nearest the thumb', () => {
  const slider = loadSlider();
  const counts = [9, 7, 5, 3];
  assert.equal(slider.countAt(counts, 0.25, 0.25, 0.01), 9);
  // Float drift (0.27 / 0.01 is not exactly 2) still lands on its step.
  assert.equal(slider.countAt(counts, 0.27, 0.25, 0.01), 5);
  assert.equal(slider.countAt(counts, 0.99, 0.25, 0.01), 3);
  assert.equal(slider.countAt(null, 0.3, 0.25, 0.01), null);
});

test('letting go sets ?similarity= and restarts the Related pager', () => {
  const slider = loadSlider();
  const url = new URL(slider.urlFor('https://autumn.test/sessions/?search=figured+it+out&related_page=3&page=2', 0.37, 0.45));
  assert.equal(url.searchParams.get('similarity'), '0.37');
  assert.equal(url.searchParams.get('related_page'), null);
  assert.equal(url.searchParams.get('page'), '2');
  assert.equal(url.searchParams.get('search'), 'figured it out');
});

test('the account default leaves ?similarity= out', () => {
  const slider = loadSlider();
  const url = new URL(slider.urlFor('https://autumn.test/sessions/?search=x&similarity=0.38', 0.45, 0.45));
  assert.equal(url.searchParams.has('similarity'), false);
});

test('positions run floor to ceiling as 0-100', () => {
  const slider = loadSlider();
  assert.equal(slider.position(0.25, 0.25, 0.6), 0);
  assert.equal(Math.round(slider.position(0.45, 0.25, 0.6) * 100) / 100, 57.14);
  assert.equal(slider.position(0.6, 0.25, 0.6), 100);
});

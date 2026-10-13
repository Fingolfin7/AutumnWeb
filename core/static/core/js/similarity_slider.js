/* ============================================================================
   AUTUMN — RELATED SLIDER                                  similarity_slider.js
   ----------------------------------------------------------------------------
   How close a meaning-based match must be to count as related
   (core/partials/similarity_slider.html). The range moves in hundredths;
   the named stops (Loose, Moderate, Strict) are markers along it, and their
   labels jump straight to them.

     page mode   while dragging, the readout shows how many related matches
                 the position would keep (data-counts: one count per step,
                 floor to ceiling, from the search the page already ran, so
                 no request is made). Letting go re-runs the search with
                 ?similarity=, left out at the account's default.
     field mode  (data-field) the slider only sets its hidden form field,
                 which data-omit-default empties at the account's default.
   ==========================================================================*/
(function (root) {
  "use strict";

  var NAVIGATE_DELAY_MS = 450;

  function countAt(counts, value, floor, step) {
    if (!counts || !counts.length) { return null; }
    var index = Math.round((value - floor) / step);
    return counts[Math.max(0, Math.min(counts.length - 1, index))];
  }

  function position(value, floor, ceiling) {
    return ((value - floor) / (ceiling - floor)) * 100;
  }

  /* The URL that re-runs this search at ``value``: other params kept, the
     Related pager reset (its pages no longer line up). */
  function urlFor(href, value, fallback) {
    var url = new URL(href);
    url.searchParams.delete("related_page");
    if (value.toFixed(2) === fallback.toFixed(2)) {
      url.searchParams.delete("similarity");
    } else {
      url.searchParams.set("similarity", value.toFixed(2));
    }
    return url.toString();
  }

  function init(container) {
    var range = container.querySelector(".similarity-range");
    if (!range) { return; }
    var floor = parseFloat(range.min);
    var ceiling = parseFloat(range.max);
    var step = parseFloat(range.step);
    var fallback = parseFloat(container.getAttribute("data-default"));
    var counts = null;
    try { counts = JSON.parse(container.getAttribute("data-counts") || "null"); }
    catch (error) { counts = null; }
    var valueOut = container.querySelector("[data-similarity-value]");
    var countOut = container.querySelector("[data-similarity-count]");
    var field = container.querySelector("[data-similarity-field]");
    var fieldMode = container.hasAttribute("data-field");
    var omitDefault = container.hasAttribute("data-omit-default");
    var applied = parseFloat(range.value);
    var timer = null;

    function show(value) {
      container.style.setProperty("--fill", position(value, floor, ceiling).toFixed(2));
      if (valueOut) { valueOut.textContent = value.toFixed(2); }
      var count = countAt(counts, value, floor, step);
      if (countOut && count !== null) { countOut.textContent = String(count); }
      range.setAttribute(
        "aria-valuetext",
        value.toFixed(2) + (count === null ? "" : ", " + count + " related")
      );
      Array.prototype.forEach.call(container.querySelectorAll(".similarity-mark"), function (mark) {
        mark.classList.toggle("is-passed", parseFloat(mark.getAttribute("data-value")) <= value + 1e-9);
      });
      Array.prototype.forEach.call(container.querySelectorAll(".similarity-labels [data-similarity-set]"), function (label) {
        label.classList.toggle("is-current", parseFloat(label.getAttribute("data-similarity-set")).toFixed(2) === value.toFixed(2));
      });
    }

    function current() {
      return Math.round(parseFloat(range.value) / step) * step;
    }

    function commit(value) {
      if (fieldMode) {
        if (field) {
          field.value = value.toFixed(2);
          field.disabled = omitDefault && value.toFixed(2) === fallback.toFixed(2);
        }
        return;
      }
      window.clearTimeout(timer);
      if (value.toFixed(2) === applied.toFixed(2)) { return; }
      // Arrow keys fire a change per press: wait until they settle.
      timer = window.setTimeout(function () {
        container.classList.add("is-loading");
        window.location.assign(urlFor(window.location.href, value, fallback));
      }, NAVIGATE_DELAY_MS);
    }

    range.addEventListener("input", function () { show(current()); });
    range.addEventListener("change", function () { commit(current()); });
    Array.prototype.forEach.call(container.querySelectorAll("[data-similarity-set]"), function (button) {
      button.addEventListener("click", function () {
        range.value = button.getAttribute("data-similarity-set");
        var value = current();
        show(value);
        commit(value);
      });
    });

    show(applied);
    if (fieldMode) { commit(applied); }
  }

  function initAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-similarity]"), init);
  }

  root.AutumnSimilarity = { countAt: countAt, position: position, urlFor: urlFor };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initAll);
    } else {
      initAll();
    }
  }
})(typeof window !== "undefined" ? window : this);

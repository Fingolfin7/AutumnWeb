/* ============================================================================
   AUTUMN — BACKDROP DIMMING SLIDER                          background_dim.js
   ----------------------------------------------------------------------------
   The header slider that dims the backdrop photo behind the app. Two speeds,
   deliberately decoupled:

     the eye    every input event writes --background-dim-opacity straight onto
                <body>, so the photo responds while the thumb is still moving.
     the server one debounced POST after the drag settles. A range input fires
                on every pixel; saving each one would be dozens of writes per
                drag for a value only the last of which matters.

   The page never waits on the request and never reverts if it fails — the
   local change has already happened and is what the user asked for. A failed
   save costs them the setting on the next load, which is not worth a jarring
   snap-back or an error banner over a brightness control.

   The same value is editable on the Profile page, which owns the canonical
   form field; this only writes the one integer.
   ==========================================================================*/
(function () {
  "use strict";

  var SAVE_DEBOUNCE_MS = 400;

  function init() {
    var slider = document.getElementById("header-dimming");
    if (!slider) { return; }

    var url = slider.getAttribute("data-dim-url");
    var control = slider.closest(".dim-control");
    var tokenField = control && control.querySelector("[name=csrfmiddlewaretoken]");
    var timer = null;

    function apply() {
      var pct = Math.max(0, Math.min(85, parseInt(slider.value, 10) || 0));
      document.body.style.setProperty(
        "--background-dim-opacity", (pct / 100).toFixed(2)
      );
      return pct;
    }

    function save(pct) {
      if (!url || !tokenField) { return; }
      var body = new FormData();
      body.append("value", pct);
      body.append("csrfmiddlewaretoken", tokenField.value);
      fetch(url, { method: "POST", body: body, credentials: "same-origin" })
        .catch(function () { /* see the note above: the local change stands */ });
    }

    slider.addEventListener("input", function () {
      var pct = apply();
      window.clearTimeout(timer);
      timer = window.setTimeout(function () { save(pct); }, SAVE_DEBOUNCE_MS);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

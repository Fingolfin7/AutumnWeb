/* ============================================================================
   AUTUMN — SERVER TIMES → THE BROWSER'S CLOCK                  local_times.js
   ----------------------------------------------------------------------------
   The `time_formatter` template filter renders a clock time twice: the server's
   rendering as the visible text, and the same instant in UTC as a data-utc-time
   attribute. This converts the former to the reader's own timezone on load, so
   a session that started at 14:05 for them does not read 12:05 because the
   server lives elsewhere. Without it the page still shows a correct time — just
   the server's — which is why this must never throw on a bad value.

   Loaded by the shell, so it runs on every page. Fragments that arrive later
   over the wire never saw this pass; dashboard_desk.js re-runs the same
   conversion on polled cards (see localiseTimes there).

   This was the surviving third of script.js. The other two thirds — a burger
   menu for a sidebar the Focus Desk shell does not have, and a duplicate of
   the Insights scroll-to-bottom — went with the legacy shell in chunk 13.
   Deliberately no jQuery: the shell should not need it to render correctly.
   ==========================================================================*/
(function () {
  "use strict";

  function localiseTimes(root) {
    root.querySelectorAll("[data-utc-time]").forEach(function (el) {
      var stamp = Date.parse(el.getAttribute("data-utc-time"));
      if (isNaN(stamp)) { return; }   // keep the server's rendering
      el.textContent = new Date(stamp).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      localiseTimes(document);
    });
  } else {
    localiseTimes(document);
  }
})();

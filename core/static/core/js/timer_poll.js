/* ============================================================================
   AUTUMN — ACTIVE-TIMER FRAGMENT POLL                            timer_poll.js
   ----------------------------------------------------------------------------
   Re-fetches the #active-timers fragment every five seconds while visible, so
   a timer started from the CLI, the API or another tab shows up here without a
   reload. The container carries its own data-refresh-url and data-timer-surface
   because the two surfaces (dashboard, timers) render different partials from
   the same endpoint.

   It only replaces markup. Anything that needs to re-run against the new nodes
   listens for `autumn:timers-refreshed`, which is dispatched on document after
   every successful swap — dashboard_desk.js uses it to rebuild the focus deck.

   THE DIRTY-EDITOR GUARD IS LOAD-BEARING. A timer note is edited in place
   inside this fragment; swapping it out mid-edit would discard what the user
   was typing. So the poll skips a beat whenever the note editor is focused or
   marked data-dirty, and re-checks after the response arrives, since the user
   can start typing while it is in flight.

   Hidden tabs pause completely and refresh when visible again. Failures back
   off to one attempt per minute so an outage does not cause a request storm.
   ==========================================================================*/
(function () {
  "use strict";

  var SELECTOR = "#active-timers";
  var SYNC_INTERVAL_MS = 5000;
  var retryDelay = SYNC_INTERVAL_MS;
  var refreshTimeout;
  var refreshInFlight = false;

  function scheduleRefresh() {
    clearTimeout(refreshTimeout);
    if (!document.hidden) {
      refreshTimeout = setTimeout(refreshTimerSection, retryDelay);
    }
  }

  function isBeingEdited(container) {
    var active = document.activeElement;
    if (active && active.closest && active.closest("[data-timer-note-editor]")) {
      return true;
    }
    return !!container.querySelector('[data-timer-note-editor][data-dirty="true"]');
  }

  function refreshTimerSection() {
    var container = document.querySelector(SELECTOR);
    if (document.hidden || refreshInFlight || !container) { return; }

    var url = container.getAttribute("data-refresh-url");
    var surface = container.getAttribute("data-timer-surface");
    if (!url || !surface) { return; }
    if (isBeingEdited(container)) { scheduleRefresh(); return; }

    refreshInFlight = true;
    fetch(url + "?surface=" + encodeURIComponent(surface), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then(function (response) {
        if (response.redirected) {
          /* Fetch follows Django's login redirect and otherwise hands us a
             200 login page. Reload the full page so its `next` stays useful. */
          window.location.reload();
          throw new Error("authentication redirect");
        }
        if (!response.ok) { throw new Error(response.status); }
        return response.text();
      })
      .then(function (html) {
        retryDelay = SYNC_INTERVAL_MS;
        /* Re-read the container: this is the post-await re-check, and the
           element may have been replaced or the user may have started typing
           while the request was in flight. */
        var current = document.querySelector(SELECTOR);
        if (document.hidden || !current || isBeingEdited(current)) { return; }
        current.outerHTML = html;
        document.dispatchEvent(new CustomEvent("autumn:timers-refreshed"));
      })
      .catch(function () {
        retryDelay = Math.min(retryDelay * 2, 60000);
      })
      .then(function () {
        refreshInFlight = false;
        scheduleRefresh();
      });
  }

  document.addEventListener("visibilitychange", function () {
    clearTimeout(refreshTimeout);
    if (!document.hidden) { refreshTimerSection(); }
  });
  scheduleRefresh();
})();

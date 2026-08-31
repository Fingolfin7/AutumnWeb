/* ============================================================================
   AUTUMN — ACTIVE-TIMER FRAGMENT POLL                            timer_poll.js
   ----------------------------------------------------------------------------
   Re-fetches the #active-timers fragment every five seconds and swaps it in, so
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

   Was dynamic_timers.js (chunk 13). It also carried an updateDurations() that
   ticked `.timer-duration` once a second — dead code: that class only appears
   on the stop/remove confirm pages, which sit OUTSIDE #active-timers, and the
   selector was scoped to inside it. The polled partials have no .timer-duration
   at all. Rewritten without jQuery on the way past.
   ==========================================================================*/
(function () {
  "use strict";

  var SELECTOR = "#active-timers";
  var SYNC_INTERVAL_MS = 5000;
  var refreshInFlight = false;

  function isBeingEdited(container) {
    var active = document.activeElement;
    if (active && active.closest && active.closest("[data-timer-note-editor]")) {
      return true;
    }
    return !!container.querySelector('[data-timer-note-editor][data-dirty="true"]');
  }

  function refreshTimerSection() {
    var container = document.querySelector(SELECTOR);
    if (refreshInFlight || !container) { return; }

    var url = container.getAttribute("data-refresh-url");
    var surface = container.getAttribute("data-timer-surface");
    if (!url || !surface) { return; }
    if (isBeingEdited(container)) { return; }

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
        /* Re-read the container: this is the post-await re-check, and the
           element may have been replaced or the user may have started typing
           while the request was in flight. */
        var current = document.querySelector(SELECTOR);
        if (!current || isBeingEdited(current)) { return; }
        current.outerHTML = html;
        document.dispatchEvent(new CustomEvent("autumn:timers-refreshed"));
      })
      .catch(function () {
        /* Offline, a 500, a redirect to the login page — all transient from
           here. Leave the markup alone; the next tick tries again. */
      })
      .then(function () {
        refreshInFlight = false;
      });
  }

  setInterval(refreshTimerSection, SYNC_INTERVAL_MS);
})();

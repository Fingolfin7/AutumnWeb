/* ============================================================================
   AUTUMN — DASHBOARD (Focus Desk) PAGE BEHAVIOUR             dashboard_desk.js
   ----------------------------------------------------------------------------
   Page-specific only. Shell behaviour (disclosure, sheet, note expansion)
   lives in focus_desk.js; this file owns the three things that are unique to
   the dashboard:

     1. LIVE FOCUS CARDS   elapsed time, auto-stop countdown and bar fill,
                           repainted every second from the card's own
                           data-start-time / data-auto-stop-at.
     2. FOCUS DECK DOTS    the phone carousel's position indicator. Inert on
                           the desk, where CSS turns the track into a grid and
                           hides the dots.
     3. ACTIVITY RANGE     week / 2 weeks / month over the 30 pre-rendered
                           calendar cells.

   The running-timer cards are re-rendered server-side every five seconds by
   dynamic_timers.js, which fires `autumn:timers-refreshed` afterwards. Nothing
   here holds a reference to a card across that swap: every tick re-queries.
   ==========================================================================*/
(function () {
  "use strict";

  var DESK_BREAKPOINT = 1000;

  function pad(n) { return String(n).padStart(2, "0"); }

  /* ------------------------------------------------------- live timers ---
     Mirrors the `hero_duration` template filter exactly: the server renders
     the first frame, this repaints every one after it, and a mismatch would
     show up as a visible jump on the first tick. */
  function heroParts(totalSeconds) {
    var days = Math.floor(totalSeconds / 86400);
    var hours = Math.floor((totalSeconds % 86400) / 3600);
    var minutes = Math.floor((totalSeconds % 3600) / 60);
    var seconds = Math.floor(totalSeconds % 60);

    if (days > 0) { return [[days, "day"], [hours, "hour"]]; }
    if (hours > 0) { return [[hours, "hour"], [minutes, "minute"]]; }
    return [[minutes, "minute"], [seconds, "second"]];
  }

  function plural(value, word) { return value === 1 ? word : word + "s"; }

  function paintElapsed(el, totalSeconds) {
    el.innerHTML = heroParts(totalSeconds).map(function (part) {
      return '<span class="focus-time-part">' +
             '<span class="num">' + part[0] + '</span>' +
             '<span class="unit">' + plural(part[0], part[1]) + '</span>' +
             '</span>';
    }).join("");
  }

  function tickCards() {
    var now = Date.now();

    document.querySelectorAll(".focus-card[data-start-time]").forEach(function (card) {
      var start = Date.parse(card.getAttribute("data-start-time"));
      if (isNaN(start)) { return; }

      var elapsed = card.querySelector("[data-timer-elapsed]");
      if (elapsed) {
        paintElapsed(elapsed, Math.max(0, Math.floor((now - start) / 1000)));
      }

      var stopAtRaw = card.getAttribute("data-auto-stop-at");
      if (!stopAtRaw) { return; }
      var stopAt = Date.parse(stopAtRaw);
      if (isNaN(stopAt) || stopAt <= start) { return; }

      var countdown = card.querySelector("[data-timer-countdown]");
      if (countdown) {
        var left = Math.max(0, Math.floor((stopAt - now) / 1000));
        countdown.textContent =
          pad(Math.floor(left / 3600)) + ":" +
          pad(Math.floor((left % 3600) / 60)) + ":" +
          pad(left % 60);
      }

      var fill = card.querySelector("[data-timer-autostop-fill]");
      if (fill) {
        var pct = (now - start) / (stopAt - start) * 100;
        fill.style.width = Math.max(0, Math.min(100, pct)).toFixed(1) + "%";
      }
    });
  }

  /* Times rendered by the `time_formatter` filter carry their UTC instant and
     are converted to the browser's clock by script.js on load. Cards that
     arrive later, via the poll, never saw that pass — so redo it for them. */
  function localiseTimes(root) {
    root.querySelectorAll("[data-utc-time]").forEach(function (el) {
      var stamp = Date.parse(el.getAttribute("data-utc-time"));
      if (isNaN(stamp)) { return; }
      el.textContent = new Date(stamp).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
      });
    });
  }

  /* --------------------------------------------------------- deck dots ---
     One dot per card. Rebuilt after a refresh because the number of running
     timers is exactly what the refresh changes. */
  function syncDots() {
    var track = document.querySelector("[data-focus-track]");
    var dots = document.querySelector("[data-focus-dots]");
    if (!track || !dots) { return; }

    var cards = track.querySelectorAll(".focus-card");
    if (dots.children.length !== cards.length) {
      dots.innerHTML = "";
      for (var i = 0; i < cards.length; i++) {
        var dot = document.createElement("span");
        dot.className = "focus-dot";
        dots.appendChild(dot);
      }
    }
    markActiveDot(track, dots);
  }

  function markActiveDot(track, dots) {
    var step = track.clientWidth + 12;
    var index = step > 0 ? Math.round(track.scrollLeft / step) : 0;
    Array.prototype.forEach.call(dots.children, function (dot, n) {
      dot.classList.toggle("is-active", n === index);
    });
  }

  document.addEventListener("scroll", function (event) {
    var track = event.target.closest ? event.target.closest("[data-focus-track]") : null;
    if (!track) { return; }
    var dots = document.querySelector("[data-focus-dots]");
    if (dots) { markActiveDot(track, dots); }
  }, true);

  document.addEventListener("click", function (event) {
    var dot = event.target.closest("[data-focus-dots] .focus-dot");
    if (!dot) { return; }
    var track = document.querySelector("[data-focus-track]");
    if (!track) { return; }
    var index = Array.prototype.indexOf.call(dot.parentNode.children, dot);
    track.scrollTo({ left: index * (track.clientWidth + 12), behavior: "smooth" });
  });

  /* ---------------------------------------------------------- timeline ---
     Network budget. The chart changes for two different reasons and they
     deserve different treatment:

       the live block grows      every second, but it is pure geometry — the
                                 client already knows the window and the start
                                 instant, so it is recomputed locally and costs
                                 nothing. TIMELINE_TICK_MS.

       the chart's SHAPE changes a timer started or stopped, a session was
                                 edited elsewhere. Only then is a refetch
                                 worth a request, and the five-second timer
                                 poll already tells us when the running set
                                 changed. TIMELINE_HEARTBEAT_MS is the slow
                                 backstop for changes made outside this tab
                                 (CLI, API, another device).

     So: one cheap local tick, and a request only when something structural
     actually happened. */
  var TIMELINE_TICK_MS = 30 * 1000;
  var TIMELINE_HEARTBEAT_MS = 5 * 60 * 1000;

  var timelineFetchInFlight = false;
  var lastRunningSignature = null;

  function compactMinutes(minutes) {
    var whole = Math.round(minutes);
    var hours = Math.floor(whole / 60);
    var mins = whole % 60;
    return hours ? hours + "h " + pad(mins) + "m" : mins + "m";
  }

  function clockLabel(stamp) {
    var d = new Date(stamp);
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  /* Mirrors build_timeline's percentages: the server draws the first frame,
     this walks it forward. Both map the same absolute window onto 0-100%. */
  function tickTimeline() {
    var root = document.querySelector("[data-timeline]");
    if (!root) { return; }

    var bounds = (root.getAttribute("data-timeline-window") || "").split("|");
    var windowStart = Date.parse(bounds[0]);
    var windowEnd = Date.parse(bounds[1]);
    if (isNaN(windowStart) || isNaN(windowEnd) || windowEnd <= windowStart) { return; }

    var now = Date.now();
    function pct(stamp) {
      var value = (stamp - windowStart) / (windowEnd - windowStart) * 100;
      return Math.max(0, Math.min(100, value));
    }

    var marker = root.querySelector("[data-now-marker]");
    if (marker && now >= windowStart && now <= windowEnd) {
      marker.style.setProperty("--x", pct(now).toFixed(4) + "%");
      var label = marker.querySelector("[data-now-label]");
      if (label) { label.textContent = clockLabel(now); }
    }

    root.querySelectorAll("[data-live-block]").forEach(function (block) {
      var started = Date.parse(block.getAttribute("data-start-iso"));
      if (isNaN(started)) { return; }
      var from = Math.max(started, windowStart);
      var startPct = pct(from);
      var endPct = pct(now);

      block.style.setProperty("--start", startPct.toFixed(4) + "%");
      block.style.setProperty("--end", endPct.toFixed(4) + "%");
      block.style.setProperty("--w", Math.max(0, endPct - startPct).toFixed(4) + "%");

      var duration = block.querySelector("[data-live-dur]");
      if (duration) { duration.textContent = compactMinutes((now - from) / 60000); }
    });
  }

  function currentRange() {
    var root = document.querySelector("[data-timeline]");
    return (root && root.getAttribute("data-timeline-range")) || "today";
  }

  function refetchTimeline(range) {
    var root = document.querySelector("[data-timeline]");
    if (!root || timelineFetchInFlight) { return; }
    var url = root.getAttribute("data-timeline-url");
    if (!url) { return; }

    timelineFetchInFlight = true;
    fetch(url + "?range=" + encodeURIComponent(range || currentRange()), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then(function (response) {
        return response.ok ? response.text() : Promise.reject(response.status);
      })
      .then(function (html) {
        var current = document.querySelector("[data-timeline]");
        if (current) { current.outerHTML = html; }
        /* The replacement is a fresh server frame; walk it to this instant so
           it does not sit a poll-interval stale. */
        tickTimeline();
      })
      .catch(function () { /* a dropped poll is not worth surfacing */ })
      .then(function () { timelineFetchInFlight = false; });
  }

  /* Which timers are running, as a comparable string. */
  function runningSignature() {
    var ids = [];
    document.querySelectorAll(".focus-card[data-timer-id]").forEach(function (card) {
      ids.push(card.getAttribute("data-timer-id"));
    });
    return ids.sort().join(",");
  }

  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-tlrange]");
    if (!tab) { return; }
    refetchTimeline(tab.getAttribute("data-tlrange"));
  });

  /* ---------------------------------------------------- activity range ---
     All 30 days are rendered server-side; narrowing the range hides the
     leading cells rather than refetching. The first visible cell is pushed to
     its real weekday column so the grid stays aligned to Mon–Sun. */
  function setActivityRange(days) {
    var grid = document.querySelector("[data-cal-grid]");
    var caption = document.querySelector("[data-cal-caption]");
    if (!grid) { return; }

    var cells = Array.prototype.slice.call(grid.querySelectorAll(".cal-cell"));
    var start = Math.max(0, cells.length - days);

    cells.forEach(function (cell, index) {
      var visible = index >= start;
      cell.style.display = visible ? "grid" : "none";
      cell.style.gridColumnStart = "auto";
    });

    var first = cells[start];
    if (first) {
      first.style.gridColumnStart = String(parseInt(first.dataset.weekday || "0", 10) + 1);
    }
    if (caption) { caption.textContent = "Last " + days + " days activity"; }
  }

  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-activity] .range-tab");
    if (!tab) { return; }
    tab.parentNode.querySelectorAll(".range-tab").forEach(function (other) {
      other.classList.remove("is-active");
      other.removeAttribute("aria-selected");
    });
    tab.classList.add("is-active");
    tab.setAttribute("aria-selected", "true");
    setActivityRange(parseInt(tab.dataset.range || "14", 10));
  });

  /* -------------------------------------------------------------- boot --- */
  function start() {
    tickCards();
    syncDots();
    setActivityRange(14);
    tickTimeline();
    lastRunningSignature = runningSignature();

    setInterval(tickCards, 1000);
    setInterval(tickTimeline, TIMELINE_TICK_MS);
    setInterval(function () { refetchTimeline(); }, TIMELINE_HEARTBEAT_MS);

    document.addEventListener("autumn:timers-refreshed", function () {
      var deck = document.querySelector("[data-focus-track]");
      if (deck) { localiseTimes(deck); }
      tickCards();
      syncDots();

      /* A timer appeared or disappeared, so the chart has a new shape — this
         is the one moment a refetch actually buys something. */
      var signature = runningSignature();
      if (signature !== lastRunningSignature) {
        lastRunningSignature = signature;
        refetchTimeline();
      }
    });

    /* Card widths change at the desk breakpoint, which moves the dot the
       scroll position maps to. */
    window.addEventListener("resize", function () {
      if (window.innerWidth < DESK_BREAKPOINT) { syncDots(); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

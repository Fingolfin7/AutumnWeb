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
      return '<span class="num">' + part[0] + '</span>' +
             '<span class="unit">' + plural(part[0], part[1]) + '</span>';
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
    setInterval(tickCards, 1000);

    document.addEventListener("autumn:timers-refreshed", function () {
      var deck = document.querySelector("[data-focus-track]");
      if (deck) { localiseTimes(deck); }
      tickCards();
      syncDots();
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

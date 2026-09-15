/* ============================================================================
   AUTUMN — "FOCUS DESK" SHELL BEHAVIOUR
   ----------------------------------------------------------------------------
   Shell-level only: things every page that extends base_fd.html gets for free.
   Page-specific behaviour (timeline, activity calendar, live timers) belongs
   in that page's own script, not here.

   Everything is delegated from `document`, so markup rendered after load
   still works without re-binding.
   ==========================================================================*/
(function () {
  "use strict";

  /* -------------------------------------------------------- disclosure ---
     A .disclose slab collapses by toggling .is-closed on the container.     */
  document.addEventListener("click", function (event) {
    var head = event.target.closest("[data-disclose] .disclose-head");
    if (!head) { return; }
    var box = head.closest("[data-disclose]");
    var closed = box.classList.toggle("is-closed");
    head.setAttribute("aria-expanded", String(!closed));
  });

  /* ------------------------------------------------------------- sheet ---
     The bottom sheet is opened by [data-sheet-open="<id>"] and closed by any
     [data-close] inside it, or Escape. Focus returns to the opener.         */
  var lastOpener = null;

  function openSheet(id) {
    var sheet = document.getElementById(id);
    if (!sheet) { return; }
    sheet.classList.add("is-open");
    var first = sheet.querySelector("a, button, input, select, textarea");
    if (first) { first.focus(); }
  }

  function closeSheet(sheet) {
    if (!sheet) { return; }
    sheet.classList.remove("is-open");
    if (lastOpener) { lastOpener.focus(); lastOpener = null; }
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-sheet-open]");
    if (opener) {
      lastOpener = opener;
      openSheet(opener.getAttribute("data-sheet-open"));
      return;
    }
    var closer = event.target.closest(".sheet [data-close]");
    if (closer) { closeSheet(closer.closest(".sheet")); }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") { return; }
    var open = document.querySelector(".sheet.is-open");
    if (open) { closeSheet(open); }
  });

  /* ------------------------------------------------- notes: no marquee ---
     Long session notes clamp and expand on click. The legacy UI slid them
     past on hover, which was unreadable and unreachable by keyboard.        */
  document.addEventListener("click", function (event) {
    var note = event.target.closest(".session-note");
    /* let real links inside a note behave like links */
    if (!note || event.target.closest("a")) { return; }
    note.classList.toggle("is-open");
  });

  /* --------------------------------------------- self-submitting selects ---
     A <select> that navigates on change, for controls where picking IS the
     action and a separate Go button would only be a second click — currently
     the header's context switcher. The form still works without JS (there is
     a <noscript> submit), which is why this is a listener rather than an
     inline onchange.                                                        */
  document.addEventListener("change", function (event) {
    var select = event.target.closest("select[data-autosubmit]");
    if (select && select.form) { select.form.submit(); }
  });
})();

/* ------------------------------------------------------- milestones ---
   A little ceremony for the few transitions that deserve it. The server marks
   only an actual lifecycle/progress crossing with data-celebration; ordinary
   messages stay entirely quiet. Leaves are decorative and aria-hidden because
   the adjacent status message already carries the accessible announcement. */
(function () {
  "use strict";

  function reducedMotion() {
    return window.matchMedia && window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
  }

  function makeLeaf(src, single, index) {
    var leaf = document.createElement("img");
    leaf.className = "celebration-leaf" + (single ? " celebration-leaf--single" : "");
    leaf.src = src;
    leaf.alt = "";
    leaf.setAttribute("aria-hidden", "true");
    if (!single) {
      leaf.style.setProperty("--leaf-left", (8 + Math.random() * 84) + "%");
      leaf.style.setProperty("--leaf-delay", (index * 55) + "ms");
      leaf.style.setProperty("--leaf-drift", ((Math.random() * 9) - 4.5) + "rem");
      leaf.style.setProperty("--leaf-tilt", ((Math.random() * 80) - 40) + "deg");
      leaf.style.setProperty("--leaf-scale", (0.72 + Math.random() * 0.45).toFixed(2));
    }
    return leaf;
  }

  function playCelebration(message) {
    var kind = message.getAttribute("data-celebration");
    var src = message.getAttribute("data-celebration-leaf");
    if (!kind || !src || reducedMotion()) { return; }

    var layer = document.createElement("div");
    layer.className = "celebration-layer";
    layer.setAttribute("aria-hidden", "true");
    if (kind === "completion") {
      for (var i = 0; i < 11; i += 1) {
        layer.appendChild(makeLeaf(src, false, i));
      }
    } else {
      var leaf = makeLeaf(src, true, 0);
      var rect = message.getBoundingClientRect();
      leaf.style.left = Math.round(rect.left + rect.width * 0.82) + "px";
      leaf.style.top = Math.round(rect.top + rect.height * 0.2) + "px";
      layer.appendChild(leaf);
    }
    document.body.appendChild(layer);
    window.setTimeout(function () {
      if (layer.parentNode) { layer.parentNode.removeChild(layer); }
    }, kind === "completion" ? 2400 : 1500);
  }

  function start() {
    var messages = document.querySelectorAll("[data-celebration]");
    for (var i = 0; i < messages.length; i += 1) {
      playCelebration(messages[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

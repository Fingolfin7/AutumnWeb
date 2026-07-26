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
})();

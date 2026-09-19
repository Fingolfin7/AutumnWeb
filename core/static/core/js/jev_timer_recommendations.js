/*
 * Jev's timer advice is deliberately progressive. The deterministic timer
 * page paints first; this request can be slow, unavailable, or unauthorized
 * without affecting the ordinary suggestion groups.
 */
(function () {
  "use strict";

  var mount = document.querySelector("[data-jev-url]");
  if (!mount || !window.fetch) { return; }

  var controller = window.AbortController ? new AbortController() : null;
  var timeout = window.setTimeout(function () {
    if (controller) { controller.abort(); }
  }, 8000);

  fetch(mount.getAttribute("data-jev-url"), {
    credentials: "same-origin",
    headers: { "Accept": "text/html", "X-Requested-With": "XMLHttpRequest" },
    signal: controller ? controller.signal : undefined
  })
    .then(function (response) {
      if (response.status === 204 || !response.ok) { return ""; }
      return response.text();
    })
    .then(function (html) {
      if (!html || !html.trim()) { return; }
      mount.innerHTML = html;
      mount.hidden = false;
      var empty = document.getElementById("deterministic-suggestions-empty");
      if (empty) { empty.remove(); }
    })
    .catch(function () {
      /* Jev is optional advice; keep the deterministic groups untouched. */
    })
    .finally(function () {
      window.clearTimeout(timeout);
    });
})();

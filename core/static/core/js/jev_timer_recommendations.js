/*
 * Jev's timer advice is deliberately progressive. The deterministic timer
 * page paints first; this request can be slow, unavailable, or unauthorized
 * without affecting the ordinary suggestion groups.
 */
(function () {
  "use strict";

  if (!window.fetch) { return; }
  document.querySelectorAll("[data-jev-url], [data-luna-url]").forEach(function (mount) {
  var isLuna = mount.hasAttribute("data-luna-url");

  var controller = window.AbortController ? new AbortController() : null;
  var timeout = window.setTimeout(function () {
    if (controller) { controller.abort(); }
  }, isLuna ? 195000 : 8000);

  var deadline = Date.now() + (isLuna ? 195000 : 8000);
  function load() {
  return fetch(mount.getAttribute(isLuna ? "data-luna-url" : "data-jev-url"), {
    credentials: "same-origin",
    headers: { "Accept": "text/html", "X-Requested-With": "XMLHttpRequest" },
    signal: controller ? controller.signal : undefined
  })
    .then(function (response) {
      if (response.status === 202) {
        if (Date.now() + 5000 >= deadline) { throw new Error("Advice still pending"); }
        return new Promise(function (resolve) { window.setTimeout(resolve, 5000); }).then(load);
      }
      if (response.status === 204 || !response.ok) { return ""; }
      return response.text();
    });
  }
  load()
    .then(function (html) {
      if (!html || !html.trim()) {
        if (isLuna) { throw new Error("Advice unavailable"); }
        return;
      }
      mount.innerHTML = html;
      mount.hidden = false;
      var empty = document.getElementById("deterministic-suggestions-empty");
      if (empty) { empty.remove(); }
    })
    .catch(function () {
      if (isLuna) {
        var message = mount.querySelector(".suggest");
        if (message) { message.textContent = "Luna is unavailable right now. Try again on your next visit."; }
      }
      /* Jev is optional advice; keep the deterministic groups untouched. */
    })
    .finally(function () {
      window.clearTimeout(timeout);
    });
  });
})();

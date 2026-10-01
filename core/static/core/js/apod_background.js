(function () {
  "use strict";

  function init() {
    var video = document.querySelector(".workspace-bg-video");
    if (!video) { return; }
    var motion = window.matchMedia("(prefers-reduced-motion: reduce)");

    function update() {
      if (motion.matches || document.hidden) {
        video.pause();
      } else {
        video.play().catch(function () { /* The poster remains visible. */ });
      }
    }

    motion.addEventListener("change", update);
    document.addEventListener("visibilitychange", update);
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

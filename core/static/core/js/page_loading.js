(function () {
    // Grace period before showing the overlay so fast navigations never flash it
    const SHOW_DELAY_MS = 300;
    // After this long, swap in a message about the server waking up (sleeping deployments)
    const SLOW_MESSAGE_MS = 8000;
    const DEFAULT_MESSAGE = "Loading…";
    const SLOW_MESSAGE = "Still working — the server may be waking up…";

    let overlay = null;
    let messageEl = null;
    let showTimer = null;
    let slowTimer = null;

    function ensureOverlay() {
        if (overlay) {
            return;
        }
        overlay = document.createElement("div");
        overlay.className = "page-loading-overlay";
        overlay.setAttribute("aria-live", "polite");
        overlay.innerHTML =
            '<div class="loading-card">' +
            '<span class="loading-leaf">' +
            '<img src="/static/core/images/new_autumn_leaf_transparent_slanted.png" alt="">' +
            "</span>" +
            '<span class="loading-text"></span>' +
            "</div>";
        messageEl = overlay.querySelector(".loading-text");
        messageEl.textContent = DEFAULT_MESSAGE;
        document.body.appendChild(overlay);
    }

    function clearTimers() {
        if (showTimer) {
            window.clearTimeout(showTimer);
            showTimer = null;
        }
        if (slowTimer) {
            window.clearTimeout(slowTimer);
            slowTimer = null;
        }
    }

    function show() {
        ensureOverlay();
        messageEl.textContent = DEFAULT_MESSAGE;
        overlay.classList.add("visible");
        slowTimer = window.setTimeout(function () {
            messageEl.textContent = SLOW_MESSAGE;
        }, SLOW_MESSAGE_MS);
    }

    function hide() {
        clearTimers();
        if (overlay) {
            overlay.classList.remove("visible");
            messageEl.textContent = DEFAULT_MESSAGE;
        }
    }

    function scheduleShow(event) {
        clearTimers();
        showTimer = window.setTimeout(function () {
            showTimer = null;
            // A page script may have taken over (e.g. streaming import) after we ran
            if (event && event.defaultPrevented) {
                return;
            }
            show();
        }, SHOW_DELAY_MS);
    }

    function optedOut(element) {
        return element.closest("[data-no-loading]") !== null;
    }

    document.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button !== 0
            || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }

        const link = event.target.closest("a[href]");
        if (!link || link.hasAttribute("download") || optedOut(link)) {
            return;
        }
        if (link.target && link.target !== "_self") {
            return;
        }

        let url;
        try {
            url = new URL(link.href, window.location.href);
        } catch (error) {
            return;
        }
        if (url.origin !== window.location.origin) {
            return;
        }
        if (!["http:", "https:"].includes(url.protocol)) {
            return;
        }
        // Same-page anchor jumps don't reload
        if (url.hash && url.pathname === window.location.pathname
            && url.search === window.location.search) {
            return;
        }

        scheduleShow(event);
    });

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (event.defaultPrevented || !(form instanceof HTMLFormElement) || optedOut(form)) {
            return;
        }
        if (form.target && form.target !== "_self") {
            return;
        }

        scheduleShow(event);
    });

    // Fires on normal loads and bfcache restores (back/forward) — never leave a stale spinner
    window.addEventListener("pageshow", hide);
    window.addEventListener("pagehide", hide);
})();

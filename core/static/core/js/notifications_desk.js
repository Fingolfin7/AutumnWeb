(function () {
    "use strict";

    function setState(container, state, title, detail, actionLabel, action) {
        container.dataset.permState = state;
        var titleNode = container.querySelector("[data-perm-title]");
        var detailNode = container.querySelector("[data-perm-detail]");
        var actionNode = container.querySelector("[data-perm-action]");
        var unsubscribeNode = container.querySelector("[data-perm-unsubscribe]");
        if (titleNode) titleNode.textContent = title;
        if (detailNode) detailNode.textContent = detail;
        if (actionNode) {
            actionNode.textContent = actionLabel || "";
            actionNode.hidden = !actionLabel;
            actionNode.dataset.permAction = action || "";
        }
        if (unsubscribeNode) unsubscribeNode.hidden = state !== "granted";
    }

    function status(container) {
        var statusUrl = container.dataset.permStatusUrl;
        if (!window.AutumnPush || !statusUrl) return;
        if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
            setState(container, "unavailable", "Notifications are unavailable.", "This browser does not support background notifications.", "", "");
            return;
        }
        Promise.all([
            window.AutumnPush.status(statusUrl),
            navigator.serviceWorker.ready.then(function (registration) {
                return registration.pushManager.getSubscription();
            }).catch(function () { return null; })
        ]).then(function (results) {
            var data = results[0];
            var subscription = results[1];
            if (!data.available) {
                setState(container, "unavailable", "Notifications are unavailable.", data.configuration_error || "Browser push is not configured for this deployment.", "", "");
                return;
            }
            if (Notification.permission === "denied") {
                setState(container, "denied", "Notifications are blocked.", "Allow notifications for this site in your browser settings, then try again.", "", "");
            } else if (Notification.permission === "granted" && subscription) {
                setState(container, "granted", "Notifications are on for this browser.", "Reminders can arrive even when Autumn is not the front tab.", "Send a test", "test");
            } else {
                setState(container, "default", "Notifications are not enabled.", "Choose Enable only if you want reminders to reach you when Autumn is not the front tab.", "Enable notifications", "enable");
            }
        }).catch(function () {
            var statusNode = container.querySelector("[data-perm-status]");
            if (statusNode) statusNode.textContent = "Notification status is temporarily unavailable.";
        });
    }

    function init() {
        document.querySelectorAll(".nx-perm").forEach(status);
    }

    document.addEventListener("click", function (event) {
        var action = event.target.closest ? event.target.closest("[data-perm-action]") : null;
        var unsubscribe = event.target.closest ? event.target.closest("[data-perm-unsubscribe]") : null;
        var container = (action || unsubscribe) && (action || unsubscribe).closest(".nx-perm");
        if (!container || !window.AutumnPush) return;
        var statusNode = container.querySelector("[data-perm-status]");
        if (unsubscribe) {
            unsubscribe.disabled = true;
            if (statusNode) statusNode.textContent = "Turning notifications off…";
            window.AutumnPush.unsubscribe(container.dataset.permUnsubscribeUrl).then(function () {
                if (statusNode) statusNode.textContent = "Notifications are off for this browser.";
                status(container);
            }).catch(function (error) {
                if (statusNode) statusNode.textContent = error.message || "Notifications could not be turned off.";
            }).then(function () { unsubscribe.disabled = false; });
            return;
        }
        if (!action || action.dataset.busy === "true") return;
        action.dataset.busy = "true";
        action.disabled = true;
        if (statusNode) statusNode.textContent = action.dataset.permAction === "test" ? "Sending a test…" : "Asking the browser…";
        var operation = action.dataset.permAction === "test"
            ? window.AutumnPush.test(container.dataset.permTestUrl)
            : window.AutumnPush.enable(container.dataset.permStatusUrl, container.dataset.permSubscribeUrl);
        operation.then(function (result) {
            if (statusNode) statusNode.textContent = action.dataset.permAction === "test" ? "Test notification queued." : "Notifications enabled for this browser.";
            status(container);
        }).catch(function (error) {
            if (statusNode) statusNode.textContent = error.message || "Notifications could not be enabled.";
        }).then(function () {
            action.disabled = false;
            action.dataset.busy = "false";
        });
    });

    document.addEventListener("DOMContentLoaded", init);
}());

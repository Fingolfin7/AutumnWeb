(function () {
    "use strict";

    // Browser-thrown push failures (an AbortError reading "Registration failed
    // - push service error") are only diagnosable with their name attached.
    // Autumn's own errors already read as sentences, so they stay bare.
    function failureText(error, fallback) {
        var message = (error && error.message) || fallback;
        var name = error && error.name;
        return name && name !== "Error" ? name + ": " + message : message;
    }

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

    // The schedule form stays fully usable without JS: every field renders and
    // the server is the authority on the one-target rule.  This only narrows
    // what is worth looking at while filling the form in.
    function setHidden(node, hidden) {
        if (node) node.hidden = !!hidden;
    }

    function subprojectInputs(field) {
        if (!field) return [];
        return Array.prototype.slice.call(
            field.querySelectorAll("input[type=checkbox][data-parent]")
        );
    }

    function optionLabel(input) {
        return (input.closest ? input.closest("label") : null) || input.parentElement;
    }

    function syncSubprojects(projectSelect, subprojectsField) {
        if (!subprojectsField) return 0;
        var selected = projectSelect ? String(projectSelect.value || "") : "";
        var visible = 0;
        subprojectInputs(subprojectsField).forEach(function (input) {
            var matches = selected !== "" && input.dataset.parent === selected;
            if (matches) {
                visible += 1;
            } else {
                input.checked = false;
            }
            setHidden(optionLabel(input), !matches);
        });
        return visible;
    }

    function initScheduleTarget() {
        var targetSelect = document.querySelector("[data-schedule-target]");
        if (!targetSelect) return;
        var projectField = document.querySelector("[data-schedule-project-field]");
        var contextField = document.querySelector("[data-schedule-context-field]");
        var tagField = document.querySelector("[data-schedule-tag-field]");
        var subprojectsField = document.querySelector("[data-schedule-subprojects-field]");
        var projectSelect = document.querySelector("[data-schedule-project]");

        function sync() {
            var target = targetSelect.value;
            setHidden(projectField, target !== "project");
            setHidden(contextField, target !== "context");
            setHidden(tagField, target !== "tag");
            var visible = syncSubprojects(projectSelect, subprojectsField);
            setHidden(subprojectsField, target !== "project" || visible === 0);
        }

        targetSelect.addEventListener("change", sync);
        if (projectSelect) projectSelect.addEventListener("change", sync);
        sync();
    }

    function init() {
        document.querySelectorAll(".nx-perm").forEach(status);
        initScheduleTarget();
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
            if (statusNode) statusNode.textContent = failureText(error, "Notifications could not be enabled.");
        }).then(function () {
            action.disabled = false;
            action.dataset.busy = "false";
        });
    });

    document.addEventListener("DOMContentLoaded", init);
}());

(function () {
    "use strict";

    var formSelector = "[data-reminder-form]";
    var cancelSelector = "[data-cancel-reminder]";

    function csrfToken() {
        var match = document.cookie.split(";").map(function (part) {
            return part.trim();
        }).find(function (part) {
            return part.indexOf("csrftoken=") === 0;
        });
        if (match) return decodeURIComponent(match.slice("csrftoken=".length));
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? input.value : "";
    }

    function checkedMode(form) {
        var checked = form.querySelector("[data-rm-mode]:checked");
        return checked ? checked.value : "none";
    }

    function setMode(form) {
        var block = form.querySelector("[data-rm-block]");
        if (!block) return;
        var mode = checkedMode(form);
        block.dataset.mode = mode;
        block.querySelectorAll("[data-rm-panel]").forEach(function (panel) {
            var active = panel.dataset.rmPanel === mode;
            panel.hidden = !active;
            panel.querySelectorAll("input, select, textarea").forEach(function (control) {
                control.disabled = !active;
            });
        });
        updateTimezonePreview(form);
        updateRail(form);
    }

    function numberValue(selector) {
        var field = document.querySelector(selector);
        if (!field || field.disabled || field.value === "") return null;
        var value = Number(field.value);
        return Number.isFinite(value) && value > 0 ? value : null;
    }

    function durationMinutes(amountSelector, unitSelector) {
        var amount = numberValue(amountSelector);
        var unit = document.querySelector(unitSelector);
        if (amount === null || !unit || unit.disabled) return null;
        return amount * (unit.value === "hours" ? 60 : 1);
    }

    function clockLabel(date) {
        return new Intl.DateTimeFormat(undefined, {
            hour: "2-digit",
            minute: "2-digit"
        }).format(date);
    }

    function dateLabel(value) {
        if (!value) return "";
        var parts = value.split("T");
        var date = parts[0].split("-");
        if (date.length !== 3 || !parts[1]) return value;
        var candidate = new Date(Number(date[0]), Number(date[1]) - 1, Number(date[2]));
        var day = new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(candidate);
        return day + " " + date[2] + " " + date[1] + " " + date[0] + ", " + parts[1];
    }

    function updateTimezonePreview(form) {
        var input = form.querySelector("#reminder-at");
        var preview = form.querySelector("[data-rm-timezone]");
        var zoneNode = form.querySelector("[data-rm-profile-zone]");
        if (!input || !preview || !zoneNode) return;
        var zone = form.dataset.profileTimezone || zoneNode.textContent.trim() || "UTC";
        var value = input.value;
        if (value) {
            preview.textContent = "Read as " + dateLabel(value) + " in " + zone + " (your profile timezone).";
        } else {
            preview.textContent = "Read as a local time in your profile timezone (" + zone + ").";
        }
    }

    function updateRail(form) {
        var rail = form.querySelector("[data-rm-rail]");
        if (!rail) return;
        var track = rail.querySelector("[data-rm-rail-track]");
        var count = rail.querySelector("[data-rm-rail-count]");
        var plan = rail.querySelector("[data-rm-rail-plan]");
        var warning = rail.querySelector("[data-rm-rail-warning]");
        var endLabel = rail.querySelector("[data-rm-rail-end]");
        var nowLabel = rail.querySelector("[data-rm-rail-now]");
        if (!track || !count || !plan || !warning) return;

        track.querySelectorAll(".rm-tick").forEach(function (tick) { tick.remove(); });
        warning.hidden = true;
        var now = new Date();
        var mode = checkedMode(form);
        var stopMinutes = durationMinutes("#stop-after-amount", "#stop-after-unit");
        var stopAt = stopMinutes === null ? null : new Date(now.getTime() + stopMinutes * 60000);
        var fires = [];

        if (mode === "after") {
            var after = durationMinutes("#reminder-amount", "#reminder-unit");
            if (after !== null) fires.push(new Date(now.getTime() + after * 60000));
        } else if (mode === "interval") {
            var interval = durationMinutes("#interval-amount", "#interval-unit");
            if (interval !== null) {
                var horizon = stopMinutes === null ? 120 : stopMinutes;
                var max = Math.min(8, Math.floor(horizon / interval));
                for (var i = 1; i <= max; i += 1) {
                    fires.push(new Date(now.getTime() + i * interval * 60000));
                }
            }
        } else if (mode === "at") {
            var at = form.querySelector("#reminder-at");
            if (at && at.value) {
                var candidate = new Date(at.value);
                if (!Number.isNaN(candidate.getTime())) fires.push(candidate);
            }
        }

        if (nowLabel) nowLabel.textContent = "now " + clockLabel(now);
        if (endLabel) endLabel.textContent = stopAt ? "stops " + clockLabel(stopAt) : "open-ended";
        if (stopAt) {
            var stopMark = rail.querySelector("[data-rm-rail-stop]");
            if (stopMark) stopMark.hidden = false;
        } else {
            var openStop = rail.querySelector("[data-rm-rail-stop]");
            if (openStop) openStop.hidden = true;
        }

        var visibleFires = fires.filter(function (fire) { return !stopAt || fire <= stopAt; });
        fires.forEach(function (fire, index) {
            var tick = document.createElement("span");
            var beyondStop = stopAt && fire > stopAt;
            tick.className = "rm-tick" + (beyondStop ? " is-void" : (index === 0 ? " is-next" : ""));
            var denominator = stopAt ? stopAt.getTime() - now.getTime() : Math.max(120 * 60000, fire.getTime() - now.getTime());
            var position = denominator > 0 ? ((fire.getTime() - now.getTime()) / denominator) * 100 : 100;
            tick.style.setProperty("--x", Math.max(0, Math.min(100, position)) + "%");
            var screenReader = document.createElement("span");
            screenReader.className = "sr-only";
            screenReader.textContent = "Reminder at " + clockLabel(fire) + (beyondStop ? "; after the timer stops" : "");
            tick.appendChild(screenReader);
            track.appendChild(tick);
        });

        if (!fires.length || mode === "none") {
            count.textContent = "No reminders";
            plan.textContent = stopAt ? "No reminders. The timer stops itself at " + clockLabel(stopAt) + "." : "No reminders. The timer runs until you stop it.";
            return;
        }
        if (visibleFires.length !== fires.length) {
            warning.hidden = false;
            warning.textContent = "This reminder falls after the auto-stop and will not fire. Shorten the reminder or extend the timer.";
        }
        count.textContent = visibleFires.length === 1 ? "1 reminder" : visibleFires.length + " reminders";
        var labels = visibleFires.slice(0, 4).map(clockLabel);
        var suffix = visibleFires.length > labels.length ? " and more" : "";
        var sentence = mode === "interval" ? "Notifies at " : "Notifies at ";
        plan.textContent = sentence + labels.join(", ") + suffix + (stopAt ? ", then stops itself at " + clockLabel(stopAt) + "." : ".");
    }

    function setPermissionState(container, state, title, detail, actionText, action) {
        container.dataset.permState = state;
        var titleNode = container.querySelector(".rm-perm-title");
        var detailNode = container.querySelector(".rm-perm-detail");
        var actionNode = container.querySelector("[data-perm-action]");
        var unsubscribeNode = container.querySelector("[data-perm-unsubscribe]");
        if (titleNode) titleNode.textContent = title;
        if (detailNode) detailNode.textContent = detail;
        if (actionNode) {
            actionNode.textContent = actionText || "";
            actionNode.hidden = !actionText;
            actionNode.dataset.permAction = action || "";
        }
        if (unsubscribeNode) unsubscribeNode.hidden = state !== "granted";
    }

    function permissionStatus(form, container) {
        var statusNode = container.querySelector("[data-perm-status]");
        if (!window.AutumnPush || !form.dataset.pushStatusUrl) return;
        if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
            setPermissionState(container, "unavailable", "Notifications are unavailable.", "This browser does not support background notifications.", "", "");
            return;
        }
        Promise.all([
            window.AutumnPush.status(form.dataset.pushStatusUrl),
            navigator.serviceWorker.ready.then(function (registration) {
                return registration.pushManager.getSubscription();
            }).catch(function () { return null; })
        ]).then(function (results) {
            var status = results[0];
            var localSubscription = results[1];
            if (!status.available) {
                setPermissionState(container, "unavailable", "Notifications are unavailable.", status.configuration_error || "This deployment has not configured browser push yet.", "", "");
                return;
            }
            var permission = "default";
            try { permission = window.Notification ? Notification.permission : "default"; } catch (error) { /* unsupported */ }
            if (permission === "denied") {
                setPermissionState(container, "denied", "Notifications are blocked.", "Allow notifications for this site in your browser settings, then try again.", "", "");
            } else if (permission === "granted" && localSubscription) {
                setPermissionState(container, "granted", "Notifications are on for this browser.", "Reminders can arrive even when Autumn is not the front tab.", "Send a test", "test");
            } else {
                setPermissionState(container, "default", "Notifications are not enabled.", "Choose Enable only if you want reminders to reach you when Autumn is not the front tab.", "Enable notifications", "enable");
            }
        }).catch(function () {
            if (statusNode) statusNode.textContent = "Notification status is temporarily unavailable.";
        });
    }

    function initialiseForm(form) {
        if (form.dataset.remindersInitialised === "true") return;
        form.dataset.remindersInitialised = "true";
        form.querySelectorAll("[data-rm-mode]").forEach(function (radio) {
            radio.addEventListener("change", function () { setMode(form); });
        });
        form.querySelectorAll("#reminder-at, #reminder-amount, #reminder-unit, #interval-amount, #interval-unit, #stop-after-amount, #stop-after-unit").forEach(function (field) {
            field.addEventListener("input", function () { updateTimezonePreview(form); updateRail(form); });
            field.addEventListener("change", function () { updateTimezonePreview(form); updateRail(form); });
        });
        setMode(form);
        var permission = form.querySelector(".rm-perm");
        if (permission) permissionStatus(form, permission);
    }

    function initialiseAll() {
        document.querySelectorAll(formSelector).forEach(initialiseForm);
    }

    document.addEventListener("click", function (event) {
        var cancel = event.target.closest ? event.target.closest(cancelSelector) : null;
        if (cancel) {
            event.preventDefault();
            if (cancel.dataset.busy === "true") return;
            cancel.dataset.busy = "true";
            cancel.disabled = true;
            fetch(cancel.dataset.cancelUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-CSRFToken": csrfToken() }
            }).then(function (response) {
                if (response.redirected) throw new Error("authentication required");
                if (!response.ok) throw new Error("cancel failed");
                return response.json();
            }).then(function () {
                var row = cancel.closest("[data-reminder-row]");
                if (row) row.remove();
                var list = cancel.closest("[data-reminder-list]");
                if (list && !list.querySelector("[data-reminder-row]") && !list.querySelector("[data-auto-stop-row]")) list.remove();
            }).catch(function (error) {
                cancel.disabled = false;
                cancel.dataset.busy = "false";
                var row = cancel.closest("[data-reminder-row]");
                if (row) {
                    var status = row.querySelector(".rm-live-message");
                    if (!status) {
                        status = document.createElement("span");
                        status.className = "rm-live-message";
                        row.querySelector(".rm-live-copy").appendChild(status);
                    }
                    status.textContent = error.message === "authentication required"
                        ? "Session expired; sign in again."
                        : "Could not cancel; try again.";
                }
            });
        }

        var unsubscribe = event.target.closest ? event.target.closest("[data-perm-unsubscribe]") : null;
        if (unsubscribe) {
            var unsubscribeForm = unsubscribe.closest(formSelector);
            var unsubscribeContainer = unsubscribe.closest(".rm-perm");
            if (!unsubscribeForm || !unsubscribeContainer || !window.AutumnPush) return;
            unsubscribe.disabled = true;
            var unsubscribeStatus = unsubscribeContainer.querySelector("[data-perm-status]");
            if (unsubscribeStatus) unsubscribeStatus.textContent = "Turning notifications off...";
            window.AutumnPush.unsubscribe(unsubscribeForm.dataset.pushUnsubscribeUrl).then(function () {
                if (unsubscribeStatus) unsubscribeStatus.textContent = "Notifications are off for this browser.";
                permissionStatus(unsubscribeForm, unsubscribeContainer);
                unsubscribe.disabled = false;
            }).catch(function (error) {
                if (unsubscribeStatus) unsubscribeStatus.textContent = error.message || "Notifications could not be turned off.";
                unsubscribe.disabled = false;
            });
            return;
        }

        var action = event.target.closest ? event.target.closest("[data-perm-action]") : null;
        if (!action) return;
        var form = action.closest(formSelector);
        var container = action.closest(".rm-perm");
        if (!form || !container || !window.AutumnPush) return;
        action.disabled = true;
        var statusNode = container.querySelector("[data-perm-status]");
        if (statusNode) statusNode.textContent = action.dataset.permAction === "test" ? "Sending a test..." : "Asking the browser...";
        var operation = action.dataset.permAction === "test"
            ? window.AutumnPush.test(form.dataset.pushTestUrl)
            : window.AutumnPush.enable(form.dataset.pushStatusUrl, form.dataset.pushSubscribeUrl);
        operation.then(function (result) {
            if (statusNode) {
                statusNode.textContent = action.dataset.permAction === "test"
                    ? (result.queued ? "Test notification queued." : ((result.sent || 0) + " test notification sent."))
                    : "Notifications enabled for this browser.";
            }
            permissionStatus(form, container);
        }).catch(function (error) {
            if (statusNode) statusNode.textContent = window.AutumnPush.describeError(error, "Notifications could not be enabled.");
            action.disabled = false;
        });
    });

    document.addEventListener("DOMContentLoaded", initialiseAll);
})();

(function () {
    if (!("serviceWorker" in navigator)) {
        return;
    }

    window.addEventListener("load", function () {
        navigator.serviceWorker.register("/service-worker.js").catch(function (error) {
            console.warn("Autumn service worker registration failed:", error);
        });
    });
})();

(function (window) {
    "use strict";

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

    function postJson(url, payload) {
        if (!url) return Promise.reject(new Error("Push endpoint is not available."));
        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken(),
                "X-Requested-With": "XMLHttpRequest"
            },
            body: JSON.stringify(payload || {})
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (!response.ok) throw new Error(data.error || "Push request failed.");
                return data;
            });
        });
    }

    function status(url) {
        if (!url) return Promise.reject(new Error("Push status endpoint is not available."));
        return fetch(url, {
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" }
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (!response.ok) throw new Error(data.error || "Push status failed.");
                return data;
            });
        });
    }

    function decodeBase64Url(value) {
        if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value) || value.length > 128) {
            throw new Error("Autumn's Web Push public key is invalid. Check PUSH_VAPID_PUBLIC_KEY.");
        }
        var padding = "=".repeat((4 - value.length % 4) % 4);
        var binary;
        try {
            binary = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
        } catch (error) {
            throw new Error("Autumn's Web Push public key is invalid. Check PUSH_VAPID_PUBLIC_KEY.");
        }
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        if (bytes.length !== 65 || bytes[0] !== 4) {
            throw new Error("Autumn's Web Push public key is invalid. Check PUSH_VAPID_PUBLIC_KEY.");
        }
        return bytes;
    }

    function sameApplicationServerKey(existing, expected) {
        if (!existing) return true;
        var bytes = new Uint8Array(existing);
        if (bytes.length !== expected.length) return false;
        for (var i = 0; i < bytes.length; i += 1) {
            if (bytes[i] !== expected[i]) return false;
        }
        return true;
    }

    function subscribeWithKey(registration, serverKey) {
        return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: serverKey });
    }

    function ensureSubscription(registration, serverKey) {
        return registration.pushManager.getSubscription().then(function (subscription) {
            // A subscription held under an older key re-registers happily
            // and then fails every push with 403, so replace it.
            if (subscription && sameApplicationServerKey(subscription.options && subscription.options.applicationServerKey, serverKey)) {
                return subscription;
            }
            var cleared = subscription
                ? subscription.unsubscribe().catch(function () {})
                : Promise.resolve();
            return cleared.then(function () {
                return subscribeWithKey(registration, serverKey).catch(function () {
                    // A stale or broken push registration can make the first
                    // subscribe throw "push service error". Clear anything
                    // lingering and retry once so the user does not have to
                    // clear site data by hand.
                    return registration.pushManager.getSubscription().then(function (stale) {
                        return stale ? stale.unsubscribe().catch(function () {}) : null;
                    }).then(function () {
                        return subscribeWithKey(registration, serverKey);
                    });
                });
            });
        });
    }

    function enable(statusUrl, subscribeUrl) {
        if (!("Notification" in window)) return Promise.reject(new Error("This browser does not support notifications."));
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) return Promise.reject(new Error("This browser does not support push notifications."));
        return window.Notification.requestPermission().then(function (permission) {
            if (permission !== "granted") throw new Error(permission === "denied" ? "Notifications are blocked in this browser or for the browser app in system settings." : "Notification permission was not granted.");
            return status(statusUrl);
        }).then(function (data) {
            if (!data.available || !data.public_key) throw new Error(data.configuration_error || "Browser push is not configured for this deployment.");
            return navigator.serviceWorker.ready.then(function (registration) {
                return ensureSubscription(registration, decodeBase64Url(data.public_key));
            });
        }).then(function (subscription) {
            return postJson(subscribeUrl, subscription.toJSON()).then(function (result) {
                result.subscription = subscription;
                return result;
            });
        });
    }

    function unsubscribe(url) {
        if (!("serviceWorker" in navigator)) return Promise.resolve({ removed: false });
        return navigator.serviceWorker.ready.then(function (registration) {
            return registration.pushManager.getSubscription();
        }).then(function (subscription) {
            if (!subscription) return { removed: false };
            return postJson(url, { endpoint: subscription.endpoint }).then(function (result) {
                return subscription.unsubscribe().then(function () { return result; });
            });
        });
    }

    window.AutumnPush = {
        status: status,
        enable: enable,
        unsubscribe: unsubscribe,
        test: function (url) { return postJson(url, {}); }
    };
})(window);

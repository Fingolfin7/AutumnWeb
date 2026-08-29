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
        var padding = "=".repeat((4 - value.length % 4) % 4);
        var binary = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        return bytes;
    }

    function enable(statusUrl, subscribeUrl) {
        if (!("Notification" in window)) return Promise.reject(new Error("This browser does not support notifications."));
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) return Promise.reject(new Error("This browser does not support push notifications."));
        return window.Notification.requestPermission().then(function (permission) {
            if (permission !== "granted") throw new Error(permission === "denied" ? "Notifications are blocked in this browser." : "Notification permission was not granted.");
            return status(statusUrl);
        }).then(function (data) {
            if (!data.available || !data.public_key) throw new Error("Browser push is not configured for this deployment.");
            return navigator.serviceWorker.ready.then(function (registration) {
                return registration.pushManager.getSubscription().then(function (subscription) {
                    return subscription || registration.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: decodeBase64Url(data.public_key)
                    });
                });
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

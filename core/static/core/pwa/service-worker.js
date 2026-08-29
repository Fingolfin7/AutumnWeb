const CACHE_PREFIX = "autumn-pwa";
/* Bumped to v3 in chunk 13: the precache list below changed, and installed
   clients hold the old list under the old key until the name changes. */
const PRECACHE = `${CACHE_PREFIX}-precache-v3`;
const RUNTIME = `${CACHE_PREFIX}-runtime-v3`;
const OFFLINE_URL = "/static/core/pwa/offline.html";

/* cache.addAll is all-or-nothing: one 404 rejects the install and the worker
   never activates. So every entry here must exist. style.css, colours.css and
   script.js were removed with the legacy shell. */
const PRECACHE_URLS = [
    OFFLINE_URL,
    "/static/core/css/focus_desk.css",
    "/static/core/js/local_times.js",
    "/static/core/js/pwa.js",
    "/static/core/js/page_loading.js",
    "/static/core/images/icons/autumn-icon-192.png",
    "/static/core/images/icons/autumn-icon-512.png",
    "/static/core/images/icons/autumn-maskable-512.png",
];

self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(PRECACHE).then(function (cache) {
            return cache.addAll(PRECACHE_URLS);
        })
    );
    self.skipWaiting();
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        caches.keys().then(function (cacheNames) {
            return Promise.all(
                cacheNames
                    .filter(function (cacheName) {
                        return cacheName.startsWith(CACHE_PREFIX)
                            && ![PRECACHE, RUNTIME].includes(cacheName);
                    })
                    .map(function (cacheName) {
                        return caches.delete(cacheName);
                    })
            );
        })
    );
    self.clients.claim();
});

function notificationUrl(value) {
    try {
        var url = new URL(typeof value === "string" ? value : "/timers/", self.location.origin);
        if (url.origin !== self.location.origin) return new URL("/timers/", self.location.origin).href;
        if (url.pathname !== "/timers" && !url.pathname.startsWith("/timers/")) return new URL("/timers/", self.location.origin).href;
        return url.href;
    } catch (error) {
        return new URL("/timers/", self.location.origin).href;
    }
}

self.addEventListener("push", function (event) {
    var payload = {};
    try {
        payload = event.data ? event.data.json() : {};
    } catch (error) {
        try { payload = { body: event.data ? event.data.text() : "" }; } catch (ignored) { payload = {}; }
    }
    if (!payload || typeof payload !== "object") payload = {};
    var kind = payload.kind || payload.event_type || "timer";
    var identity = payload.reminder_id || payload.session_id || "general";
    var title = payload.title || "Autumn";
    var body = payload.body || "Your timer needs your attention.";
    event.waitUntil(self.registration.showNotification(title, {
        body: body,
        tag: "autumn-" + kind + "-" + identity,
        renotify: false,
        icon: "/static/core/images/icons/autumn-icon-192.png",
        badge: "/static/core/images/icons/autumn-icon-192.png",
        data: { url: notificationUrl(payload.url), kind: kind, session_id: payload.session_id || null }
    }));
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    var target = notificationUrl(event.notification.data && event.notification.data.url);
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
            for (var i = 0; i < clientList.length; i += 1) {
                var client = clientList[i];
                if (client.url && new URL(client.url).origin === self.location.origin && "focus" in client) {
                    if ("navigate" in client && client.url !== target) {
                        return client.navigate(target).then(function (navigated) {
                            return navigated && "focus" in navigated ? navigated.focus() : client.focus();
                        });
                    }
                    return client.focus();
                }
            }
            if (self.clients.openWindow) return self.clients.openWindow(target);
            return undefined;
        })
    );
});

self.addEventListener("fetch", function (event) {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);
    if (requestUrl.origin !== self.location.origin) {
        return;
    }

    // Django-served assets (admin, DRF) have no ?v= cache-buster, so caching
    // them here would serve stale styles forever after a Django upgrade.
    if (
        requestUrl.pathname.startsWith("/admin/")
        || requestUrl.pathname.startsWith("/static/admin/")
        || requestUrl.pathname.startsWith("/static/rest_framework/")
    ) {
        return;
    }

    if (event.request.mode === "navigate") {
        event.respondWith(
            fetch(event.request).catch(function () {
                return caches.match(OFFLINE_URL);
            })
        );
        return;
    }

    if (["style", "script", "image", "font"].includes(event.request.destination)) {
        event.respondWith(
            caches.match(event.request).then(function (cachedResponse) {
                if (cachedResponse) {
                    return cachedResponse;
                }

                return fetch(event.request).then(function (networkResponse) {
                    if (
                        !networkResponse
                        || networkResponse.status !== 200
                        || networkResponse.type !== "basic"
                    ) {
                        return networkResponse;
                    }

                    const responseToCache = networkResponse.clone();
                    caches.open(RUNTIME).then(function (cache) {
                        cache.put(event.request, responseToCache);
                    });
                    return networkResponse;
                });
            })
        );
    }
});

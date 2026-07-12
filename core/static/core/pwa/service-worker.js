const CACHE_PREFIX = "autumn-pwa";
const PRECACHE = `${CACHE_PREFIX}-precache-v1`;
const RUNTIME = `${CACHE_PREFIX}-runtime-v1`;
const OFFLINE_URL = "/static/core/pwa/offline.html";

const PRECACHE_URLS = [
    OFFLINE_URL,
    "/static/core/css/style.css",
    "/static/core/css/colours.css",
    "/static/core/js/script.js",
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

self.addEventListener("fetch", function (event) {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);
    if (requestUrl.origin !== self.location.origin) {
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

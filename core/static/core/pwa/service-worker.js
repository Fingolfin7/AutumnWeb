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

/* Notification destinations are intentionally separate from the cache
   routing rules below.  A notification is untrusted data and may navigate
   only to an explicit same-origin Autumn path. */
const NOTIFICATION_PATH_PREFIXES = [
    "/timers",
    "/start_timer",
    "/notifications",
    "/commitments",
    "/update_commitment",
    "/review/weekly",
];

const NOTIFICATION_CATEGORY_PATHS = {
    timer: ["/timers"],
    reminder: ["/timers"],
    auto_stop: ["/timers"],
    test: ["/timers"],
    scheduled_reminder: ["/notifications", "/start_timer", "/timers"],
    commitment_check: ["/notifications", "/commitments", "/update_commitment", "/start_timer"],
    weekly_review: ["/review/weekly"],
};

function notificationCategory(value) {
    var category = typeof value === "string" ? value.trim().toLowerCase() : "timer";
    if (category === "scheduled-reminder") category = "scheduled_reminder";
    if (category === "commitment-check") category = "commitment_check";
    if (category === "weekly-review") category = "weekly_review";
    return Object.prototype.hasOwnProperty.call(NOTIFICATION_CATEGORY_PATHS, category)
        ? category
        : "timer";
}

function pathMatches(path, prefixes) {
    return prefixes.some(function (prefix) {
        return path === prefix || path.startsWith(prefix + "/");
    });
}

function safeNotificationPath(path) {
    return path.indexOf("\\") === -1
        && !/%(?:2e|2f|5c)/i.test(path)
        && !path.split("/").some(function (part) { return part === "." || part === ".."; });
}

function defaultNotificationPath(category) {
    if (category === "weekly_review") return "/review/weekly/";
    if (category === "scheduled_reminder" || category === "commitment_check") {
        return "/notifications/";
    }
    return "/timers/";
}

function safeNotificationUrl(value, category, fallback) {
    var fallbackPath = fallback || defaultNotificationPath(category);
    try {
        if (typeof value === "string" && (!value.startsWith("/") || value.startsWith("//"))) {
            return new URL(fallbackPath, self.location.origin).href;
        }
        var url = new URL(typeof value === "string" ? value : fallbackPath, self.location.origin);
        if (url.origin !== self.location.origin) return new URL(fallbackPath, self.location.origin).href;
        if (!safeNotificationPath(url.pathname)) return new URL(fallbackPath, self.location.origin).href;
        if (!pathMatches(url.pathname, NOTIFICATION_PATH_PREFIXES)) {
            return new URL(fallbackPath, self.location.origin).href;
        }
        if (!pathMatches(url.pathname, NOTIFICATION_CATEGORY_PATHS[category])) {
            return new URL(fallbackPath, self.location.origin).href;
        }
        return url.pathname + url.search + url.hash;
    } catch (error) {
        return new URL(fallbackPath, self.location.origin).href;
    }
}

function safeActionUrl(value, category) {
    if (typeof value !== "string" || !value) return null;
    try {
        if (!value.startsWith("/") || value.startsWith("//")) return null;
        var url = new URL(value, self.location.origin);
        if (url.origin !== self.location.origin) return null;
        if (!safeNotificationPath(url.pathname)) return null;
        if (!pathMatches(url.pathname, NOTIFICATION_PATH_PREFIXES)) return null;
        if (!pathMatches(url.pathname, NOTIFICATION_CATEGORY_PATHS[category])) return null;
        return url.pathname + url.search + url.hash;
    } catch (error) {
        return null;
    }
}

function safeNotificationIdentity(payload) {
    var identity = payload.identity || payload.reminder_id || payload.schedule_id
        || payload.commitment_id || payload.session_id || "general";
    return String(identity).replace(/[^A-Za-z0-9_.:+-]/g, "-").slice(0, 96) || "general";
}

function safeNotificationTag(value, category, identity) {
    var supplied = typeof value === "string" && value;
    var tag = supplied ? value : "autumn-" + category + "-" + identity;
    tag = tag.replace(/[^A-Za-z0-9_.:+-]/g, "-").slice(0, 100) || identity;
    if (!supplied) return tag;
    /* Prefix the category even when a producer supplied a tag so a scheduled
       reminder can never replace a commitment or review notification. */
    return category + "-" + tag;
}

function notificationActions(payloadActions, category) {
    if (!Array.isArray(payloadActions)) return [];
    return payloadActions.slice(0, 2).reduce(function (actions, item, index) {
        if (!item || typeof item !== "object") return actions;
        var title = typeof item.title === "string" ? item.title : item.label;
        var url = safeActionUrl(item.url, category);
        if (!title || !url) return actions;
        var action = typeof item.action === "string" && item.action
            ? item.action
            : "action-" + (index + 1);
        if (actions.some(function (existing) { return existing.action === action; })) return actions;
        actions.push({ action: action, title: title.slice(0, 64), url: url });
        return actions;
    }, []);
}

self.addEventListener("push", function (event) {
    var payload = {};
    try {
        payload = event.data ? event.data.json() : {};
    } catch (error) {
        try { payload = { body: event.data ? event.data.text() : "" }; } catch (ignored) { payload = {}; }
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) payload = {};
    var category = notificationCategory(payload.kind || payload.event_type);
    var identity = safeNotificationIdentity(payload);
    var actions = notificationActions(payload.actions, category);
    var tag = safeNotificationTag(payload.tag, category, identity);
    var title = typeof payload.title === "string" && payload.title ? payload.title : "Autumn";
    var body = typeof payload.body === "string" && payload.body
        ? payload.body
        : "Your timer needs your attention.";
    var options = {
        body: body,
        tag: tag,
        /* Repeat-interval reminders share a tag; renotify makes a later
           occurrence visible without collapsing unrelated categories. */
        renotify: true,
        icon: "/static/core/images/icons/autumn-icon-192.png",
        badge: "/static/core/images/icons/autumn-icon-192.png",
        data: {
            url: safeNotificationUrl(payload.url, category),
            kind: category,
            identity: identity,
            actions: actions,
        },
    };
    if (actions.length) {
        options.actions = actions.map(function (item) {
            return { action: item.action, title: item.title };
        });
    }
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    var data = event.notification.data || {};
    var category = notificationCategory(data.kind);
    var target = data.url;
    if (event.action && Array.isArray(data.actions)) {
        var selected = data.actions.find(function (item) {
            return item && item.action === event.action;
        });
        if (selected) target = selected.url;
    }
    target = new URL(safeNotificationUrl(target, category), self.location.origin).href;
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

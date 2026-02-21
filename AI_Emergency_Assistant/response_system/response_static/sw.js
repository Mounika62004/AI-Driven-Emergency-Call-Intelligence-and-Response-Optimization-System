/* ─── sw.js — Service Worker ─────────────────────────────────────────────────
   Must be served from the root path so its scope covers the whole response app.
   Route: GET /sw.js  → served by response_app.py
──────────────────────────────────────────────────────────────────────────────*/

const CACHE_NAME = 'response-center-v1';

// ─── Install / Activate ───────────────────────────────────────────────────────
self.addEventListener('install',  () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));


// ─── Push event ───────────────────────────────────────────────────────────────
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { title: '🚨 Emergency Alert', body: event.data?.text() || '' };
    }

    const priorityColors = { 1: '🔴', 2: '🟠', 3: '🟡', 4: '🟢' };
    const dot   = priorityColors[data.priority] || '🔴';
    const title  = data.title  || `${dot} Emergency Alert`;
    const body   = data.body   || 'New emergency alert received. Tap to view details.';

    const options = {
        body:             body,
        icon:             '/response_static/icons/icon-192.png',
        badge:            '/response_static/icons/badge-72.png',
        vibrate:          [300, 100, 300, 100, 300, 100, 600],  // SOS pattern
        requireInteraction: true,        // keeps notification on screen until user taps
        tag:              'emergency-alert',
        renotify:         true,          // re-alert even if same tag
        timestamp:        Date.now(),
        data:             data,
        actions: [
            { action: 'view',    title: '👁 View Details' },
            { action: 'dismiss', title: '✖ Dismiss'       }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});


// ─── Notification click ───────────────────────────────────────────────────────
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'dismiss') return;

    const payload = event.notification.data || {};

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            // If the response app is already open, focus it and pass the payload
            for (const client of clientList) {
                if (client.url.includes(':5020') && 'focus' in client) {
                    client.focus();
                    client.postMessage({ type: 'ALERT_CLICKED', payload });
                    return;
                }
            }
            // Otherwise, open the response app
            return clients.openWindow('http://localhost:5020').then((newClient) => {
                if (newClient) {
                    // Small delay so the page can load before receiving the message
                    setTimeout(() => {
                        newClient.postMessage({ type: 'ALERT_CLICKED', payload });
                    }, 2000);
                }
            });
        })
    );
});


// ─── Background sync (optional future use) ───────────────────────────────────
self.addEventListener('sync', (event) => {
    if (event.tag === 'check-alerts') {
        event.waitUntil(
            fetch('/alerts').then(r => r.json()).catch(() => [])
        );
    }
});
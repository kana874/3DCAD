// SPDX-License-Identifier: LGPL-2.1-or-later
// GitHub Pages cross-origin isolation shim, no binary/body caching.
// Pages cannot set COOP/COEP response headers. Add them only to same-origin
// navigations and Web Workers; leave large WASM payloads byte-for-byte intact.
// This service worker is scoped to /3DCAD/ by its registration URL.
'use strict';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.mode === 'only-if-cached' && req.cache !== 'only-if-cached') return;
  if (req.mode !== 'navigate' && req.destination !== 'worker' &&
      req.destination !== 'sharedworker') return;

  event.respondWith((async () => {
    const response = await fetch(req);
    if (!response.ok || response.type === 'opaque') return response;
    const headers = new Headers(response.headers);
    headers.set('Cross-Origin-Opener-Policy', 'same-origin');
    headers.set('Cross-Origin-Embedder-Policy', 'require-corp');
    headers.set('Cross-Origin-Resource-Policy', 'same-origin');
    return new Response(response.body, {
      status: response.status, statusText: response.statusText, headers
    });
  })());
});
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'unregister') {
    event.waitUntil(self.registration.unregister());
  }
});

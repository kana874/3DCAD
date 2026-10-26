// SPDX-License-Identifier: LGPL-2.1-or-later
// GitHub Pages FreeCAD runtime: cross-origin isolation and streamed WASM fallback.
// GitHub Pages cannot set Content-Encoding on FreeCAD.wasm.gz; dynamically convert
// FreeCAD.wasm requests into a gzip-decoded stream with the required application/wasm
// MIME type. Do not cache enormous engine assets in this service worker.
'use strict';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

function sameOriginHeaders(headers) {
  const out = new Headers(headers);
  out.set('Cross-Origin-Opener-Policy', 'same-origin');
  out.set('Cross-Origin-Embedder-Policy', 'require-corp');
  out.set('Cross-Origin-Resource-Policy', 'same-origin');
  return out;
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Independently of Qt-loader changes, the generated Emscripten runtime may
  // fetch FreeCAD.wasm directly. That file does not exist on GitHub Pages:
  // the build only publishes the much smaller FreeCAD.wasm.gz.
  // Return the decompressed bytes as a streaming application/wasm Response.
  if (url.pathname.endsWith('/FreeCAD.wasm')) {
    event.respondWith((async () => {
      const gzUrl = new URL('./FreeCAD.wasm.gz' + url.search, url.href);
      const gz = await fetch(gzUrl, {cache: 'force-cache'});
      if (!gz.ok || !gz.body) {
        return new Response('FreeCAD wasm gzip fetch failed: HTTP ' + gz.status, {
          status: 502, headers: sameOriginHeaders({'Content-Type': 'text/plain'})
        });
      }
      const decompressor = new DecompressionStream('gzip');
      return new Response(gz.body.pipeThrough(decompressor), {
        status: 200,
        headers: sameOriginHeaders({
          'Content-Type': 'application/wasm',
          'Cache-Control': 'no-store'
        })
      });
    })());
    return;
  }

  // Keep large assets byte-for-byte; only navigations and workers need the
  // synthetic COOP/COEP response headers.
  if (request.mode === 'only-if-cached' && request.cache !== 'only-if-cached') return;
  if (request.mode !== 'navigate' && request.destination !== 'worker' &&
      request.destination !== 'sharedworker') return;
  event.respondWith((async () => {
    const response = await fetch(request);
    if (!response.ok || response.type === 'opaque') return response;
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: sameOriginHeaders(response.headers)
    });
  })());
});
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'unregister') {
    event.waitUntil(self.registration.unregister());
  }
});

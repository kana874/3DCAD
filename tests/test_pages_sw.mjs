// SPDX-License-Identifier: LGPL-2.1-or-later
// Test the Service Worker's actual fetch handler with a compressed WASM fixture.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { gzipSync } from 'node:zlib';

const callbacks = {};
const payload = new Uint8Array([0,97,115,109,1,0,0,0,42,43]);
const zipped = gzipSync(payload);
let fetchedUrl = '';
const origin = 'https://kana874.github.io';
const worker = {
  location: { origin },
  addEventListener: (type, cb) => { callbacks[type] = cb; },
  skipWaiting: () => Promise.resolve(),
  clients: { claim: () => Promise.resolve() }
};
const ctx = {
  self: worker, URL, Headers, Response, Request, DecompressionStream,
  fetch: async (request) => {
    fetchedUrl = String(request.url || request);
    return new Response(zipped, {
      status: 200,
      headers: { 'Content-Type': 'application/octet-stream' }
    });
  }
};
vm.runInNewContext(fs.readFileSync('pages/sw.js', 'utf8'), ctx, {filename: 'pages/sw.js'});
assert.equal(typeof callbacks.fetch, 'function');

let answer;
callbacks.fetch({
  request: new Request(origin+'/3DCAD/FreeCAD.wasm?v=1.0.8-ja1'),
  respondWith: (promise) => { answer = Promise.resolve(promise); }
});
assert.ok(answer, 'WASM request intercepted');
const result = await answer;
const decoded = new Uint8Array(await result.arrayBuffer());
assert.deepEqual(decoded, payload);
assert.equal(result.headers.get('Content-Type'), 'application/wasm');
assert.equal(result.headers.get('Cross-Origin-Embedder-Policy'), 'require-corp');
assert.equal(result.headers.get('Cross-Origin-Opener-Policy'), 'same-origin');
assert.equal(fetchedUrl, origin+'/3DCAD/FreeCAD.wasm.gz?v=1.0.8-ja1');

let missed = false;
callbacks.fetch({
  request: new Request('https://example.com/FreeCAD.wasm'),
  respondWith: () => { missed = true; }
});
assert.equal(missed, false, 'No rewriting cross-origin requests');
console.log('PASS: Service Worker serves gzip decompressed wasm + COOP/COEP');

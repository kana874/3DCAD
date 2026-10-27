// Execute the production entry scripts without a CAD engine to check ownership
// of the default/explicit/compatibility boot paths. No source-string matching.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const scripts = ['cad/workspace.js', 'fusion/fusion-mode.js', 'fusion/design-palette.js'];
function boot(file, search) {
  const calls = {fetch: [], timers: 0, dom: false};
  const scope = {
    URL, URLSearchParams, TextEncoder, TextDecoder,
    location: {search, href: 'https://example.test/3DCAD/' + search},
    console: {error() {}, info() {}, debug() {}, warn() {}, log() {}},
    fetch: url => {calls.fetch.push(String(url)); return Promise.resolve({ok: true, text: async () => ''});},
    setInterval: () => ++calls.timers, clearInterval() {}, setTimeout: () => 1,
    addEventListener() {}, matchMedia: () => ({matches: false}),
    document: {
      currentScript: {src: 'https://example.test/3DCAD/' + file},
      getElementById: () => null, querySelector: () => null,
      createElement() {calls.dom = true; throw new Error('DOM boundary');},
    },
  };
  scope.window = scope;
  try { vm.runInNewContext(fs.readFileSync('play-gui/' + file, 'utf8'), scope); }
  catch (error) { if (!calls.dom) throw error; }
  return calls;
}
for (const search of ['', '?workspace=fusion', '?workspace=classic', '?fusionMode=off']) {
  const results = scripts.map(file => boot(file, search));
  const native = results[0].fetch.some(url => url.endsWith('/cad/cad_workspace.py'));
  const oldBridge = results[1].fetch.length > 0;
  const oldPalette = results[2].dom || results[2].timers > 0 || results[2].fetch.length > 0;
  if (search === '' || search === '?workspace=fusion') {
    assert.equal(native, true, search || 'default');
    assert.equal(oldBridge, false);
    assert.equal(oldPalette, false);
  } else if (search === '?workspace=classic') {
    assert.equal(native, false);
    assert.equal(oldBridge, true);
    assert.equal(oldPalette, true);
  } else {
    assert.equal(native, false);
    assert.equal(oldPalette, false);
  }
}
console.log('PASS: native default/explicit boot, isolated compatibility and disabled modes');

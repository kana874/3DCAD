// SPDX-License-Identifier: LGPL-2.1-or-later
// GitHub Pages has no COOP/COEP headers; the service worker supplies them.
// Always check for updates, even in already-isolated tabs: otherwise an older
// cached worker can leave a missing FreeCAD.wasm request unhandled.
(() => {
  'use strict';
  if (!('serviceWorker' in navigator)) {
    console.error('[freecad-ja-pages] Service Worker unavailable');
    return;
  }
  const key = 'freecad-ja-pages-sw-v2-reloaded';
  let restarted = false;
  const restartOnce = () => {
    if (restarted || sessionStorage.getItem(key)) return;
    restarted = true;
    sessionStorage.setItem(key, '1');
    location.reload();
  };
  navigator.serviceWorker.addEventListener('controllerchange', restartOnce);
  navigator.serviceWorker.register('./sw.js', {
    scope: './', updateViaCache: 'none'
  }).then(async (reg) => {
    await reg.update();
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller || !self.crossOriginIsolated) {
      restartOnce();
    }
    console.info('[freecad-ja-pages] Worker ready:', reg.scope);
  }).catch((err) => {
    console.error('[freecad-ja-pages] Worker registration failed:', err);
  });
})();

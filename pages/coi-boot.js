// SPDX-License-Identifier: LGPL-2.1-or-later
// GitHub Pages has no COOP/COEP header API; the service worker enables it on reload.
(() => {
  'use strict';
  if (!('serviceWorker' in navigator)) {
    console.error('[freecad-ja-pages] Service Worker unavailable; COI cannot start');
    return;
  }
  if (self.crossOriginIsolated) return;
  const key = 'freecad-ja-pages-coi-reloads';
  const attempts = Number(sessionStorage.getItem(key) || '0');

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (self.crossOriginIsolated || Number(sessionStorage.getItem(key) || '0') > 1) return;
    sessionStorage.setItem(key, String(attempts + 1));
    location.reload();
  });
  navigator.serviceWorker.register('./sw.js', {scope:'./'}).then(async (reg) => {
    await navigator.serviceWorker.ready;
    if (navigator.serviceWorker.controller && !self.crossOriginIsolated && attempts < 2) {
      sessionStorage.setItem(key, String(attempts + 1));
      location.reload();
    }
    console.info('[freecad-ja-pages] COI service worker ready:', reg.scope);
  }).catch((err) => {
    console.error('[freecad-ja-pages] COI SW registration failed', err);
  });
})();

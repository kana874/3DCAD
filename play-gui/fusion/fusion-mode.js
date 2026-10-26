// SPDX-License-Identifier: LGPL-2.1-or-later
// Fusion-style FreeCAD UI bridge. Uses Qt/Python native commands; never remaps
// DOM pointer events, so Sketcher and the WASM Qt event loop stay untouched.
(() => {
  'use strict';
  if(new URLSearchParams(location.search).get('workspace') === 'fusion') return;
  const qs = new URLSearchParams(location.search);
  const enabled = qs.get('fusionMode') !== 'off';
  const mark = '/tmp/freecad-fusion-mode-status.txt';
  let attempts = 0;
  let started = false;
  const maxPolls = 240;
  let pyPromise = fetch('./fusion/fusion-mode.py', {cache: 'force-cache'}).then(r => {
    if (!r.ok) throw new Error('Fusion Python script HTTP ' + r.status);
    return r.text();
  }).catch(e => { console.error('[fusion-mode]', e); return null; });

  function status() {
    try {
      return new TextDecoder().decode(window.fcInstance.FS.readFile(mark));
    } catch (_) { return ''; }
  }

  // Only lightweight help overlay is DOM. Native CAD menus and shortcuts are
  // controlled by FreeCAD; web inputs never capture or synthesize mouse events.
  function help() {
    if (document.getElementById('fusion-mode-help')) return;
    const style = document.createElement('style');
    style.textContent = [
      '#fusion-mode-help{position:fixed;right:14px;bottom:36px;z-index:2147480000;',
      'font:12px/1.45 sans-serif;color:#192334;}',
      '#fusion-mode-help details{border:1px solid #c7cdd3;background:#fafafa;',
      'box-shadow:0 1px 4px #0002;border-radius:7px;max-width:260px;}',
      '#fusion-mode-help summary{padding:5px 11px;cursor:pointer;user-select:none;}',
      '#fusion-mode-help .fusion-content{padding:0 12px 10px;}',
      '#fusion-mode-help table{border-collapse:collapse;width:100%;}',
      '#fusion-mode-help td{padding:3px 4px;border-bottom:1px solid #ddd;}',
      '#fusion-mode-help a{color:#145bb2;}',
      '#fusion-mode-help code{font-size:12px;}'
    ].join('');
    document.head.appendChild(style);
    const root = document.createElement('aside');
    root.id = 'fusion-mode-help';
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = enabled ? 'Fusion操作ガイド' : 'FreeCAD標準操作';
    details.appendChild(summary);
    const content = document.createElement('div');
    content.className = 'fusion-content';
    const rows = [
      ['中ボタン＋ドラッグ', '平行移動（パン）'],
      ['Shift＋中ドラッグ', '視点回転'],
      ['ホイール回転', '拡大・縮小'],
      ['E / H / F', '押し出し / 穴 / フィレット'],
      ['L / R / C / D', '線 / 長方形 / 円 / 寸法']
    ];
    const table = document.createElement('table');
    for (const [a,b] of rows) {
      const tr = document.createElement('tr');
      for (const value of [a,b]) {
        const td = document.createElement('td'); td.textContent = value; tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    content.appendChild(table);
    const p = document.createElement('p');
    p.textContent = 'スケッチ用キーはスケッチ編集時のみ有効です。FusionのEはFreeCADではパッドに対応します。';
    content.appendChild(p);
    const link = document.createElement('a');
    const next = new URL(location.href);
    if (enabled) next.searchParams.set('fusionMode','off');
    else next.searchParams.delete('fusionMode');
    link.href = next.toString();
    link.textContent = enabled ? 'FreeCAD標準操作に戻す（再読み込み）' : 'Fusion操作に戻す（再読み込み）';
    link.addEventListener('click', ev => {
      if (!window.confirm('開いている設計データを保存しましたか？操作モードを切り替えるとページを再読み込みします。')) ev.preventDefault();
    });
    content.appendChild(link);
    details.appendChild(content); root.appendChild(details);
    document.body.appendChild(root);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', help, {once:true});
  } else help();

  const tick = setInterval(async () => {
    if (started || ++attempts > maxPolls) {
      clearInterval(tick);
      if (!started) console.warn('[fusion-mode] FreeCAD GUI unavailable');
      return;
    }
    if (!window.__fcWorkReady || !window.__fcAppReady ||
        !window.fcInstance?.FS || !window.__fcRunPyGuarded ||
        window.__fcPyBusy) return;
    // Run locale setup first to avoid a CPython JSPI reentrant call.
    const locale = window.fcInstance.FS;
    if (qs.get('fontMode') !== 'off') {
      try {
        const s = new TextDecoder().decode(locale.readFile('/tmp/freecad-web-ja-status.txt'));
        if (!s) return;
      } catch (_) {
        // If localization failed permanently, do not block useful CAD input.
        if (attempts < 150) return;
      }
    }
    started = true; clearInterval(tick);
    let source = await pyPromise;
    if (!source) return;
    source = source.replace('__FUSION_MODE__', enabled ? 'on' : 'off');
    // The same native guard used by Japanese localization/other Qt hooks.
    if (window.__fcPyBusy) return;
    try { window.__fcRunPyGuarded(source); }
    catch (e) { console.error('[fusion-mode] Python bridge failed', e); return; }
    let polls = 0;
    const verify = setInterval(() => {
      const result = status();
      if (result || ++polls > 50) {
        clearInterval(verify);
        if (result.startsWith('ok:')) console.info('[fusion-mode] ', result);
        else console.warn('[fusion-mode] activation not confirmed', result);
      }
    }, 400);
  }, 500);
})();

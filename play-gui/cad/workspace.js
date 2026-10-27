// SPDX-License-Identifier: LGPL-2.1-or-later
// Dedicated GUI is the default; the legacy shell is an explicit compatibility path.
(() => {
  'use strict';
  const query = new URLSearchParams(location.search);
  if (query.get('workspace') === 'classic' || query.get('fusionMode') === 'off') return;
  const base = new URL('./', document.currentScript.src);
  const files = ['cad_core.py', 'cad_selection.py', 'cad_profiles.py', 'cad_commands.py', 'cad_catalog.py', 'cad_workspace.py'];
  const directory = '/home/web_user/.cad-workspace';
  let started = false;
  const fontPrepared = () => {
    if (['off', 'static-register'].includes(query.get('fontMode'))) return true;
    try {
      return new TextDecoder().decode(window.fcInstance.FS.readFile('/tmp/freecad-web-ja-status.txt')).startsWith('ok:');
    } catch (_) { return false; }
  };
  const ready = () => window.__fcWorkReady && window.__fcAppReady &&
    window.fcInstance?.FS && window.__fcRunPyGuarded && !window.__fcPyBusy && fontPrepared();
  const sources = Promise.all(files.map(async name => {
    const response = await fetch(new URL(name, base), {cache: 'no-cache'});
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    return [name, await response.text()];
  }));
  // Catch the promise immediately even if the engine never becomes ready.
  sources.catch(error => { window.__cadFailed = String(error); showFailure(String(error)); });
  const timer = setInterval(async () => {
    if (started || !ready() || window.__cadFailed) return;
    started = true;
    try {
      const loaded = await sources;
      // Loading the files may have yielded while another guarded call started.
      // Retry without re-entering the Python interpreter.
      if (!ready()) { started = false; return; }
      clearInterval(timer);
      const fs = window.fcInstance.FS;
      fs.mkdirTree(directory);
      for (const [name, content] of loaded) fs.writeFile(`${directory}/${name}`, content);
      const source = `import sys, json\n` +
        `if ${JSON.stringify(directory)} not in sys.path: sys.path.insert(0, ${JSON.stringify(directory)})\n` +
        `try:\n import cad_workspace\n cad_workspace.install()\n _cad_status = {'ok': True, 'version': cad_workspace.VERSION}\n` +
        `except Exception as _cad_error:\n import traceback\n traceback.print_exc()\n _cad_status = {'ok': False, 'error': repr(_cad_error)}\n` +
        `with open('/tmp/cad-workspace-status.json','w') as _cad_file: json.dump(_cad_status, _cad_file)\n`;
      window.__fcRunPyGuarded(source);
      const check = setInterval(() => {
        let result;
        try { result = JSON.parse(new TextDecoder().decode(fs.readFile('/tmp/cad-workspace-status.json'))); }
        catch (_) { return; }
        clearInterval(check);
        if (result.ok) {
          window.__cadReady = result;
          console.info('[CAD workspace] ready', result.version);
        } else {
          window.__cadFailed = result.error;
          console.error('[CAD workspace]', result.error);
          showFailure(result.error);
        }
      }, 250);
      setTimeout(() => { if (!window.__cadReady && !window.__cadFailed) {
        clearInterval(check); window.__cadFailed = '専用UIの起動が完了しませんでした。'; showFailure(window.__cadFailed);
      } }, 60000);
    } catch (error) {
      window.__cadFailed = String(error);
      showFailure(String(error));
    }
  }, 500);
  function showFailure(message) {
    const notice = document.createElement('div');
    notice.setAttribute('role', 'alert');
    notice.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:3000000;background:#fff1e9;color:#7c2923;padding:12px';
    notice.textContent = `専用ワークスペースを起動できませんでした：${message} `;
    const link = document.createElement('a');
    const recovery = new URL(location.href); recovery.searchParams.set('workspace', 'classic');
    link.href = recovery.href; link.textContent = '互換モードを開く';
    notice.append(link); document.body.append(notice);
  }
})();

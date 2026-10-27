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
  function showLegacyFiles() {
    const fs=window.fcInstance.FS, dir='/home/web_user/.fcweb-autosave';
    const prior=document.getElementById('cad-legacy-files'); if (prior) prior.remove();
    const panel=document.createElement('div'); panel.id='cad-legacy-files';
    panel.style.cssText='position:fixed;z-index:2147483000;left:50%;top:12%;transform:translateX(-50%);background:#fff;color:#222;padding:20px;border:1px solid #888;border-radius:8px;box-shadow:0 4px 24px #0006;max-height:70vh;overflow:auto;font:15px sans-serif';
    const title=document.createElement('p'); title.textContent='以前のブラウザ保存データ'; panel.appendChild(title);
    let names=[]; try { names=fs.readdir(dir).filter(name=>name.toLowerCase().endsWith('.fcstd')); } catch (_) {}
    if (!names.length) { const text=document.createElement('p'); text.textContent='データはありません。'; panel.appendChild(text); }
    for (const name of names) {
      const row=document.createElement('p');
      const download=document.createElement('button'); download.textContent=name+' を保存';
      download.onclick=() => {
        try {
          const url=URL.createObjectURL(new Blob([fs.readFile(dir+'/'+name)],{type:'application/octet-stream'}));
          const link=document.createElement('a'); link.href=url; link.download=name; document.body.appendChild(link); link.click(); link.remove();
          setTimeout(() => URL.revokeObjectURL(url),60000);
        } catch (error) { window.fcwebNotify?.('データを取り出せませんでした: '+error.message,'error'); }
      };
      const remove=document.createElement('button'); remove.textContent='削除'; remove.style.marginLeft='8px';
      remove.onclick=() => {
        if (!window.confirm(name+' をブラウザから削除しますか？')) return;
        try {
          fs.unlink(dir+'/'+name);
          fs.syncfs(false,error=>{
            if (error) window.fcwebNotify?.('削除結果を保存できませんでした: '+error,'error');
            else { row.remove(); window.fcwebNotify?.('ブラウザから削除しました。','info'); }
          });
        } catch (error) { window.fcwebNotify?.('削除できませんでした: '+error.message,'error'); }
      };
      row.append(download,remove); panel.appendChild(row);
    }
    const close=document.createElement('button'); close.textContent='閉じる'; close.onclick=()=>panel.remove(); panel.appendChild(close);
    document.body.appendChild(panel);
  }
  // Qt callbacks request a browser download through a transient MEMFS file.
  async function fileRequest(request) {
    if (request.operation === 'open') { window.fcwebOpen(); return; }
    if (request.operation === 'recover') { showLegacyFiles(); return; }
    const ext=request.operation === 'save' ? '.FCStd' : '.step';
    const filename=(request.label || 'design').replace(/[\\/:*?"<>|\x00-\x1f]/g,'_')+ext;
    let handle=null;
    if (window.showSaveFilePicker) {
      try { handle=await window.showSaveFilePicker({suggestedName:filename,types:[{description:request.operation === 'save' ? 'FreeCAD' : 'STEP',accept:{'application/octet-stream':[ext]}}]}); }
      catch (error) {
        if (error.name==='AbortError') return;
        if (error.name!=='SecurityError') throw error;
      }
    }
    const fs = window.fcInstance.FS;
    const tag = String(Date.now()) + '-' + String(Math.floor(Math.random() * 1000000));
    const out = '/tmp/cad-export-' + tag + ext, status = out + '.json';
    const payload = JSON.stringify({request, out, status});
    const code = request.operation === 'save' ? `import json, os\n_r=json.loads(${JSON.stringify(payload)})\ntry:\n import FreeCAD as _a\n _d=_a.getDocument(_r['request']['document'])\n if _d is None: raise RuntimeError('設計が閉じられました。')\n _d.recompute()\n _d.saveCopy(_r['out'])\n if not os.path.isfile(_r['out']) or os.path.getsize(_r['out'])==0: raise RuntimeError('FCStdが作成されませんでした。')\n _result={'ok':True}\nexcept Exception as _e:\n _result={'ok':False,'error':str(_e)}\nwith open(_r['status'],'w',encoding='utf-8') as _f: json.dump(_result,_f,ensure_ascii=False)\n` : `import json, os\n_r=json.loads(${JSON.stringify(payload)})\ntry:\n import FreeCAD as _a, Import, cad_core\n _d=_a.getDocument(_r['request']['document'])\n if _d is None: raise RuntimeError('設計が閉じられました。')\n _scope=_r['request']['scope']\n _c=[_d.getObject(n) for n in _r['request']['selected']] if _scope=='selected' else list(_d.Objects)\n _objects=[]\n for _o in _c:\n  if _o is None: continue\n  _b=cad_core.body_of(_o)\n  _target=_b if _b else _o\n  if _scope=='visible' and not _target.ViewObject.Visibility: continue\n  if not _target.isDerivedFrom('Part::Feature') or _target.Shape.isNull() or not _target.Shape.Solids: continue\n  if _target not in _objects: _objects.append(_target)\n if not _objects: raise RuntimeError('書き出せるボディがありません。')\n _d.recompute()\n Import.export(_objects,_r['out'])\n if not os.path.isfile(_r['out']) or os.path.getsize(_r['out'])==0: raise RuntimeError('STEPが作成されませんでした。')\n _result={'ok':True}\nexcept Exception as _e:\n _result={'ok':False,'error':str(_e)}\nwith open(_r['status'],'w',encoding='utf-8') as _f: json.dump(_result,_f,ensure_ascii=False)\n`;
    try {
      for (let i=0; window.__fcPyBusy; i++) {
        if (i > 600) throw new Error('CADの処理が終了しませんでした。');
        await new Promise(resolve => setTimeout(resolve,100));
      }
      window.__fcRunPyGuarded(code);
      let result;
      for (let i=0; i<1200; i++) {
        try { result=JSON.parse(new TextDecoder().decode(fs.readFile(status))); break; }
        catch (_) { await new Promise(resolve => setTimeout(resolve,100)); }
      }
      if (!result) throw new Error('STEP作成がタイムアウトしました。');
      if (!result.ok) throw new Error(result.error);
      const bytes=fs.readFile(out);
      if (handle) {
        const writable=await handle.createWritable(); await writable.write(bytes); await writable.close();
      } else {
        const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
        const link=document.createElement('a'); link.href=url; link.download=filename;
        document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url),60000);
      }
      window.fcwebNotify?.(handle ? 'ファイルを保存しました。' : 'ダウンロードを開始しました。','info');
    } catch (error) {
      window.fcwebNotify?.('ファイルを保存できませんでした: '+error.message,'error');
    } finally {
      for (const p of [out,status]) { try { fs.unlink(p); } catch (_) {} }
    }
  }
  setInterval(() => {
    if (!window.fcInstance?.FS) return;
    const fs=window.fcInstance.FS, path='/tmp/cad-file-request.json';
    try {
      const request=JSON.parse(new TextDecoder().decode(fs.readFile(path)));
      fs.unlink(path); fileRequest(request).catch(error => window.fcwebNotify?.('ファイル操作に失敗しました: '+error.message,'error'));
    } catch (_) {}
  },300);
  window.__cadSaveRequest = () => {
    if (window.__fcPyBusy || !window.__cadReady) {
      window.fcwebNotify?.('処理が終わってから保存してください。','warn'); return;
    }
    window.__fcRunPyGuarded("import cad_workspace; cad_workspace.WORKSPACE.safe(cad_workspace.WORKSPACE.request_file_operation,'save')");
  };
  window.addEventListener('beforeunload', event => {
    try {
      if (!window.fcInstance?.FS.analyzePath('/tmp/cad-open-documents').exists) return;
      event.preventDefault(); event.returnValue='';
    } catch (_) {}
  });
})();

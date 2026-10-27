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
    const fs=window.fcInstance.FS;
    const prior=document.getElementById('cad-legacy-files'); if (prior) prior.remove();
    const panel=document.createElement('div'); panel.id='cad-legacy-files';
    panel.style.cssText='position:fixed;z-index:2147483000;left:50%;top:12%;transform:translateX(-50%);background:#fff;color:#222;padding:20px;border:1px solid #888;border-radius:8px;box-shadow:0 4px 24px #0006;max-height:70vh;overflow:auto;font:15px sans-serif';
    const title=document.createElement('p'); title.textContent='以前のブラウザ保存データ'; panel.appendChild(title);
    const files=[], extensions=/\.(fcstd|step|stp|iges|igs|brep|brp|stl|obj|ply|3mf|ifc|dxf)$/i;
    function scan(dir, label, recurse) {
      let entries=[]; try { entries=fs.readdir(dir); } catch (_) { return; }
      for (const name of entries) {
        if (name==='.' || name==='..') continue;
        const path=dir+'/'+name; let stat;
        try { stat=fs.lstat(path); } catch (_) { continue; }
        if (recurse && fs.isDir(stat.mode)) scan(path,label+'/'+name,true);
        else if (fs.isFile(stat.mode) && extensions.test(name)) files.push({name,path,label:label+'/'+name});
      }
    }
    scan('/home/web_user/.fcweb-autosave','以前の自動保存',true);
    scan('/home/web_user/_up','以前開いたファイル',true);
    scan('/home/web_user/_dl','以前の保存ファイル',true);
    scan('/home/web_user','以前のホーム',false);
    if (!files.length) { const text=document.createElement('p'); text.textContent='データはありません。'; panel.appendChild(text); }
    for (const entry of files) {
      const row=document.createElement('p');
      row.dataset.legacyPath=entry.path;
      const download=document.createElement('button'); download.textContent=entry.label+' を保存';
      download.onclick=() => {
        try {
          const url=URL.createObjectURL(new Blob([fs.readFile(entry.path)],{type:'application/octet-stream'}));
          const link=document.createElement('a'); link.href=url; link.download=entry.name; document.body.appendChild(link); link.click(); link.remove();
          setTimeout(() => URL.revokeObjectURL(url),60000);
        } catch (error) { window.fcwebNotify?.('データを取り出せませんでした: '+error.message,'error'); }
      };
      const remove=document.createElement('button'); remove.textContent='削除'; remove.style.marginLeft='8px';
      remove.onclick=() => {
        if (!window.confirm(entry.label+' をブラウザから削除しますか？')) return;
        try {
          fs.unlink(entry.path);
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
  // Handles stay in memory only; a document token prevents a new document
  // with a reused name from overwriting a previously chosen file.
  const saveHandles=new Map();
  // Qt callbacks request a browser download through a transient MEMFS file.
  async function fileRequest(request) {
    if (request.operation === 'open') { window.fcwebOpen(); return; }
    if (request.operation === 'recover') { showLegacyFiles(); return; }
    const isSave=request.operation === 'save' || request.operation === 'save_as';
    const ext=isSave ? '.FCStd' : '.step';
    const filename=(request.label || 'design').replace(/[\\/:*?"<>|\x00-\x1f]/g,'_')+ext;
    let handle=isSave && request.operation==='save' && request.token ? saveHandles.get(request.token) || null : null;
    if (handle && handle.queryPermission) {
      try { if (await handle.queryPermission({mode:'readwrite'})!=='granted') handle=null; }
      catch (_) { handle=null; }
    }
    if (!handle && window.showSaveFilePicker) {
      try { handle=await window.showSaveFilePicker({suggestedName:filename,types:[{description:isSave ? 'FreeCAD' : 'STEP',accept:{'application/octet-stream':[ext]}}]}); }
      catch (error) {
        if (error.name==='AbortError') return;
        if (error.name!=='SecurityError') throw error;
      }
    }
    const fs = window.fcInstance.FS;
    const tag = String(Date.now()) + '-' + String(Math.floor(Math.random() * 1000000));
    const out = '/tmp/cad-export-' + tag + ext, status = out + '.json';
    const payload = JSON.stringify({request, out, status});
    const code = isSave ? `import json, os\n_r=json.loads(${JSON.stringify(payload)})\ntry:\n import FreeCAD as _a, cad_workspace as _w\n _d=_a.getDocument(_r['request']['document'])\n if _d is None or _w.WORKSPACE.file_token(_d)!=_r['request']['token']: raise RuntimeError('設計が閉じられました。')\n _d.recompute()\n _d.saveCopy(_r['out'])\n if not os.path.isfile(_r['out']) or os.path.getsize(_r['out'])==0: raise RuntimeError('FCStdが作成されませんでした。')\n _result={'ok':True}\nexcept Exception as _e:\n _result={'ok':False,'error':str(_e)}\nwith open(_r['status'],'w',encoding='utf-8') as _f: json.dump(_result,_f,ensure_ascii=False)\n` : `import json, os\n_r=json.loads(${JSON.stringify(payload)})\ntry:\n import FreeCAD as _a, Import, cad_core, cad_workspace as _w\n _d=_a.getDocument(_r['request']['document'])\n if _d is None or _w.WORKSPACE.file_token(_d)!=_r['request']['token']: raise RuntimeError('設計が閉じられました。')\n _scope=_r['request']['scope']\n _c=[_d.getObject(n) for n in _r['request']['selected']] if _scope=='selected' else list(_d.Objects)\n _objects=[]\n for _o in _c:\n  if _o is None: continue\n  _b=cad_core.body_of(_o)\n  _target=_b if _b else _o\n  if _scope=='visible' and not _target.ViewObject.Visibility: continue\n  if not _target.isDerivedFrom('Part::Feature') or _target.Shape.isNull() or not _target.Shape.Solids: continue\n  if _target not in _objects: _objects.append(_target)\n if not _objects: raise RuntimeError('書き出せるボディがありません。')\n _d.recompute()\n Import.export(_objects,_r['out'])\n if not os.path.isfile(_r['out']) or os.path.getsize(_r['out'])==0: raise RuntimeError('STEPが作成されませんでした。')\n _result={'ok':True}\nexcept Exception as _e:\n _result={'ok':False,'error':str(_e)}\nwith open(_r['status'],'w',encoding='utf-8') as _f: json.dump(_result,_f,ensure_ascii=False)\n`;
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
        if (isSave && request.token) saveHandles.set(request.token,handle);
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
  window.__cadSaveRequest = (saveAs=false) => {
    if (window.__fcPyBusy || !window.__cadReady) {
      window.fcwebNotify?.('処理が終わってから保存してください。','warn'); return;
    }
    const operation=saveAs ? 'save_as' : 'save';
    window.__fcRunPyGuarded("import cad_workspace; cad_workspace.WORKSPACE.safe(cad_workspace.WORKSPACE.request_file_operation,"+JSON.stringify(operation)+")");
  };
  window.addEventListener('beforeunload', event => {
    try {
      if (!window.fcInstance?.FS.analyzePath('/tmp/cad-open-documents').exists) return;
      event.preventDefault(); event.returnValue='';
    } catch (_) {}
  });
})();

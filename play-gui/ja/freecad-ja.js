// SPDX-License-Identifier: LGPL-2.1-or-later
// kana874/3DCAD: browser-only Japanese font + FreeCAD language preference.
// Do not call into CPython until the upstream window.__fcAppReady gate is true.
(() => {
  'use strict';

  document.documentElement.lang = 'ja';
  document.title = 'FreeCAD 日本語版 | ブラウザ3D CAD';

  // Only use CJK registration on explicit diagnostic requests. A prior
  // variable-font attempt reached QFontEngineFT::init and trapped with a
  // WebAssembly function signature mismatch on Edge 155. Unmodified URL is
  // deliberately stable while static fonts are validated.
  const query = new URLSearchParams(location.search);
  const requestedMode = query.get('fontMode');
  const mode = ['static', 'static-register'].includes(requestedMode)
    ? requestedMode
    : (query.get('experimentalFont') === '1' ? 'variable' : 'off');
  if (mode === 'off') {
    console.info('[freecad-web-ja] CJK font registration disabled (safe mode)');
    return;
  }
  const fontPath = mode.startsWith('static')
    ? '/usr/share/fonts/NotoSansJP-Static.ttf'
    : '/usr/share/fonts/NotoSansJP-VF.ttf';
  const applyFont = mode !== 'static-register';

  const python = [
    "import sys",
    "try:",
    " import FreeCAD as _jp_app",
    " import FreeCADGui as _jp_gui_api",
    " from PySide6 import QtGui as _jp_gui, QtWidgets as _jp_widgets",
    " _jp_path=" + JSON.stringify(fontPath),
    " _jp_font_id=_jp_gui.QFontDatabase.addApplicationFontFromData(open(_jp_path,'rb').read())",
    " if _jp_font_id < 0: raise RuntimeError('Noto Sans JP font registration failed')",
    " _jp_family=_jp_gui.QFontDatabase.applicationFontFamilies(_jp_font_id)[0]",
    " _jp_qapp=_jp_widgets.QApplication.instance()",
    " if _jp_qapp is not None and " + (applyFont ? 'True' : 'False') + ":",
    "  _jp_font=_jp_gui.QFont(_jp_family)",
    "  _jp_font.setPointSize(9)",
    "  _jp_qapp.setFont(_jp_font)",
    "  for _jp_top in _jp_qapp.topLevelWidgets(): _jp_top.update()",
    " _jp_app.ParamGet('User parameter:BaseApp/Preferences/General').SetString('Language','Japanese')",
    " _jp_gui_api.setLocale('Japanese')",
    " _jp_gui_api.updateLocale()",
    " _jp_locale=_jp_gui_api.getLocale()",
    " _jp_status='ok:'+_jp_family+';locale='+str(_jp_locale)",
    "except Exception as _jp_err:",
    " _jp_status='error:'+repr(_jp_err)",
    " sys.stderr.write('[freecad-web-ja] '+_jp_status+'\\n')",
    "try:",
    " open('/tmp/freecad-web-ja-status.txt','w',encoding='utf-8').write(_jp_status)",
    "except Exception: pass",
    ""
  ].join('\n');

  let attempts = 0;
  const maxAttempts = 180; // 90 seconds, no unbounded timer
  const timer = setInterval(() => {
    attempts += 1;
    if (attempts > maxAttempts) {
      clearInterval(timer);
      console.warn('[freecad-web-ja] FreeCAD Python was not ready within 90 seconds');
      return;
    }
    // Wait until the workbench has finished constructing its menus; doing a
    // Qt retranslate before this may leave actions with stale English labels.
    if (!window.__fcWorkReady || !window.__fcAppReady || !window.fcInstance ||
        !window.__fcRunPyGuarded || window.__fcPyBusy) return;
    clearInterval(timer);
    // FreeCADGui and the Qt GUI may still be initializing; retry if not applied.
    const m = window.fcInstance;
    const started = Date.now();
    const poll = setInterval(() => {
      let state = '';
      try {
        state = new TextDecoder().decode(m.FS.readFile('/tmp/freecad-web-ja-status.txt'));
      } catch (_) {}
      if (state.startsWith('ok:')) {
        clearInterval(poll);
        console.info('[freecad-web-ja] font mode=' + mode + '; translation activated', state);
      } else if (Date.now() - started > 10000) {
        clearInterval(poll);
        console.warn('[freecad-web-ja] Check the console and the font asset:', state);
      } else if (!window.__fcPyBusy) {
        window.__fcRunPyGuarded(python);
      }
    }, 500);
  }, 500);
})();

// SPDX-License-Identifier: LGPL-2.1-or-later
// kana874/3DCAD: browser-only Japanese font + FreeCAD language preference.
// Do not call into CPython until the upstream window.__fcAppReady gate is true.
(() => {
  'use strict';

  document.documentElement.lang = 'ja';
  document.title = 'FreeCAD 日本語版 | ブラウザ3D CAD';

  const python = [
    "import sys",
    "try:",
    " import FreeCAD as _jp_app",
    " from PySide6 import QtGui as _jp_gui, QtWidgets as _jp_widgets",
    " _jp_path='/usr/share/fonts/NotoSansJP-VF.ttf'",
    " _jp_font_id=_jp_gui.QFontDatabase.addApplicationFont(_jp_path)",
    " if _jp_font_id < 0: raise RuntimeError('Noto Sans JP font registration failed')",
    " _jp_family=_jp_gui.QFontDatabase.applicationFontFamilies(_jp_font_id)[0]",
    " _jp_qapp=_jp_widgets.QApplication.instance()",
    " if _jp_qapp is not None:",
    "  _jp_font=_jp_gui.QFont(_jp_family)",
    "  _jp_font.setPointSize(9)",
    "  _jp_qapp.setFont(_jp_font)",
    "  for _jp_top in _jp_qapp.topLevelWidgets(): _jp_top.update()",
    " _jp_app.ParamGet('User parameter:BaseApp/Preferences/General').SetString('Language','Japanese')",
    " _jp_status='ok:'+_jp_family",
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
    if (!window.__fcAppReady || !window.fcInstance ||
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
        console.info('[freecad-web-ja] Japanese font active', state);
      } else if (Date.now() - started > 10000) {
        clearInterval(poll);
        console.warn('[freecad-web-ja] Check the console and the font asset:', state);
      } else if (!window.__fcPyBusy) {
        window.__fcRunPyGuarded(python);
      }
    }, 500);
  }, 500);
})();

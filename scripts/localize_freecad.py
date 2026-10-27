#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Apply an idempotent Japanese-only frontend customization to freecad-web.

The binary FreeCAD engine is NOT modified. Qt font setup is applied after the
interpreter is ready by ja/freecad-ja.js. This is an integration candidate,
not a claim of successful in-browser rendering.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MARKER = '<!-- freecad-web-ja: source customization -->'
BOOT_SCRIPT = '<script src="/ja/freecad-ja.js" defer></script>'
FUSION_SCRIPT = '<script src="/fusion/fusion-mode.js" defer></script>'
DESIGN_SCRIPT = '<script src="/fusion/design-palette.js" defer></script>'
WORKSPACE_SCRIPT = '<script src="/cad/workspace.js" defer></script>'
FONT_JSON = '/ja/fonts.json'


def remove_fundraising(page: str) -> str:
    """Remove the prompt, its scheduler/storage, links, and invocation at build time.

    Run before the localization marker check so already customized snapshots
    receive this change too. Unknown upstream fundraising markup fails closed.
    """
    page = re.sub(r'<div\b[^>]*\bid="vtNudge"[\s\S]*?<script\b[^>]*\bid="vt-nudge"[\s\S]*?</script>', '', page)
    page = re.sub(r'[ \t]*<a\b[^>]*href="[^"]*(?:patreon|ko-fi|/go/kofi)[^"]*"[^>]*>[\s\S]*?</a>', '', page, flags=re.I)
    page = re.sub(r'^.*(?:\.vt-nudge|\.socials a\.support).*\n', '', page, flags=re.M)
    page = re.sub(r'^.*window\.vtNudge.*\n', '', page, flags=re.M)
    if re.search(r'vtNudge|vt-nudge|vt\.support\.nudge|patreon|ko-fi|/go/kofi|Enjoying FreeCAD in your browser', page, re.I):
        raise ValueError('Unrecognized upstream fundraising content remains')
    return page


def localize(page: str) -> str:
    page = remove_fundraising(page)
    # Stage opened and downloaded CAD files in MEMFS and do not install the
    # upstream CAD autosave/recovery observer. Keep the normal home mount for
    # application preferences and installed workbench resources.
    page = page.replace('     __cfg.fcwebSessionMode = true; // CAD_LOCAL_FILES\n', '')
    autosave = '    // Sequence on READINESS, not on fixed timers.'
    disabled = '    // CAD_LOCAL_FILES: browser CAD autosave and restore disabled.\n    if (false) '
    if autosave in page and disabled not in page:
        start = page.index(autosave)
        pos = page.index('    (function(){', start)
        page = page[:pos] + disabled + page[pos + 4:]
        page = page.replace("    document.addEventListener('visibilitychange', function(){ if(document.hidden) runPy(AUTOSAVE_FORCE); });\n", '', 1)
        page = page.replace("    window.addEventListener('pagehide', function(){ runPy(AUTOSAVE_FORCE); });\n", '', 1)
    # The old autosave loop also saved user preferences and serviced optional
    # sharing. Keep those independent of document autosave.
    if disabled in page:
        keep = '''    // CAD_LOCAL_SETTINGS_ONLY: preserve settings and optional sharing without CAD autosave.
    var CAD_PREFS = "import FreeCAD as _App\\ntry: _App.saveParameter()\\nexcept Exception: pass\\n";
    var CAD_SHARE = "try:\\n import fcweb_share as _fs; _fs.tick()\\nexcept Exception: pass\\n";
    var CAD_MESH = ["import FreeCAD as _App", "if not getattr(_App,'_cad_mesh_observer',None):", " class _CadMeshObserver:", "  def slotChangedObject(self,o,prop=None):", "   try:", "    mesh=getattr(o,'Mesh',None)", "    if prop in (None,'Mesh') and mesh is not None and mesh.CountFacets>50000 and o.ViewObject.SelectionStyle!='BoundBox': o.ViewObject.SelectionStyle='BoundBox'", "   except Exception: pass", " _App._cad_mesh_observer=_CadMeshObserver()", " _App.addDocumentObserver(_App._cad_mesh_observer)", "for _d in _App.listDocuments().values():", " for _o in _d.Objects: _App._cad_mesh_observer.slotChangedObject(_o)"].join("\\n");
    var CAD_MESH_READY = false;
    setInterval(function(){ if(window.__fcWorkReady && !window.__fcPyBusy && !CAD_MESH_READY) { CAD_MESH_READY=true; runPy(CAD_MESH); } }, 500);
    setInterval(function(){ if(window.__fcWorkReady) runPy(CAD_SHARE); }, 1500);
    function saveCADPreferences(){
      if (!window.__fcAppReady) { window.__cadPrefsPending=false; return; }
      if (window.__fcPyBusy) {
        if (!window.__cadPrefsPending) {
          window.__cadPrefsPending=true;
          setTimeout(function(){ window.__cadPrefsPending=false; saveCADPreferences(); }, 200);
        }
        return;
      }
      window.__cadPrefsPending=false; runPy(CAD_PREFS);
    }
    setInterval(saveCADPreferences, 120000);
    document.addEventListener('visibilitychange', function(){ if(document.hidden) saveCADPreferences(); });
    window.addEventListener('pagehide', saveCADPreferences);
'''
        marker = '    // CAD_LOCAL_SETTINGS_ONLY: preserve settings and optional sharing without CAD autosave.\n'
        if marker in page:
            page = re.sub(re.escape(marker) + r'[\s\S]*?(?=' + re.escape(disabled) + ')', lambda _: keep, page, count=1)
        else:
            page = page.replace(disabled, keep + disabled, 1)
    page = page.replace("dir='/home/web_user/_dl'", "dir='/tmp/_dl'")
    page = page.replace("var UP='/home/web_user/_up';", "var UP='/tmp/_up';")
    page = page.replace('"    d.saveAs(fp)",', '"    d.saveCopy(fp)",')
    page = re.sub(r'(?m)^[ \t]*try\{ window\.__fcWorkSaved && window\.__fcWorkSaved\(\); \}catch\(e\)\{\}[ \t]*$', '', page)
    page = page.replace("      try{ if(window.fcwebServerFiles){ window.fcwebServerFiles.onSave && window.fcwebServerFiles.onSave(dir+'/'+name, bytes); } }catch(e){}", '')
    page = page.replace("var text = 'Something went wrong (' + kind + '). Your work is autosaved and will be ' +\n               'restored if you reload. If it keeps happening, please send us the report.';", "var text = 'Something went wrong (' + kind + '). Unsaved work is not restored automatically. Save a local copy if possible.';")
    page = page.replace("'Your open work has been autosaved.'", "'Save your open work locally before reloading.'")
    page = page.replace("'(4 GB limit). Your work has been autosaved — reload to get it back.'", "'(4 GB limit). Unsaved work is not restored automatically.'")
    page = page.replace("text + ' Your work is autosaved.'", "text + ' Save your work locally before reloading.'")
    page = page.replace('      checkAutosaveHealth();\n', '')
    page = page.replace('        try { py(AUTOSAVE_FORCE); } catch (e) {}\n', '')
    page = page.replace("+ 'been saved. Save a copy with File", "+ 'not been saved automatically. Save a copy with File")
    page = page.replace("'has. Your work has been saved. Consider simplifying it or closing documents you '", "'has. Save a local copy and consider simplifying it or closing documents you '")
    page = page.replace("if((e.metaKey||e.ctrlKey)&&k==='s'){ e.preventDefault(); e.stopImmediatePropagation(); download(); }", "if((e.metaKey||e.ctrlKey)&&k==='s'){ e.preventDefault(); e.stopImmediatePropagation(); (window.__cadSaveRequest||download)(); }")
    # A rejected JSPI call is not proof that FreeCAD rolled back every mutation.
    page = page.replace('). Your document is unchanged — please report this.',
                        '). The document may have changed. Check the model before continuing; save a copy and report this error.')
    if MARKER in page:
        assert 'preload: ["/ja/fonts.json"]' in page, "Partial JA patch found"
        # Checked-in upstream snapshot predates the optional Fusion bridge;
        # Docker release build adds the script when starting from a clean HTML.
        if WORKSPACE_SCRIPT not in page:
            page = page.replace('</head>', WORKSPACE_SCRIPT + '\n</head>', 1)
        return page

    source_lang = '<!doctype html><html lang="en">'
    if page.count(source_lang) != 1:
        raise ValueError("Upstream <html lang> anchor changed")
    page = page.replace(source_lang, '<!doctype html><html lang="ja">', 1)

    title = '<title>FreeCAD in your browser - the full CAD app compiled to WebAssembly</title>'
    if page.count(title) != 1:
        raise ValueError("Upstream page title changed")
    page = page.replace(title, '<title>FreeCAD 日本語版 | ブラウザ3D CAD</title>', 1)

    head = '</head>'
    if page.count(head) != 1:
        raise ValueError("Upstream </head> anchor changed")
    page = page.replace(head, f'{MARKER}\n{BOOT_SCRIPT}\n{FUSION_SCRIPT}\n{DESIGN_SCRIPT}\n{WORKSPACE_SCRIPT}\n{head}', 1)

    qt = '       qt: {\n'
    if page.count(qt) != 1:
        raise ValueError("Upstream Qt boot config changed")
    page = page.replace(qt, '       qt: {\n         preload: ["/ja/fonts.json"],\n', 1)
    return page


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = args.file.read_text(encoding='utf-8')
    localized = localize(content)
    if args.check:
        assert content == localized, "Missing JA localization"
        print(f'PASS: {args.file} (Japanese frontend patch)')
        return
    args.file.write_text(localized, encoding='utf-8')
    manifest = args.file.with_name('manifest.webmanifest')
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data.update({
            'name': 'FreeCAD 日本語版',
            'short_name': 'FreeCAD 日本語',
            'description': 'ブラウザで動作する日本語版FreeCAD。'
        })
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Patched {args.file}')


if __name__ == '__main__':
    main()

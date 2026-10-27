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

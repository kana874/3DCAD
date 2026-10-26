#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Convert the nginx FreeCAD Web distribution into a GitHub Pages project site.

This modifies a *build output*, not the upstream source tree. Fails closed if
the pinned frontend's loader anchors change. Designed for /3DCAD/ hosting.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import sys

MARK = "freecad-ja-pages-v1"


def replace_one(text, old, new, what):
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{what}: expected exactly one anchor; found {count}")
    return text.replace(old, new, 1)


def gzip_file(path):
    target = Path(str(path) + ".gz")
    with path.open("rb") as src, target.open("wb") as dest:
        with gzip.GzipFile(fileobj=dest, filename="", mode="wb", compresslevel=6, mtime=0) as writer:
            shutil.copyfileobj(src, writer, length=1024 * 1024)
    path.unlink()
    return target


def validate_gzip(path):
    """Read through the footer/CRC; opening the first 4 KiB misses truncation."""
    size = 0
    with gzip.open(path, 'rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            size += len(chunk)
    if size == 0:
        raise ValueError(f'Empty gzip asset: {path}')
    return size


def site(site_dir, base, version):
    if not base.startswith("/") or not base.endswith("/") or "//" in base:
        raise ValueError("Base path must look like /3DCAD/")
    # Docker image already contains the correct patched Emscripten engine.
    ui = site_dir / "freecad-gui.html"
    if not ui.is_file():
        raise FileNotFoundError(ui)
    html = ui.read_text(encoding="utf-8")
    if "FreeCAD 日本語版" not in html:
        raise ValueError("Build the Japanese Docker image first")
    html = replace_one(html, '<link rel="canonical" href="https://freecad.virtastic.app/">',
                       f'<link rel="canonical" href="https://kana874.github.io{base}">', "canonical")
    html = html.replace('https://freecad.virtastic.app/', f'https://kana874.github.io{base}')
    html = replace_one(html, "navigator.serviceWorker.register('/sw.js')",
                       "navigator.serviceWorker.register('./sw.js')", "service-worker")
    # Only browser paths, not virtual Emscripten paths such as /home/web_user/.
    html = re.sub(r'(href|src)="/(?!/)', r'\1="./', html)
    # Use the fixed-weight Noto Sans JP TTF for ordinary visitors.
    # Opt out with ?fontMode=off; the variable-font test remains opt-in.
    # Match the mode precedence in play-gui/ja/freecad-ja.js exactly.
    html = replace_one(html, 'preload: ["/ja/fonts.json"]',
                       'preload: (new URLSearchParams(location.search).get("fontMode") === "off" ? [] : (["static", "static-register"].includes(new URLSearchParams(location.search).get("fontMode")) ? ["ja/fonts-static.json"] : (new URLSearchParams(location.search).get("experimentalFont") === "1" ? ["ja/fonts.json"] : ["ja/fonts-static.json"])))', "Qt preload")
    # The pinned production Docker image stamps ?v=<content-hash> while our
    # unit fixture does not. Match both forms, never the comment text.
    html, n_wasm = re.subn(
        r"const WASM_URL = 'FreeCAD\.wasm(?:\?v=[A-Za-z0-9]+)?';",
        f"const WASM_URL = 'FreeCAD.wasm.gz?v={version}';", html)
    html, n_data = re.subn(
        r"const DATA_URL = 'FreeCAD\.data\.gz\?v=[A-Za-z0-9]+';",
        f"const DATA_URL = 'FreeCAD.data.gz?v={version}';", html)
    if n_wasm != 1 or n_data != 1:
        raise ValueError(f"Staged engine asset anchors: wasm={n_wasm}, data={n_data}")

    helper = """// GitHub Pages does not support Content-Encoding override. Decompress the
 // versioned .gz binary in the tab, then give Emscripten the raw bytes.
 async function __fcPagesUnGzip(raw, expected) {
   if (!raw) throw new Error('Missing ' + expected + ' gzip data');
   const u = new Uint8Array(raw, 0, Math.min(4, raw.byteLength));
   if (expected === 'wasm' && u.length >= 4 &&
       u[0] === 0 && u[1] === 97 && u[2] === 115 && u[3] === 109) return raw;
   if (u[0] !== 31 || u[1] !== 139)
     throw new Error('Invalid gzip response for ' + expected + '. Check GitHub Pages deployment.');
   if (!('DecompressionStream' in self))
     throw new Error('This browser does not support DecompressionStream(gzip). Update Edge.');
   const decoded = await new Response(
     new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))
   ).arrayBuffer();
   if (expected === 'wasm') {
     const v = new Uint8Array(decoded, 0, 4);
     if (v[0] !== 0 || v[1] !== 97 || v[2] !== 115 || v[3] !== 109)
       throw new Error('Invalid FreeCAD wasm magic after decompression');
   }
   return decoded;
 }
 """
    html = replace_one(html, " async function init(){", helper + "\n async function init(){", "engine loader")
    wasm_prefetch = """__fcWasmBytes = await __engineFetch(WASM_URL, 'wasm', (n,_t,cached) => {
         __wasmGot = n; if (!cached) __fromCache = false; __report(); });"""
    html = replace_one(html, wasm_prefetch,
                       wasm_prefetch.replace("= await __engineFetch(", "= await __fcPagesUnGzip(await __engineFetch(")
                       .replace("__report(); });", "__report(); }), 'wasm');"), "wasm decompress")
    data_prefetch = """__fcDataBytes = await __engineFetch(DATA_URL, 'data', (n,_t,cached) => {
         __dataGot = n; if (!cached) __fromCache = false; __report(); });"""
    html = replace_one(html, data_prefetch,
                       data_prefetch.replace("= await __engineFetch(", "= await __fcPagesUnGzip(await __engineFetch(")
                       .replace("__report(); });", "__report(); }), 'data');"), "data decompress")
    html = replace_one(html, "} catch(e){ append('engine prefetch failed: '+e,'err'); }",
                       "} catch(e){ append('engine prefetch failed: '+e,'err'); throw e; }",
                       "fail closed")
    # The generated FreeCAD.js does NOT read Module.wasmBinary: it always calls
    # findWasmBinary() to fetch FreeCAD.wasm again. Qt's documented qt.module
    # option injects instantiateWasm with a precompiled WebAssembly.Module.
    # That prevents a 404 for FreeCAD.wasm (we only publish FreeCAD.wasm.gz).
    # Independent A/B control for Qt's precompiled module path. In
    # 'stream' mode, Emscripten fetches /FreeCAD.wasm through our worker.
    html = replace_one(
        html, "const instance = window.fcInstance = await qtLoad(__cfg);",
        "if (new URLSearchParams(location.search).get('wasmMode') !== 'stream') {\n"
        "       __cfg.qt.module = WebAssembly.compile(__fcWasmBytes);\n"
        "     }\n"
        "     const instance = window.fcInstance = await qtLoad(__cfg);",
        "Qt WASM mode switch")

    # The existing app gate runs after body scripts; register COI worker early.
    insert = """<!-- freecad-ja-pages-v1: cross-origin isolation via same-origin SW -->
<script src="./coi-boot.js"></script>
"""
    html = replace_one(html, "<head>", "<head>\n" + insert, "head")
    html = replace_one(html, '<html lang="ja">', '<html lang="ja" data-platform="github-pages">', "platform")
    # The bundled web page's analytics, sharing, addons API and proxy are not
    # backed by GitHub Pages. The README documents these as unavailable.
    ui.write_text(html, encoding="utf-8")
    (site_dir / "index.html").write_text(html, encoding="utf-8")

    # VFS preloading references must be relative to the project site's base.
    for name in ("fonts.json", "fonts-static.json"):
        font_manifest = site_dir / "ja" / name
        fonts = json.loads(font_manifest.read_text(encoding="utf-8"))
        for entry in fonts:
            if entry["source"].startswith("/ja/"):
                entry["source"] = "ja/" + entry["source"][4:]
        font_manifest.write_text(json.dumps(fonts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = site_dir / "manifest.webmanifest"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["start_url"] = "./"
    data["scope"] = "./"
    for icon in data.get("icons", []):
        if icon.get("src", "").startswith("/"):
            icon["src"] = "." + icon["src"]
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Only Japanese UI translations are required; trim the site footprint.
    i18n = site_dir / "i18n"
    if (i18n / "index.json").exists():
        man = json.loads((i18n / "index.json").read_text(encoding="utf-8"))
        files = man.get("files", {})
        allowed = {n: length for n, length in files.items() if n.endswith("_ja.qm")}
        if not allowed:
            raise ValueError("No Japanese FreeCAD .qm translations in distribution")
        for item in i18n.iterdir():
            if item.name.endswith(".qm") and item.name not in allowed:
                item.unlink()
        man["files"] = allowed
        (i18n / "index.json").write_text(json.dumps(man, ensure_ascii=False, separators=(",", ":")))
        print(f"Japanese translations: {len(allowed)} files")

    # gh-pages has no server gzip Content-Encoding, send explicitly gz assets.
    wasm = site_dir / "FreeCAD.wasm"
    if not wasm.is_file():
        raise FileNotFoundError(wasm)
    wasm_gz = gzip_file(wasm)
    # Container serves precompressed FreeCAD.data.gz; reject a missing bundle.
    data_gz = site_dir / "FreeCAD.data.gz"
    if not data_gz.is_file():
        raw = site_dir / "FreeCAD.data"
        if not raw.is_file():
            raise FileNotFoundError("FreeCAD.data.gz or FreeCAD.data")
        data_gz = gzip_file(raw)
    (site_dir / "FreeCAD.data").unlink(missing_ok=True)
    validate_gzip(wasm_gz)
    validate_gzip(data_gz)
    # Pages artifact is strictly files and directories.
    for path in site_dir.rglob("*"):
        if path.is_symlink():
            path.unlink()
    (site_dir / ".nojekyll").touch()
    for entry in (site_dir / "FreeCAD.js", wasm_gz, data_gz, site_dir / "index.html"):
        if not entry.exists() or entry.stat().st_size == 0:
            raise RuntimeError(f"Missing or empty asset: {entry}")
    total = sum(p.stat().st_size for p in site_dir.rglob("*") if p.is_file())
    if total > 1024 ** 3:
        raise ValueError(f"GitHub Pages 1 GB max site exceeded: {total}")
    print(json.dumps({"site_bytes": total, "wasm_gz": wasm_gz.stat().st_size,
                      "data_gz": data_gz.stat().st_size, "base": base}, indent=2))
    (site_dir / "build-report.json").write_text(json.dumps({
        "version": version, "base": base, "site_bytes": total,
        "wasm_gz_bytes": wasm_gz.stat().st_size,
        "data_gz_bytes": data_gz.stat().st_size, "page_patch": MARK}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("site", type=Path)
    parser.add_argument("--base", default="/3DCAD/")
    parser.add_argument("--version", default="1.0.8-ja1")
    args = parser.parse_args()
    site(args.site, args.base, args.version)


if __name__ == "__main__":
    main()

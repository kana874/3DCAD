# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fixture-based Pages build tests; do not need the 400MB Docker image."""
import importlib.util
import json
from pathlib import Path
import tempfile
import gzip
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_pages", ROOT/"scripts"/"build_pages.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

HTML = """<!doctype html><html lang="ja"><head>
<link rel="canonical" href="https://freecad.virtastic.app/">
<link rel="manifest" href="/manifest.webmanifest">
<a href="/legal.html">license</a>
<title>FreeCAD 日本語版</title>
<script>
navigator.serviceWorker.register('/sw.js')
const WASM_URL = 'FreeCAD.wasm';
const DATA_URL = 'FreeCAD.data.gz?v=1';
__fcWasmBytes = await __engineFetch(WASM_URL, 'wasm', (n,_t,cached) => {
         __wasmGot = n; if (!cached) __fromCache = false; __report(); });
__fcDataBytes = await __engineFetch(DATA_URL, 'data', (n,_t,cached) => {
         __dataGot = n; if (!cached) __fromCache = false; __report(); });
} catch(e){ append('engine prefetch failed: '+e,'err'); }
const __cfg = { qt: {
         preload: ["/ja/fonts.json"],
}};
 async function init(){
const instance = window.fcInstance = await qtLoad(__cfg);
</script></head></html>
"""

class PagesBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        (self.site/"ja").mkdir()
        (self.site/"i18n").mkdir()
        (self.site/"freecad-gui.html").write_text(HTML,encoding="utf-8")
        (self.site/"FreeCAD.js").write_text("//FreeCAD mock",encoding="utf-8")
        (self.site/"FreeCAD.wasm").write_bytes(b'\x00asm'+b'abc'*64)
        with gzip.open(self.site/"FreeCAD.data.gz","wb") as w:
            w.write(b'DATA'*200)
        (self.site/"ja/fonts.json").write_text(json.dumps([
            {"source":"/ja/NotoSansJP-VF.ttf","destination":"/usr/share/fonts/NotoSansJP-VF.ttf"}
        ]))
        (self.site/"ja/NotoSansJP-VF.ttf").write_bytes(b'MOCK FONT')
        (self.site/"manifest.webmanifest").write_text(json.dumps({
            "start_url":"/","scope":"/","icons":[{"src":"/icon-192.png"}]}))
        (self.site/"i18n/index.json").write_text(json.dumps({
            "version":"1.0.8","files":{"FreeCAD_ja.qm":3,"FreeCAD_en.qm":2}}))
        (self.site/"i18n/FreeCAD_ja.qm").write_bytes(b'aaa')
        (self.site/"i18n/FreeCAD_en.qm").write_bytes(b'bb')

    def test_output(self):
        mod.site(self.site,"/3DCAD/","test")
        text=(self.site/"index.html").read_text()
        self.assertIn("coi-boot.js",text)
        self.assertIn("FreeCAD.wasm.gz?v=test",text)
        self.assertIn("await __fcPagesUnGzip(await __engineFetch",text)
        self.assertIn("__cfg.qt.module = WebAssembly.compile(__fcWasmBytes);",text)
        self.assertIn("register('./sw.js')",text)
        self.assertIn('href="./manifest.webmanifest"',text)
        self.assertIn("https://kana874.github.io/3DCAD/",text)
        self.assertTrue((self.site/"FreeCAD.wasm.gz").exists())
        self.assertFalse((self.site/"FreeCAD.wasm").exists())
        with gzip.open(self.site/"FreeCAD.wasm.gz","rb") as g:
            self.assertEqual(g.read(4),b'\x00asm')
        files=json.loads((self.site/"i18n/index.json").read_text())["files"]
        self.assertEqual(list(files),["FreeCAD_ja.qm"])
        font=json.loads((self.site/"ja/fonts.json").read_text())[0]
        self.assertEqual(font["source"],"ja/NotoSansJP-VF.ttf")
        manifest=json.loads((self.site/"manifest.webmanifest").read_text())
        self.assertEqual(manifest["start_url"],"./")
        self.assertEqual(manifest["icons"][0]["src"],"./icon-192.png")

    def test_wrong_base_fails(self):
        with self.assertRaises(ValueError):
            mod.site(self.site, "3DCAD", "test")

    def test_upstream_anchor_mismatch_fails(self):
        (self.site/"freecad-gui.html").write_text(HTML.replace("const WASM_URL = 'FreeCAD.wasm';",""))
        with self.assertRaises(ValueError):
            mod.site(self.site,"/3DCAD/","test")

if __name__=="__main__":
    unittest.main()

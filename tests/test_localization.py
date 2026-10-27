# SPDX-License-Identifier: LGPL-2.1-or-later
import importlib.util
import pathlib
import unittest

source = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "localize_freecad.py"
spec = importlib.util.spec_from_file_location("localize_freecad", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

BASE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<title>FreeCAD in your browser - the full CAD app compiled to WebAssembly</title>'
        '</head><body><script> const cfg = {\n       qt: {\n         onLoaded:()=>{}'
        '};</script></body></html>')

class JapaneseLocalizationTests(unittest.TestCase):
    def test_idempotent(self):
        result = module.localize(BASE)
        self.assertEqual(result, module.localize(result))
        self.assertIn('html lang="ja"', result)
        self.assertIn('preload: ["/ja/fonts.json"]', result)
        self.assertIn('/ja/freecad-ja.js', result)
        self.assertIn('/fusion/fusion-mode.js', result)
        self.assertIn('/fusion/design-palette.js', result)

    def test_upstream_change_fails_loudly(self):
        with self.assertRaises(ValueError):
            module.localize('<html>unexpected</html>')

    def test_runtime_files_exist(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertTrue((root/"play-gui/ja/fonts.json").is_file())
        self.assertTrue((root/"play-gui/ja/freecad-ja.js").is_file())

    def test_fundraising_removed_on_fresh_and_already_localized_pages(self):
        prompt = '''<div id="vtNudge" class="vt-nudge" hidden>
          <p>Enjoying FreeCAD in your browser?</p><div class="row">
          <a href="https://ko-fi.com/virtastic">Give once</a></div></div>
          <script id="vt-nudge">window.vtNudge=function(){};
          setInterval(function(){localStorage.setItem('vt.support.nudge','1')},30000);
          </script>'''
        extras = '''<style>
 .vt-nudge{display:block}
 .topbar .socials a.support{color:gold}
 .model{display:block}
</style><a href="https://www.patreon.com/virtastic">Support</a>
<a href="/legal.html">Licenses</a><script>
 if (rc === 0 && window.vtNudge) { window.vtNudge('solve'); }
</script>'''
        for base in (BASE, module.localize(BASE)):
            result = module.localize(base.replace('</body>', prompt + extras + '</body>'))
            self.assertNotRegex(result, r'vtNudge|vt-nudge|patreon|ko-fi|vt.support.nudge')
            self.assertIn('.model{display:block}', result)
            self.assertIn('<a href="/legal.html">Licenses</a>', result)
            self.assertEqual(result, module.localize(result))

    def test_unknown_fundraising_markup_blocks_release(self):
        with self.assertRaisesRegex(ValueError, 'fundraising'):
            module.localize(BASE.replace('</body>', '<button>Support on Patreon</button></body>'))

if __name__ == "__main__":
    unittest.main()

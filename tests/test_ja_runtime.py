# SPDX-License-Identifier: LGPL-2.1-or-later
"""Guard against regressions in the Japanese UI locale activation path."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "play-gui" / "ja" / "freecad-ja.js").read_text(encoding="utf-8")

class JapaneseLocaleActivation(unittest.TestCase):
    def test_language_is_activated_not_just_saved(self):
        self.assertIn('import FreeCADGui as _jp_gui_api', JS)
        self.assertIn("SetString('Language','Japanese')", JS)
        self.assertIn("_jp_gui_api.setLocale('Japanese')", JS)
        self.assertIn("_jp_gui_api.updateLocale()", JS)
        self.assertIn("_jp_gui_api.getLocale()", JS)
        self.assertLess(JS.index("_jp_gui_api.setLocale('Japanese')"), JS.index("_jp_gui_api.updateLocale()"))
    def test_waits_for_workbench(self):
        self.assertIn('window.__fcWorkReady',JS)
        self.assertIn('window.__fcPyBusy',JS)
        self.assertIn('QFontDatabase.addApplicationFontFromData',JS)
    def test_safe_mode_kept(self):
        self.assertIn("mode === 'off'",JS)
        self.assertIn("fontMode",JS)

if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mocked tests for Fusion input mapping; no FreeCAD binary required."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

SOURCE = (Path(__file__).parents[1] / 'play-gui/fusion/fusion-mode.py').read_text()

class Params:
    def __init__(self): self.strings={}; self.bools={}
    def GetString(self,k,default=''): return self.strings.get(k,default)
    def SetString(self,k,v): self.strings[k]=v
    def GetStrings(self): return list(self.strings)
    def GetBool(self,k,default=False): return self.bools.get(k,default)
    def SetBool(self,k,v): self.bools[k]=v
    def GetBools(self): return list(self.bools)
    def RemGroup(self,k): pass

class FakeCommand:
    def __init__(self,shortcut=''): self.shortcut=shortcut
    def setShortcut(self,key): self.shortcut=key
    def resetShortcut(self): self.shortcut=''

class Stub:
    def __init__(self):
        self.groups={}
        self.view=types.SimpleNamespace(style=None,setNavigationType=lambda s:setattr(self.view,'style',s))
        self.commands={s:FakeCommand() for s in ('Sketcher_CreateLine','Sketcher_CreateRectangle',
        'Sketcher_CreateCircle','Sketcher_Dimension','Sketcher_ToggleConstruction',
        'Sketcher_Trimming','Sketcher_Offset','Sketcher_Projection','PartDesign_Pad',
        'PartDesign_Hole','PartDesign_Fillet','Std_TransformManip','Std_Measure')}
        self.commands['Sketcher_ConstrainCoincident']=FakeCommand('C')
        cmd=types.SimpleNamespace(get=lambda name:self.commands.get(name),
             listByShortcut=lambda k:[n for n,c in self.commands.items() if c.shortcut==k])
        self.app=types.ModuleType('FreeCAD')
        self.app.ParamGet=lambda k:self.groups.setdefault(k,Params())
        self.app.listDocuments=lambda:['Sample']
        self.gui=types.ModuleType('FreeCADGui')
        self.gui.Command=cmd
        self.gui.getDocument=lambda name:types.SimpleNamespace(mdiViewsOfType=lambda typ:[self.view])
        self.app.ParamGet("User parameter:BaseApp/Preferences/View").SetString('NavigationStyle','Gui::CADNavigationStyle')

    def run(self,mode):
        with patch.dict(sys.modules, {'FreeCAD':self.app,'FreeCADGui':self.gui}):
            ns={'__name__':'fusionmode_test'}
            with patch('builtins.open',create=True) as opener:
                # Return a mock writer for the status marker only
                from unittest.mock import mock_open
                opener.side_effect=mock_open()
                exec(compile(SOURCE.replace('_MODE = "__FUSION_MODE__"',f'_MODE = "{mode}"'),
                             'fusion-mode.py','exec'),ns)
            return ns['_fusion_status']

class FusionPresetTest(unittest.TestCase):
    def test_fusion_pan_orbit_zoom_and_shortcuts(self):
        s=Stub()
        result=s.run('on')
        self.assertTrue(result.startswith('ok:on'),result)
        view=s.app.ParamGet('User parameter:BaseApp/Preferences/View')
        self.assertEqual(view.GetString('NavigationStyle'),'Gui::RevitNavigationStyle')
        self.assertTrue(view.GetBool('ZoomAtCursor'))
        self.assertEqual(s.view.style,'Gui::RevitNavigationStyle')
        self.assertEqual(s.commands['PartDesign_Pad'].shortcut,'E')
        self.assertEqual(s.commands['Sketcher_CreateLine'].shortcut,'L')
        self.assertEqual(s.commands['Sketcher_CreateCircle'].shortcut,'C')
        self.assertEqual(s.commands['Sketcher_ConstrainCoincident'].shortcut,'')

    def test_restore_and_previous_user_shortcut(self):
        s=Stub()
        s.app.ParamGet('User parameter:BaseApp/Preferences/Shortcut').SetString('PartDesign_Pad','Shift+E')
        s.run('on')
        result=s.run('off')
        self.assertTrue(result.startswith('ok:off'),result)
        self.assertEqual(s.app.ParamGet('User parameter:BaseApp/Preferences/View').GetString('NavigationStyle'),'Gui::CADNavigationStyle')
        self.assertEqual(s.commands['PartDesign_Pad'].shortcut,'Shift+E')

    def test_browser_js_checks_full_gui_and_preserves_qt(self):
        js=(Path(__file__).parents[1]/'play-gui/fusion/fusion-mode.js').read_text()
        self.assertIn('window.__fcWorkReady',js)
        self.assertIn('window.__fcPyBusy',js)
        self.assertIn("get('fusionMode') !== 'off'",js)
        self.assertIn("source.replace('__FUSION_MODE__'",js)
        self.assertNotIn('dispatchEvent(new MouseEvent(',js)

if __name__=='__main__':
    unittest.main()

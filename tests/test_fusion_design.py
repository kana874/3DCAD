# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mocked native command dispatch and state-gating tests; no FreeCAD binary."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import mock_open, patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'play-gui/fusion/design-commands.py').read_text(encoding='utf-8')

class FreeCADMocks:
    def __init__(self, has_document=True, editing=False, selected=0):
        self.actions=[]
        self.editor=editing
        self.selected=selected
        self.app=types.ModuleType('FreeCAD')
        self.gui=types.ModuleType('FreeCADGui')
        self.app.ActiveDocument=object() if has_document else None
        self.gui.activeDocument=lambda:types.SimpleNamespace(
            getInEdit=lambda: self.editor,
            resetEdit=lambda: self.actions.append('resetEdit'))
        self.gui.Selection=types.SimpleNamespace(
            getSelectionEx=lambda: [object() for _ in range(self.selected)])
        self.commands={
            'Std_New','PartDesign_Body','PartDesign_NewSketch',
            'Sketcher_CreateLine','Sketcher_CreateRectangle','Sketcher_CreateCircle',
            'Sketcher_Dimension','Sketcher_Trimming',
            'PartDesign_Pad','PartDesign_Pocket','PartDesign_Revolution',
            'PartDesign_Fillet','PartDesign_Chamfer','PartDesign_Hole'
        }
        self.gui.listCommands=lambda:list(self.commands)
        self.gui.Command=types.SimpleNamespace(get=lambda n:object() if n in self.commands else None)
        self.gui.runCommand=lambda n:self.actions.append(n)

    def run(self, action):
        code=SOURCE.replace('"__FUSION_DESIGN_REQUEST__"',json.dumps(action))
        code=code.replace('__FUSION_DESIGN_ID__','73')
        with patch.dict(sys.modules,{'FreeCAD':self.app,'FreeCADGui':self.gui}):
            with patch('builtins.open',mock_open()):
                space={'__name__':'__main__'}
                exec(compile(code,'design-commands.py','exec'),space)
                return space['_result']

class FusionDesignTests(unittest.TestCase):
    def test_no_document_disables_design_commands(self):
        f=FreeCADMocks(has_document=False)
        r=f.run('body')
        self.assertFalse(r['ok'])
        self.assertFalse(r['state']['document'])
        self.assertEqual(f.actions,[])
        self.assertTrue(f.run('new')['ok'])
        self.assertEqual(f.actions,['Std_New'])
    def test_sketch_prefers_partdesign_create(self):
        f=FreeCADMocks()
        r=f.run('sketch')
        self.assertTrue(r['ok'],r)
        self.assertEqual(f.actions,['PartDesign_NewSketch'])
    def test_sketch_tools_only_in_edit_mode(self):
        f=FreeCADMocks(editing=False)
        self.assertFalse(f.run('line')['ok'])
        f.editor=True
        self.assertTrue(f.run('line')['ok'])
        self.assertEqual(f.actions,['Sketcher_CreateLine'])
        self.assertTrue(f.run('leave_sketch')['ok'])
        self.assertIn('resetEdit',f.actions)
    def test_solid_selection_and_edit_guards(self):
        f=FreeCADMocks(selected=0)
        self.assertFalse(f.run('pad')['ok'])
        f.selected=1
        self.assertTrue(f.run('pad')['ok'])
        f.editor=True
        self.assertFalse(f.run('pocket')['ok'])
        self.assertEqual(f.actions,['PartDesign_Pad'])
    def test_unknown_action_fails_closed(self):
        f=FreeCADMocks()
        self.assertFalse(f.run("__import__('os').system('echo unsafe')")['ok'])
        self.assertFalse(f.run('magic')['ok'])
        self.assertEqual(f.actions,[])
    def test_source_is_published_and_no_mouse_synthesis(self):
        js=(ROOT/'play-gui/fusion/design-palette.js').read_text()
        self.assertIn('window.__fcRunPyGuarded',js)
        self.assertIn('window.__fcWorkReady',js)
        self.assertIn('designPalette',js)
        self.assertIn('fusionMode',js)
        self.assertNotIn('dispatchEvent(new MouseEvent(',js)
        self.assertIn('design-palette.css',js)

if __name__=='__main__':
    unittest.main()

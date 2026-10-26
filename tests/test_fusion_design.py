# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-less smoke tests: only declared FreeCAD commands and safer Body reuse."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import mock_open, patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'play-gui/fusion/design-commands.py').read_text(encoding='utf-8')

class Document:
    def __init__(self,bodies=None):
        self.bodies=bodies or []
        self.recomputes=0
        self.transactions=[]
    def findObjects(self,type_id):
        return self.bodies if type_id=='PartDesign::Body' else []
    def openTransaction(self,s):self.transactions.append(('open',s))
    def commitTransaction(self):self.transactions.append(('commit',None))
    def abortTransaction(self):self.transactions.append(('abort',None))
    def recompute(self):self.recomputes+=1

class Body:
    TypeId='PartDesign::Body'
    def __init__(self):
        self.Tip=None
        self.Group=[]
        self.InListRecursive=[]

class Fake:
    def __init__(self,doc=True,edit=False,selected=None):
        self.calls=[];self.edited=edit
        self.body=Body();self.document=Document([self.body]) if doc else None
        self.selected=selected or []
        self.app=types.ModuleType('FreeCAD')
        self.gui=types.ModuleType('FreeCADGui')
        self.app.ActiveDocument=self.document
        self.commands=set(('Std_New','PartDesign_Body','PartDesign_NewSketch','Sketcher_CreateLine',
           'Sketcher_CreateRectangle','Sketcher_CreateCircle','Sketcher_Dimension',
           'PartDesign_Pad','PartDesign_Pocket','PartDesign_Fillet'))
        self.gui.listCommands=lambda:list(self.commands)
        self.gui.Command=types.SimpleNamespace(get=lambda n: object() if n in self.commands else None)
        def run(name):
            self.calls.append(name)
            if name=='PartDesign_Body' and self.document:
                self.document.bodies.append(Body())
        self.gui.runCommand=run
        self.view=types.SimpleNamespace(getActiveObject=lambda k: self.body if self.document else None,
            setActiveObject=lambda k,b:self.calls.append(('activate',b)))
        self.gui.activeDocument=lambda:types.SimpleNamespace(getInEdit=lambda:None,
            activeView=lambda:self.view,resetEdit=lambda:self.calls.append('resetEdit'))
        self.gui.Selection=types.SimpleNamespace(getSelectionEx=lambda:self.selected,
            clearSelection=lambda:self.calls.append('clear'))
    def run(self,action,value=0):
        code=SOURCE.replace('"__FUSION_DESIGN_REQUEST__"',json.dumps(action))
        code=code.replace('__FUSION_DESIGN_ID__','11')
        code=code.replace('__FUSION_DESIGN_VALUE__',str(value))
        with patch.dict(sys.modules,{'FreeCAD':self.app,'FreeCADGui':self.gui}):
            with patch('builtins.open',mock_open()):
                ns={'__name__':'__main__'}
                exec(compile(code,'design-commands.py','exec'),ns)
                return ns['_result']

class FusionDesignTests(unittest.TestCase):
    def test_only_new_on_empty_project(self):
        f=Fake(doc=False)
        self.assertFalse(f.run('body')['ok'])
        self.assertTrue(f.run('new')['ok'])
        self.assertEqual(f.calls,['Std_New'])
    def test_existing_body_is_activated_without_creating_another(self):
        f=Fake()
        r=f.run('sketch')
        self.assertTrue(r['ok'],r)
        self.assertIn(('activate',f.body),f.calls)
        self.assertIn('PartDesign_NewSketch',f.calls)
        self.assertNotIn('PartDesign_Body',f.calls)
    def test_new_body_clears_selected_feature_before_creation(self):
        f=Fake(selected=[types.SimpleNamespace(Object=object(),SubElementNames=[])])
        r=f.run('body')
        self.assertTrue(r['ok'])
        self.assertLess(f.calls.index('clear'),f.calls.index('PartDesign_Body'))
    def test_sketch_rejects_ambiguous_bodies(self):
        f=Fake();f.document.bodies.append(Body())
        f.view.getActiveObject=lambda key:None
        r=f.run('sketch')
        self.assertFalse(r['ok'])
        self.assertIn('複数',r['message'])
        self.assertNotIn('PartDesign_NewSketch',f.calls)
    def test_pad_requires_selection(self):
        f=Fake()
        self.assertFalse(f.run('pad')['ok'])
        f.selected=[types.SimpleNamespace(Object=object(),SubElementNames=[])]
        self.assertTrue(f.run('pad')['ok'])
    def test_solid_numeric_requires_actual_pad(self):
        f=Fake()
        selected=types.SimpleNamespace(TypeId='PartDesign::Pad',Label='Pad001',Length=2.5)
        f.selected=[types.SimpleNamespace(Object=selected,SubElementNames=[])]
        r=f.run('length',12.5)
        self.assertTrue(r['ok'],r)
        self.assertEqual(selected.Length,12.5)
        self.assertEqual(f.document.recomputes,1)
        self.assertEqual(f.document.transactions[-1][0],'commit')
        self.assertFalse(f.run('length',-3)['ok'])
        self.assertEqual(selected.Length,12.5)
    def test_parametric_pad_exact_creates_feature_in_same_body(self):
        f=Fake()
        sketch=types.SimpleNamespace(TypeId='Sketcher::SketchObject')
        f.body.Group=[sketch]
        shape=types.SimpleNamespace(isNull=lambda:False,isValid=lambda:True,Solids=[object()])
        made=[]
        def create(typeid,label):
            feat=types.SimpleNamespace(Shape=shape,Profile=None,Length=0)
            made.append((typeid,feat))
            return feat
        f.body.newObject=create
        f.selected=[types.SimpleNamespace(Object=sketch,SubElementNames=[])]
        response=f.run('pad_exact',18.25)
        self.assertTrue(response['ok'],response)
        self.assertEqual(made[0][0],'PartDesign::Pad')
        self.assertIs(made[0][1].Profile,sketch)
        self.assertEqual(made[0][1].Length,18.25)
        self.assertEqual(f.document.transactions[-1][0],'commit')
    def test_failed_numeric_extrusion_rolls_back(self):
        f=Fake()
        sketch=types.SimpleNamespace(TypeId='Sketcher::SketchObject')
        f.body.Group=[sketch]
        bad_shape=types.SimpleNamespace(isNull=lambda:True,isValid=lambda:False,Solids=[])
        f.body.newObject=lambda typeid,label:types.SimpleNamespace(Shape=bad_shape,Profile=None,Length=0)
        f.selected=[types.SimpleNamespace(Object=sketch,SubElementNames=[])]
        res=f.run('pad_exact',12)
        self.assertFalse(res['ok'])
        self.assertEqual(f.document.transactions[-1][0],'abort')
    def test_rejects_unknown_code(self):
        f=Fake()
        self.assertFalse(f.run("__import__('os')")['ok'])
        self.assertEqual(f.calls,[])
    def test_js_ribbon_and_browser_optout(self):
        js=(ROOT/'play-gui/fusion/design-palette.js').read_text()
        css=(ROOT/'play-gui/fusion/design-palette.css').read_text()
        self.assertIn('fusion_gui',js)
        self.assertIn("get('fusionUI')==='classic'",js)
        self.assertIn('fd-dimensions',js)
        self.assertIn("['pad_exact','押し出し（mm）'",js)
        self.assertIn('pocket_exact',js)
        self.assertIn("send(state?.sketchEdit?'sketch_dimension':'length')",js)
        self.assertIn('fusion-integrated #screen',css)
        self.assertIn("if(tabs.dataset.built!=='yes')",js)
        self.assertIn("if(actions.dataset.group!==group)",js)
        self.assertNotIn('tabs.replaceChildren()',js)
        self.assertNotIn('dispatchEvent(new MouseEvent(',js)
if __name__=='__main__':
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Engine-independent policy checks; real modeling is tested by cad-workspace-e2e."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cad_core', ROOT / 'play-gui/cad/cad_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class Transactions:
    def __init__(self):
        self.calls = []

    def openTransaction(self, title):
        self.calls.append(('open', title))

    def commitTransaction(self):
        self.calls.append(('commit',))

    def abortTransaction(self):
        self.calls.append(('abort',))

    def recompute(self):
        self.calls.append(('recompute',))


class WorkspacePolicyTest(unittest.TestCase):
    def test_commit_and_recompute_once(self):
        doc = Transactions()
        with core.transaction(doc, 'test'):
            doc.calls.append(('mutation',))
        self.assertEqual(doc.calls, [('open', 'test'), ('mutation',), ('recompute',), ('commit',)])

    def test_failure_aborts_and_recomputes_before_propagating(self):
        doc = Transactions()
        with self.assertRaisesRegex(ValueError, 'invalid geometry'):
            with core.transaction(doc, 'test'):
                raise ValueError('invalid geometry')
        self.assertEqual(doc.calls, [('open', 'test'), ('abort',), ('recompute',)])

    def test_view_provider_is_resolved_to_sketch_object(self):
        sketch = SimpleNamespace(TypeId='Sketcher::SketchObject')
        gui = SimpleNamespace(activeDocument=lambda: SimpleNamespace(getInEdit=lambda: SimpleNamespace(Object=sketch)))
        self.assertIs(core.sketch_in_edit(gui), sketch)

    def test_non_sketch_edit_is_not_treated_as_sketch(self):
        gui = SimpleNamespace(activeDocument=lambda: SimpleNamespace(getInEdit=lambda: SimpleNamespace(Object=SimpleNamespace(TypeId='PartDesign::Pad'))))
        self.assertIsNone(core.sketch_in_edit(gui))

    def test_body_is_found_through_containment(self):
        body = SimpleNamespace(TypeId='PartDesign::Body')
        sketch = SimpleNamespace(InListRecursive=[SimpleNamespace(TypeId='App::Part'), body])
        self.assertIs(core.body_of(sketch), body)

    def test_invalid_or_disconnected_solid_is_rejected(self):
        def shape(null=False, valid=True, count=1):
            return SimpleNamespace(isNull=lambda: null, isValid=lambda: valid, Solids=[object()] * count)
        for value in (shape(null=True), shape(valid=False), shape(count=0), shape(count=2)):
            with self.subTest(value=value), self.assertRaises(core.CadError):
                core.valid_shape(value)
        core.valid_shape(shape())

    def test_extrusion_cancel_is_idempotent_and_restores_visibility(self):
        obj = SimpleNamespace(ViewObject=SimpleNamespace(Visibility=False))
        doc = Transactions()
        doc.getObject = lambda name: obj
        session = core.ExtrusionSession.__new__(core.ExtrusionSession)
        session.closed = False
        session.doc = doc
        session.visibility = {'Pad': True}
        session.cancel()
        session.cancel()
        self.assertEqual(doc.calls, [('abort',), ('recompute',)])
        self.assertTrue(obj.ViewObject.Visibility)

    def test_cancel_resumes_autosaving_after_preview(self):
        doc = Transactions()
        doc.getObject = lambda name: None
        session = core.ExtrusionSession.__new__(core.ExtrusionSession)
        session.closed = False
        session.doc, session.visibility = doc, {}
        saved = lambda: 'original'
        deferred = lambda: None
        session._saver = SimpleNamespace(save=deferred, dirty=False)
        session._saved_save, session._defer_save = saved, deferred
        session.cancel()
        self.assertIs(session._saver.save, saved)
        self.assertTrue(session._saver.dirty)

    def test_selection_ambiguity_requires_explicit_sketch(self):
        gui = SimpleNamespace(activeDocument=lambda: None,
                              Selection=SimpleNamespace(getSelection=lambda: []))
        with self.assertRaises(core.CadError):
            core.selected_sketch(None, gui)


if __name__ == '__main__':
    unittest.main()

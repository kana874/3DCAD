# SPDX-License-Identifier: LGPL-2.1-or-later
"""Model operations for the native workspace. No Qt widgets or browser globals.

The FreeCAD document is authoritative; every public mutation is transactional.
This first milestone deliberately uses whole closed sketches as Pad/Pocket
profiles. Region picking is not advertised until it has a tested backend.
"""
from contextlib import contextmanager
import math


class CadError(ValueError):
    pass


def sketch_in_edit(gui):
    gdoc = gui.activeDocument()
    edit = gdoc.getInEdit() if gdoc else None
    if isinstance(edit, (tuple, list)):
        edit = edit[0] if edit else None
    edit = getattr(edit, 'Object', edit)
    return edit if getattr(edit, 'TypeId', '') == 'Sketcher::SketchObject' else None


def body_of(obj):
    if obj is None:
        return None
    if getattr(obj, 'TypeId', '') == 'PartDesign::Body':
        return obj
    for parent in getattr(obj, 'InListRecursive', ()):
        if getattr(parent, 'TypeId', '') == 'PartDesign::Body':
            return parent
    return None


def length(app, text, positive=True):
    """Parse dimensions with FreeCAD's quantity parser, never Python eval."""
    try:
        q = app.Units.Quantity(str(text))
        # Bare numbers mean mm. Other units must be length dimensions.
        if q.Unit != app.Units.Unit() and q.Unit != app.Units.Quantity('1 mm').Unit:
            raise ValueError('length unit required')
        value = float(q.Value)
    except Exception as error:
        raise CadError('長さを数値と単位で入力してください（例：25 mm、2 cm）。') from error
    if not math.isfinite(value) or abs(value) > 100000 or (positive and value <= 0):
        raise CadError('長さは0より大きく100000 mm以下にしてください。')
    return value


def valid_shape(shape, single=True):
    if shape.isNull() or not shape.isValid() or not shape.Solids:
        raise CadError('有効なソリッドを作成できません。輪郭と加工方向を確認してください。')
    if single and len(shape.Solids) != 1:
        raise CadError('結合されない形状です。新規ボディを選ぶか、輪郭を見直してください。')


def target_distance(target, origin, direction):
    """Distance to a parallel target plane, measured along the sweep axis."""
    import Part
    if not target or len(target) != 2 or not target[0] or not str(target[1]).startswith('Face'):
        raise CadError('終端の平面を選択してください。')
    try:
        face = target[0].Shape.getElement(target[1])
    except Exception as error:
        raise CadError('終端面が見つかりません。選択し直してください。') from error
    if face.ShapeType != 'Face' or not isinstance(face.Surface, Part.Plane):
        raise CadError('終端には平行な平面を選択してください。')
    normal = face.normalAt(0, 0)
    dot = normal.dot(direction)
    if abs(abs(dot) - 1.0) > 1e-6:
        raise CadError('現在は押し出し面に平行な終端面に対応しています。')
    distance = (face.CenterOfMass - origin).dot(normal) / dot
    if not math.isfinite(distance) or distance <= 1e-6 or distance > 100000:
        raise CadError('終端面が押し出し方向の先にありません。方向を確認してください。')
    return distance


@contextmanager
def transaction(doc, label):
    doc.openTransaction(label)
    try:
        yield
        doc.recompute()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        doc.recompute()
        raise


def create_sketch(app, gui, plane='XY', face_selection=None):
    """Create on a real attachment when a face is selected, not a copied pose."""
    import Part
    doc = app.ActiveDocument
    if doc is None:
        doc = app.newDocument()
    if gui.activeDocument().getInEdit():
        raise CadError('現在の編集を終了してからスケッチを作成してください。')
    support = None
    if face_selection:
        obj, name = face_selection
        if getattr(obj, 'TypeId', '') == 'PartDesign::Body' and obj.Tip:
            obj = obj.Tip
        face = obj.Shape.getElement(name)
        if not isinstance(face.Surface, Part.Plane):
            raise CadError('スケッチには平面を選択してください。')
        body = body_of(obj)
        if body is None:
            raise CadError('この段階ではPartDesignボディの平面を選択してください。')
        support = (obj, [name])
    else:
        bodies = doc.findObjects('PartDesign::Body')
        active = gui.activeDocument().activeView().getActiveObject('pdbody')
        body = active if active in bodies else (bodies[0] if len(bodies) == 1 else None)
        if len(bodies) > 1 and body is None:
            raise CadError('スケッチを置くボディをツリーで選択してください。')
    with transaction(doc, 'スケッチを作成'):
        if body is None:
            body = doc.addObject('PartDesign::Body', 'Body')
        sketch = body.newObject('Sketcher::SketchObject', 'Sketch')
        sketch.Label = 'スケッチ'
        if support:
            sketch.AttachmentSupport = support
            sketch.MapMode = 'FlatFace'
        elif plane != 'XY':
            normal = app.Vector(1, 0, 0) if plane == 'YZ' else app.Vector(0, -1, 0)
            sketch.Placement.Rotation = app.Rotation(app.Vector(0, 0, 1), normal)
    view = gui.activeDocument().activeView()
    view.setActiveObject('pdbody', body)
    gui.Selection.clearSelection()
    gui.activeDocument().setEdit(sketch.Name)
    if hasattr(sketch.ViewObject, 'ShowGrid'):
        sketch.ViewObject.ShowGrid = True
        if hasattr(sketch.ViewObject, 'GridAuto'):
            sketch.ViewObject.GridAuto = True
    return sketch


def add_rectangle(app, sketch, width, height, x=0.0, y=0.0, center=False):
    import Part
    import Sketcher
    v = app.Vector
    if center:
        x, y = x - width / 2, y - height / 2
    corners = [v(x, y, 0), v(x + width, y, 0),
               v(x + width, y + height, 0), v(x, y + height, 0)]
    with transaction(sketch.Document, '寸法付き長方形'):
        start = sketch.GeometryCount
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]), False)
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint('Coincident', start + i, 2, start + (i + 1) % 4, 1))
            sketch.addConstraint(Sketcher.Constraint('Horizontal' if i % 2 == 0 else 'Vertical', start + i))
        sketch.addConstraint(Sketcher.Constraint('Distance', start, width))
        sketch.addConstraint(Sketcher.Constraint('Distance', start + 1, height))
        if center:
            point = sketch.addGeometry(Part.Point(v(x + width / 2, y + height / 2, 0)), True)
            sketch.addConstraint(Sketcher.Constraint('Symmetric', start, 1, start + 2, 1, point, 1))
            sketch.addConstraint(Sketcher.Constraint('Block', point))


def add_circle(app, sketch, diameter, x=0.0, y=0.0):
    import Part
    import Sketcher
    with transaction(sketch.Document, '直径指定の円'):
        index = sketch.addGeometry(Part.Circle(app.Vector(x, y, 0), app.Vector(0, 0, 1), diameter / 2), False)
        sketch.addConstraint(Sketcher.Constraint('Diameter', index, diameter))


def selected_sketch(app, gui):
    edit = sketch_in_edit(gui)
    if edit:
        return edit
    selected = gui.Selection.getSelection()
    sketches = [o for o in selected if getattr(o, 'TypeId', '') == 'Sketcher::SketchObject']
    if len(sketches) == 1 and len(selected) == 1:
        return sketches[0]
    raise CadError('閉じたスケッチを一つ選択してください。スケッチ編集中はEで直接進めます。')


class ExtrusionSession:
    """One transaction per accepted extrusion, abort restores preview changes.

    Session owns the document until commit/cancel; the shell locks unrelated
    editing actions. Preview is exact OCCT geometry, not an approximate mesh.
    """
    def __init__(self, app, gui, sketch):
        self.app, self.gui, self.sketch = app, gui, sketch
        self.doc = sketch.Document
        self.body = body_of(sketch)
        if self.body is None:
            raise CadError('PartDesignボディ内のスケッチを選択してください。')
        self.previous = self.body.Tip
        if self.previous == sketch or not getattr(getattr(self.previous, 'Shape', None), 'Solids', []):
            # A sketch can itself be Body.Tip; look for the last solid before it.
            self.previous = next((o for o in reversed(self.body.Group)
                                  if o != sketch and getattr(getattr(o, 'Shape', None), 'Solids', [])), None)
        self.visibility = {o.Name: o.ViewObject.Visibility for o in self.doc.Objects}
        self.closed = False
        self.preview = None
        self.region_candidates = None
        self.region_keys = None
        self.use_source_sketch = False
        self.boundaries = []
        self.doc.openTransaction('押し出し')
        # A long-lived preview must never enter the browser's recovery copy.
        # Resume the existing autosaver on both commit and abort; don't replace
        # the browser persistence implementation or its prior saved files.
        self._saver = getattr(app, '_fcweb_saver', None)
        self._saved_save = getattr(self._saver, 'save', None)
        self._defer_save = lambda *args, **kwargs: None
        if self._saved_save:
            self._saver.save = self._defer_save

    def _resume_saving(self):
        saver = getattr(self, '_saver', None)
        if saver and saver.save is self._defer_save:
            saver.save = self._saved_save
            saver.dirty = True

    def _check(self):
        if self.closed or self.app.ActiveDocument != self.doc:
            raise CadError('押し出し操作の文書が変更されました。操作をやり直してください。')

    def update(self, distance, operation='join', reversed=False, symmetric=False, through=False, distance2=None, start=0, target=None):
        import Part
        self._check()
        if not math.isfinite(distance) or distance <= 0 or distance > 100000:
            raise CadError('正の押し出し距離を指定してください。')
        if distance2 is not None and (not math.isfinite(distance2) or distance2 <= 0 or distance2 > 100000):
            raise CadError('反対側にも正の押し出し距離を指定してください。')
        if not math.isfinite(start) or abs(start) > 100000:
            raise CadError('開始オフセットを確認してください。')
        if target:
            if symmetric or through or distance2 is not None:
                raise CadError('終端面までは片側の押し出しで指定してください。')
            if target[0].Document != self.doc:
                raise CadError('同じ設計内の終端面を選択してください。')
            normal = self.sketch.Placement.Rotation.multVec(self.app.Vector(0, 0, 1))
            direction = normal * (-1 if reversed else 1)
            distance = target_distance(target, self.sketch.Placement.Base + direction * start, direction)
        if through:
            if operation != 'cut' or self.previous is None or symmetric or distance2 is not None:
                raise CadError('貫通は既存ボディの片側切り取りで指定してください。')
            bounds = self.previous.Shape.BoundBox
            distance = bounds.DiagonalLength + (self.sketch.Placement.Base - bounds.Center).Length + abs(start) + 1
        if self.region_candidates is not None:
            if not self.region_keys:
                raise CadError('押し出す領域をクリック、または一覧から選択してください。')
            selected = [dict(self.region_candidates)[key] for key in self.region_keys]
            face = selected[0].multiFuse(selected[1:]).removeSplitter() if len(selected) > 1 else selected[0].copy()
            face.Placement = self.sketch.Placement.multiply(face.Placement)
        else:
            wires = self.sketch.Shape.Wires
            if not wires or any(not wire.isClosed() for wire in wires):
                raise CadError('輪郭が閉じていません。スケッチの端点を確認してください。')
            face = Part.makeFace(wires, 'Part::FaceMakerBullseye')
        normal = self.sketch.Placement.Rotation.multVec(self.app.Vector(0, 0, 1))
        face.translate(normal * (-start if reversed else start))
        direction = normal * (-distance if reversed else distance)
        if distance2 is not None:
            face.translate(normal * -distance2)
            direction = normal * (distance + distance2)
        elif symmetric:
            face.translate(direction * -0.5)
        tool = face.extrude(direction)
        if operation == 'join':
            result = self.previous.Shape.fuse(tool) if self.previous else tool
        elif operation == 'cut':
            if self.previous is None:
                raise CadError('切り取りには既存のソリッドが必要です。')
            result = self.previous.Shape.cut(tool)
            if abs(result.Volume - self.previous.Shape.Volume) < 1e-7:
                raise CadError('切り取りがボディと交差していません。方向を反転してください。')
        elif operation == 'intersect':
            if self.previous is None:
                raise CadError('交差には既存のソリッドが必要です。')
            result = self.previous.Shape.common(tool)
        elif operation == 'new':
            result = tool
        else:
            raise CadError('未対応の操作です。')
        valid_shape(result)
        if self.preview is None:
            self.preview = self.doc.addObject('Part::Feature', 'CADPreview')
            self.preview.Label = 'プレビュー（未確定）'
            self.preview.ViewObject.ShapeColor = (0.25, 0.65, 0.95)
            self.preview.ViewObject.Transparency = 35
            self.preview.ViewObject.Selectable = False
        self.preview.Shape = result
        self.preview.ViewObject.Visibility = True
        if self.previous:
            self.previous.ViewObject.Visibility = operation == 'new'
        self.doc.recompute()
        return result

    def accept(self, distance, operation='join', reversed=False, symmetric=False, through=False, distance2=None, start=0, target=None):
        self.update(distance, operation, reversed, symmetric, through, distance2, start, target)
        try:
            self.doc.removeObject(self.preview.Name)
            self.preview = None
            kind = 'PartDesign::Pocket' if operation == 'cut' else 'PartDesign::Pad'
            target_body = self.body
            separate_body = operation == 'new' and self.previous is not None
            if separate_body:
                target_body = self.doc.addObject('PartDesign::Body', 'Body')
                target_body.Label = '新規ボディ'
            profile = self.sketch
            if self.region_candidates is not None and (not self.use_source_sketch or separate_body):
                from cad_profiles import make_profile
                profile = make_profile(target_body, self.sketch, self.boundaries, self.region_keys)
                target_body.Tip = None if separate_body else (self.previous or self.sketch)
            if operation == 'intersect':
                from cad_face import SketchIntersection
                feature = target_body.newObject('PartDesign::FeaturePython', 'SketchIntersection')
                feature.Label = '交差'
                SketchIntersection(feature)
                feature.SourceProfile = profile
                feature.SourceSketch = self.sketch
                feature.SourceBase = self.previous
                feature.Length = distance
                feature.Length2 = distance2 if distance2 is not None else 0
                feature.StartOffset = start
                feature.ToFace = bool(target)
                if target:
                    feature.TargetFeature, feature.TargetFace = target
                feature.Reversed, feature.Symmetric = reversed, symmetric
                feature.TwoSides = distance2 is not None
                self.doc.recompute()
                if feature.IntersectionStatus != 'OK':
                    raise CadError(feature.IntersectionStatus)
                valid_shape(feature.Shape)
                profile.ViewObject.Visibility = False
                self.sketch.ViewObject.Visibility = False
                self.previous.ViewObject.Visibility = False
                feature.ViewObject.Visibility = True
                target_body.Tip = feature
                self.doc.commitTransaction()
                self.closed = True
                self._resume_saving()
                return feature
            feature = target_body.newObject(kind, 'Pocket' if operation == 'cut' else 'Pad')
            feature.Profile = profile
            feature.Length = distance
            if start:
                if 'StartType' not in feature.PropertiesList:
                    raise CadError('この環境では開始オフセットを利用できません。')
                feature.StartType = 'Offset'
                feature.StartOffset = start
            if through:
                feature.Type = 1  # Native Pocket: Through all (parametric).
            elif target:
                feature.Type = 3  # Native Pad/Pocket: up to a referenced face.
                feature.UpToFace = (target[0], [target[1]])
            # Pocket's default axis points into the support (-normal), whereas
            # the unified dialog and preview always use the sketch +normal.
            feature.Reversed = not reversed if operation == 'cut' else reversed
            if 'SideType' in feature.PropertiesList:
                feature.SideType = 'Two sides' if distance2 is not None else ('Symmetric' if symmetric else 'One side')
                if distance2 is not None:
                    feature.Length2 = distance2
            else:
                if distance2 is not None:
                    raise CadError('この環境では両側の押し出しを利用できません。')
                feature.Midplane = symmetric
            self.doc.recompute()
            valid_shape(feature.Shape)
            feature.Label = '切り取り' if operation == 'cut' else '押し出し'
            profile.ViewObject.Visibility = False
            self.sketch.ViewObject.Visibility = False
            if self.previous and not separate_body:
                self.previous.ViewObject.Visibility = False
            elif self.previous:
                self.body.Tip = self.previous
                self.previous.ViewObject.Visibility = True
            feature.ViewObject.Visibility = True
            target_body.Tip = feature
            self.doc.commitTransaction()
            self.closed = True
            self._resume_saving()
            return feature
        except Exception:
            self.cancel()
            raise

    def cancel(self):
        if self.closed:
            return
        try:
            self.doc.abortTransaction()
            self.doc.recompute()
            for name, visible in self.visibility.items():
                obj = self.doc.getObject(name)
                if obj:
                    obj.ViewObject.Visibility = visible
        finally:
            self.closed = True
            self._resume_saving()


def add_three_point_rectangle(app, sketch, x1, y1, x2, y2, x3, y3):
    """First two points define the base; the third defines signed height."""
    import Part
    import Sketcher
    dx, dy = x2 - x1, y2 - y1
    width = math.hypot(dx, dy)
    if width <= 1e-6:
        raise CadError('矩形の最初の2点を離してください。')
    ux, uy = dx / width, dy / width
    height = -(x3 - x2) * uy + (y3 - y2) * ux
    if abs(height) <= 1e-6:
        raise CadError('3点目を底辺から離してください。')
    a = app.Vector(x1, y1, 0)
    b = app.Vector(x2, y2, 0)
    offset = app.Vector(-uy * height, ux * height, 0)
    corners = [a, b, b + offset, a + offset]
    with transaction(sketch.Document, '3点矩形'):
        start = sketch.GeometryCount
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]), False)
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint('Coincident', start + i, 2, start + (i + 1) % 4, 1))
        sketch.addConstraint(Sketcher.Constraint('Parallel', start, start + 2))
        sketch.addConstraint(Sketcher.Constraint('Parallel', start + 1, start + 3))
        sketch.addConstraint(Sketcher.Constraint('Perpendicular', start, start + 1))
        sketch.addConstraint(Sketcher.Constraint('Distance', start, width))
        sketch.addConstraint(Sketcher.Constraint('Distance', start + 1, abs(height)))


def add_two_point_circle(app, sketch, x1, y1, x2, y2):
    diameter = math.hypot(x2 - x1, y2 - y1)
    if diameter <= 1e-6:
        raise CadError('円の直径を定義する2点を離してください。')
    add_circle(app, sketch, diameter, (x1 + x2) / 2, (y1 + y2) / 2)

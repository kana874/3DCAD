# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parametric planar-face extrusion and transactional preview."""
import math
import FreeCAD as App
import Part
from cad_core import CadError, body_of, valid_shape


def selected_face(source, face_name):
    if not source or not face_name.startswith('Face') or source.Shape.isNull():
        raise CadError('ボディの平面を一つ選択してください。')
    try:
        face = source.Shape.getElement(face_name)
    except Exception as error:
        raise CadError('面の参照が見つかりません。面を選択し直してください。') from error
    if face.ShapeType != 'Face' or not isinstance(face.Surface, Part.Plane):
        raise CadError('押し出しには平面の面を選択してください。')
    return face


def result_for_face(source, face_name, distance, operation, reversed=False, symmetric=False, through=False):
    if not math.isfinite(distance) or distance <= 0 or distance > 100000:
        raise CadError('正の押し出し距離を指定してください。')
    face = selected_face(source, face_name).copy()
    if through:
        if operation != 'cut' or symmetric:
            raise CadError('貫通は片側の切り取りで指定してください。')
        bounds = source.Shape.BoundBox
        distance = bounds.DiagonalLength + (face.CenterOfMass - bounds.Center).Length + 1
    normal = face.normalAt(0, 0)
    vector = normal * (-distance if reversed else distance)
    if symmetric:
        face.translate(vector * -0.5)
    tool = face.extrude(vector)
    if operation == 'join':
        result = source.Shape.fuse(tool).removeSplitter()
    elif operation == 'cut':
        result = source.Shape.cut(tool).removeSplitter()
        if abs(result.Volume - source.Shape.Volume) < 1e-7:
            raise CadError('切り取りがボディと交差していません。方向を反転してください。')
    elif operation == 'intersect':
        result = source.Shape.common(tool).removeSplitter()
    elif operation == 'new':
        result = tool
    else:
        raise CadError('未対応の操作です。')
    valid_shape(result)
    return result


class FaceExtrusion:
    """FeaturePython proxy; links retain the original face and base shape."""
    def __init__(self, obj):
        obj.addProperty('App::PropertyLink', 'SourceFeature', '押し出し')
        obj.addProperty('App::PropertyString', 'SourceFace', '押し出し')
        obj.addProperty('App::PropertyLength', 'Length', '押し出し')
        obj.addProperty('App::PropertyEnumeration', 'Operation', '押し出し')
        obj.Operation = ['join', 'cut', 'intersect', 'new']
        obj.addProperty('App::PropertyBool', 'Reversed', '押し出し')
        obj.addProperty('App::PropertyBool', 'Symmetric', '押し出し')
        obj.addProperty('App::PropertyBool', 'ThroughAll', '押し出し')
        obj.addProperty('App::PropertyString', 'FaceStatus', '押し出し')
        obj.setEditorMode('FaceStatus', 1)
        obj.Proxy = self

    def execute(self, obj):
        try:
            obj.Shape = result_for_face(obj.SourceFeature, obj.SourceFace, float(obj.Length),
                                        str(obj.Operation), obj.Reversed, obj.Symmetric, obj.ThroughAll)
            obj.FaceStatus = 'OK'
        except Exception as error:
            obj.FaceStatus = '面の再選択または条件の修正が必要: ' + str(error)
            raise RuntimeError(obj.FaceStatus) from error

    def dumps(self):
        return None

    def loads(self, state):
        pass


class FaceExtrusionSession:
    def __init__(self, app, gui, selection):
        source, name = selection
        body = body_of(source)
        if getattr(source, 'TypeId', '') == 'PartDesign::Body':
            body, source = source, source.Tip
        if not body or not source or body.Tip != source:
            raise CadError('現在のボディの面を選択してください。')
        selected_face(source, name)
        self.app, self.gui, self.doc = app, gui, source.Document
        self.body, self.previous, self.face_name = body, source, name
        self.visibility = {o.Name: o.ViewObject.Visibility for o in self.doc.Objects}
        self.preview = None
        self.closed = False
        self.doc.openTransaction('面を押し出し')

    def update(self, distance, operation='join', reversed=False, symmetric=False, through=False):
        if self.closed or self.app.ActiveDocument != self.doc:
            raise CadError('押し出し操作の文書が変更されました。')
        result = result_for_face(self.previous, self.face_name, distance, operation, reversed, symmetric, through)
        if self.preview is None:
            self.preview = self.doc.addObject('Part::Feature', 'CADPreview')
            self.preview.Label = 'プレビュー（未確定）'
            self.preview.ViewObject.ShapeColor = (0.25, 0.65, 0.95)
            self.preview.ViewObject.Transparency = 35
            self.preview.ViewObject.Selectable = False
        self.preview.Shape = result
        self.preview.ViewObject.Visibility = True
        self.previous.ViewObject.Visibility = operation == 'new'
        self.doc.recompute()
        return result

    def accept(self, distance, operation='join', reversed=False, symmetric=False, through=False):
        self.update(distance, operation, reversed, symmetric, through)
        try:
            self.doc.removeObject(self.preview.Name)
            self.preview = None
            target = self.body
            if operation == 'new':
                target = self.doc.addObject('PartDesign::Body', 'Body')
                target.Label = '新規ボディ'
            obj = target.newObject('PartDesign::FeaturePython', 'FaceExtrusion')
            obj.Label = '面押し出し'
            FaceExtrusion(obj)
            obj.SourceFeature = self.previous
            obj.SourceFace = self.face_name
            obj.Length = distance
            obj.Operation = operation
            obj.Reversed, obj.Symmetric, obj.ThroughAll = reversed, symmetric, through
            self.doc.recompute()
            if obj.FaceStatus != 'OK':
                raise CadError(obj.FaceStatus)
            valid_shape(obj.Shape)
            if operation != 'new':
                self.previous.ViewObject.Visibility = False
            obj.ViewObject.Visibility = True
            target.Tip = obj
            self.doc.commitTransaction()
            self.closed = True
            return obj
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

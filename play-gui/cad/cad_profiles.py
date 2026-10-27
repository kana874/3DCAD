# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exact planar arrangements and persistent region references for native Pad/Pocket.

The FCStd stores the proxy module name. This module ships with the workspace;
standard FreeCAD installations must install it to recompute region profiles.
"""
import json
import hashlib
from collections import defaultdict
import FreeCAD as App
import Part
from BOPTools import SplitAPI
from cad_core import CadError

TOLERANCE = 1e-6


def source_edges(sketch, boundaries=()):
    edges = []
    for index, geometry in enumerate(sketch.Geometry):
        if not sketch.getConstruction(index):
            shape = geometry.toShape()
            for edge in shape.Edges:
                edges.append(('sketch:%d' % index, edge))
    inverse = sketch.Placement.inverse().toMatrix()
    for obj in boundaries:
        if obj is None or obj.Shape.isNull():
            continue
        local = obj.Shape.copy()
        local.transformShape(inverse, True)
        bounds = local.BoundBox
        extent = max(bounds.DiagonalLength * 2, 100)
        plane = Part.makePlane(bounds.XLength + 2 * extent, bounds.YLength + 2 * extent, App.Vector(bounds.XMin - extent, bounds.YMin - extent, 0))
        section = local.section(plane)
        # Stable source edge identity is derived from model edge incidence.
        for edge in section.Edges:
            origins = []
            for i, face in enumerate(local.Faces):
                if edge.common(face).Length > edge.Length - TOLERANCE:
                    origins.append(str(i))
            edges.append(('boundary:%s:%s' % (obj.Name, ','.join(origins)), edge))
    return edges


def regions(sketch, boundaries=()):
    sources = source_edges(sketch, boundaries)
    if not sources:
        return []
    bounds = Part.makeCompound([e for _, e in sources]).BoundBox
    margin = max(bounds.DiagonalLength, 10)
    base = Part.makePlane(bounds.XLength + 2 * margin, bounds.YLength + 2 * margin,
                          App.Vector(bounds.XMin - margin, bounds.YMin - margin, 0))
    split = SplitAPI.slice(base, [e for _, e in sources], 'Split')
    bounded = [face for face in split.Faces if face.Area > TOLERANCE and
               not any(edge.common(base.OuterWire).Length > TOLERANCE for edge in face.Edges)]
    # A circle cut by a diameter has the same source curves on both sides.
    # Persist the order of the split fragments along each original curve too.
    fragments = defaultdict(list)
    memberships = []
    for face in bounded:
        face_members = []
        for edge in face.Edges:
            identities = []
            for name, source in sources:
                if edge.common(source).Length > edge.Length - TOLERANCE:
                    items = fragments[name]
                    if not any(edge.isSame(existing[1]) for existing in items):
                        midpoint = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
                        parameter = source.Curve.parameter(midpoint)
                        items.append((parameter, edge))
                    identities.append(name)
            if not identities:
                raise CadError('領域の境界を参照できません。線の重複や交差を確認してください。')
            face_members.append((edge, sorted(set(identities))))
        memberships.append((face, face_members))
    for items in fragments.values():
        items.sort(key=lambda item: item[0])
    result = []
    for face, members in memberships:
        signature = []
        for edge, identities in members:
            parts = []
            for name in identities:
                items = fragments[name]
                index = next(i for i, (_, fragment) in enumerate(items) if edge.isSame(fragment))
                parts.append('%s:fragment%dof%d' % (name, index, len(items)))
            signature.append('|'.join(parts))
        result.append((json.dumps(sorted(signature), separators=(',', ':')), face))
    # Repeated source signatures cannot be persisted unambiguously.
    counts = defaultdict(int)
    for key, _ in result:
        counts[key] += 1
    if any(count > 1 for count in counts.values()):
        raise CadError('同じ境界参照を持つ領域があります。スケッチを分割して再選択してください。')
    return sorted(result, key=lambda item: (item[1].CenterOfMass.x, item[1].CenterOfMass.y, item[1].Area))


class RegionProfile:
    def __init__(self, obj):
        obj.addProperty('App::PropertyLink', 'SourceSketch', 'Profile')
        obj.addProperty('App::PropertyLinkList', 'BoundaryObjects', 'Profile')
        obj.addProperty('App::PropertyStringList', 'RegionKeys', 'Profile')
        obj.addProperty('App::PropertyString', 'ProfileStatus', 'Profile')
        obj.setEditorMode('ProfileStatus', 1)
        obj.addProperty('App::PropertyString', 'InputSignature', 'Profile')
        obj.setEditorMode('InputSignature', 2)
        obj.Proxy = self

    def execute(self, obj):
        try:
            digest = hashlib.sha256()
            digest.update(obj.SourceSketch.Shape.exportBrepToString().encode())
            digest.update(str(obj.SourceSketch.Placement).encode())
            digest.update(json.dumps(list(obj.RegionKeys)).encode())
            for boundary in obj.BoundaryObjects:
                digest.update(boundary.Shape.exportBrepToString().encode())
            signature = digest.hexdigest()
            if obj.InputSignature == signature and not obj.Shape.isNull():
                return
            candidates = dict(regions(obj.SourceSketch, obj.BoundaryObjects))
            selected = [candidates[key] for key in obj.RegionKeys]
            if not selected:
                raise CadError('押し出す領域を選択してください。')
            # Fuse adjacent selected cells so native Pad gets a proper boundary.
            shape = selected[0].multiFuse(selected[1:]).removeSplitter() if len(selected) > 1 else selected[0]
            shape = shape.copy()
            obj.Shape = shape
            obj.Placement = obj.SourceSketch.Placement
            obj.ProfileStatus = 'OK'
            obj.InputSignature = signature
        except Exception as error:
            obj.Shape = Part.Shape()
            obj.ProfileStatus = '領域の再選択が必要: ' + str(error)
            raise RuntimeError(obj.ProfileStatus) from error

    def onDocumentRestored(self, obj):
        obj.touch()

    def dumps(self):
        return None

    def loads(self, state):
        pass


def make_profile(body, sketch, boundaries, keys):
    obj = body.newObject('PartDesign::FeaturePython', 'RegionProfile')
    obj.Label = '選択領域'
    RegionProfile(obj)
    obj.SourceSketch = sketch
    obj.BoundaryObjects = list(boundaries)
    obj.RegionKeys = list(keys)
    obj.Document.recompute()
    if obj.Shape.isNull() or obj.ProfileStatus != 'OK':
        raise CadError(obj.ProfileStatus)
    obj.ViewObject.Visibility = False
    return obj


def restore_proxies():
    """Repair recovery files opened by upstream before our module was loaded."""
    repaired = 0
    for doc in App.listDocuments().values():
        for obj in doc.Objects:
            if obj.TypeId == 'PartDesign::FeaturePython' and all(name in obj.PropertiesList for name in ('SourceSketch', 'BoundaryObjects', 'RegionKeys', 'ProfileStatus', 'InputSignature')):
                if not isinstance(obj.Proxy, RegionProfile):
                    obj.Proxy = RegionProfile.__new__(RegionProfile)
                    obj.touch()
                    repaired += 1
        if repaired:
            doc.recompute()
    return repaired


class ProfileEditSession:
    """Selection remains transient until Apply; persistence sees no preview data."""
    editing_profile = True

    def __init__(self, profile):
        self.profile = profile
        self.doc = profile.Document
        self.sketch = profile.SourceSketch
        self.boundaries = list(profile.BoundaryObjects)
        self.previous = self.boundaries[0] if self.boundaries else None
        self.region_candidates = []
        self.region_keys = list(profile.RegionKeys)
        self.preview = None
        self.closed = False
        self.use_source_sketch = False

    def accept(self):
        from cad_core import transaction
        if not self.region_keys or App.ActiveDocument != self.doc:
            raise CadError('領域を選択してください。')
        with transaction(self.doc, '押し出し領域を変更'):
            self.profile.BoundaryObjects = self.boundaries
            self.profile.RegionKeys = self.region_keys
            self.doc.recompute()
            if self.profile.Shape.isNull() or self.profile.ProfileStatus != 'OK':
                raise CadError(self.profile.ProfileStatus)
            for child in self.profile.InListRecursive:
                if 'Invalid' in child.State:
                    raise CadError('領域変更で後続フィーチャの参照が失われました。')
        self.closed = True

    def cancel(self):
        self.closed = True

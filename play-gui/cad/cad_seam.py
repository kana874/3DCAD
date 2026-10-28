# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hide only topological seam lines; keep all geometry and selection indices."""
from pivy import coin


def seam_indices(shape):
    faces = shape.Faces
    candidates = []
    for face in faces:
        for edge in face.Edges:
            if edge.isSeam(face) and not any(edge.isSame(other) for other in candidates):
                candidates.append(edge)
    indices = []
    for edge in candidates:
        owners = [face for face in faces if any(edge.isSame(item) for item in face.Edges)]
        if len(owners) == 1:
            indices.extend(i for i, item in enumerate(shape.Edges) if item.isSame(edge))
    return sorted(set(indices))


def line_nodes(view):
    search = coin.SoSearchAction()
    search.setType(coin.SoIndexedLineSet.getClassTypeId())
    search.setInterest(coin.SoSearchAction.ALL)
    search.apply(view.RootNode)
    for path in search.getPaths():
        parent = path.getNode(path.getLength() - 2)
        children = [parent.getChild(i) for i in range(parent.getNumChildren())]
        binding = next((n for n in children if str(n.getName()) == 'LineBind'), None)
        material = next((n for n in children if str(n.getName()) == 'LineMaterial'), None)
        if binding and material:
            return path.getTail()
    return None


class SeamVisibility:
    def __init__(self):
        self.applied = {}
        self.nonseams = {}

    def apply(self, obj):
        shape = obj.Shape
        if shape.isNull() or len(shape.Edges) > 5000:
            return []
        key = (obj.Document.Name, obj.Name)
        if self.nonseams.get(key) == shape.hashCode():
            return []
        previous = self.applied.get(key)
        if previous and previous['hash'] == shape.hashCode():
            return previous['seams']
        line_set = line_nodes(obj.ViewObject)
        if previous:
            if previous['line_set'] == line_set:
                self.restore(obj)
            else:
                self.applied.pop(key, None)
        seams = seam_indices(shape)
        if not seams:
            self.nonseams[key] = shape.hashCode()
            return []
        self.nonseams.pop(key, None)
        if line_set is None:
            return []
        original = list(line_set.coordIndex.getValues())
        # Keep every group and index slot so real edge selection indices do
        # not shift. Collapse seam polyline vertices to one coordinate; only
        # the transient Coin drawing changes, never the OCCT shape itself.
        groups, current = [], []
        for index in original:
            if index < 0:
                groups.append(current)
                current = []
            else:
                current.append(index)
        if current or len(groups) != len(shape.Edges):
            return []  # Unknown representation: preserve all drawing/selection.
        modified = list(original)
        group = 0
        first = None
        for i, index in enumerate(original):
            if index < 0:
                group += 1
                first = None
            elif group in seams:
                if first is None:
                    first = index
                modified[i] = first
        self.applied[key] = {'line_set': line_set, 'hash': shape.hashCode(), 'seams': seams,
                             'original': original, 'modified': modified}
        for i, index in enumerate(modified):
            if index != original[i]:
                line_set.coordIndex.set1Value(i, index)
        return seams

    def restore(self, obj):
        key = (obj.Document.Name, obj.Name)
        old = self.applied.pop(key, None)
        if not old:
            return
        field = old['line_set'].coordIndex
        for i, index in enumerate(old['original']):
            if index != old['modified'][i]:
                field.set1Value(i, index)

    def sync(self, doc):
        import FreeCAD as App
        alive = {(d.Name, obj.Name) for d in App.listDocuments().values() for obj in d.Objects}
        self.applied = {k: v for k, v in self.applied.items() if k in alive}
        self.nonseams = {k: v for k, v in self.nonseams.items() if k in alive}
        if doc is None:
            return
        for obj in doc.Objects:
            if obj.Name.startswith('CADPreview') or not hasattr(obj, 'Shape'):
                continue
            try:
                if obj.ViewObject.Visibility:
                    self.apply(obj)
            except Exception as error:
                import FreeCAD as App
                App.Console.PrintWarning('[cad-seam] ' + str(error) + '\n')

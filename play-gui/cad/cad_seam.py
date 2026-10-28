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
            return binding, material
    return None, None


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
        binding, material = line_nodes(obj.ViewObject)
        if previous:
            if previous['binding'] == binding:
                self.restore(obj)
            else:
                self.applied.pop(key, None)
        seams = seam_indices(shape)
        if not seams:
            self.nonseams[key] = shape.hashCode()
            return []
        self.nonseams.pop(key, None)
        if binding is None or material is None:
            return []
        count = len(shape.Edges)
        colors = [color.getValue() for color in material.diffuseColor.getValues()]
        transparency = list(material.transparency.getValues())
        self.applied[key] = {'binding': binding, 'material': material, 'hash': shape.hashCode(), 'seams': seams,
                             'binding_value': binding.value.getValue(), 'colors': colors, 'transparency': transparency}
        base_color = colors[-1] if colors else (0.0, 0.0, 0.0)
        base_alpha = transparency[-1] if transparency else 0.0
        per_color = [colors[i] if i < len(colors) else base_color for i in range(count)]
        per_alpha = [1.0 if i in seams else (transparency[i] if i < len(transparency) else base_alpha) for i in range(count)]
        material.diffuseColor.setNum(count)
        for i, color in enumerate(per_color):
            material.diffuseColor.set1Value(i, color)
        material.transparency.setNum(count)
        for i, alpha in enumerate(per_alpha):
            material.transparency.set1Value(i, alpha)
        binding.value = coin.SoMaterialBinding.PER_FACE
        return seams

    def restore(self, obj):
        key = (obj.Document.Name, obj.Name)
        old = self.applied.pop(key, None)
        if not old:
            return
        material, binding = old['material'], old['binding']
        material.diffuseColor.setNum(len(old['colors']))
        if old['colors']:
            for i, color in enumerate(old['colors']):
                material.diffuseColor.set1Value(i, color)
        material.transparency.setNum(len(old['transparency']))
        if old['transparency']:
            for i, alpha in enumerate(old['transparency']):
                material.transparency.set1Value(i, alpha)
        binding.value = old['binding_value']

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

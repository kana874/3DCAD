# SPDX-License-Identifier: LGPL-2.1-or-later
"""Transient, document-free view selection. No mesh geometry enters the model."""
from pivy import coin
from PySide6 import QtCore
import FreeCAD as App
import FreeCADGui as Gui


class PlanePicker:
    def __init__(self, choose):
        self.view = Gui.activeDocument().activeView()
        self.scene = self.view.getSceneGraph()
        self.choose = choose
        self.root = coin.SoSeparator()
        self.planes = {}
        self.materials = {}
        self.colors = {}
        self.hovered = None
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.SHAPE
        self.root.addChild(pick)
        style = coin.SoShapeHints()
        style.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        style.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
        self.root.addChild(style)
        for name, color in [('XY', (0.25, 0.5, 1)), ('YZ', (1, 0.35, 0.3)), ('XZ', (0.3, 0.8, 0.4))]:
            group = coin.SoSeparator()
            material = coin.SoMaterial()
            material.diffuseColor = color
            material.transparency = 0.55
            group.addChild(material)
            # Positive quadrants separate the three click targets visually.
            points = [(0, 0, 0), (45, 0, 0), (45, 45, 0), (0, 45, 0)]
            if name == 'YZ':
                points = [(z, x, y) for x, y, z in points]
            elif name == 'XZ':
                points = [(x, z, y) for x, y, z in points]
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 4, points)
            group.addChild(coords)
            face = coin.SoFaceSet()
            face.numVertices.setValue(4)
            group.addChild(face)
            self.root.addChild(group)
            self.planes[name] = group
            self.materials[name] = material
            self.colors[name] = color
            caption = coin.SoSeparator()
            translation = coin.SoTranslation()
            midpoint = tuple(sum(p[i] for p in points) / 4 for i in range(3))
            translation.translation = midpoint
            font = coin.SoFont()
            font.size = 15
            text = coin.SoText2()
            text.string = name
            caption.addChild(translation)
            caption.addChild(font)
            caption.addChild(text)
            group.addChild(caption)
        # Annotation draws the planes even when an existing solid covers them.
        annotation = coin.SoAnnotation()
        annotation.addChild(self.root)
        self.annotation = annotation
        self.scene.addChild(annotation)
        self.callback = self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.on_mouse)
        self.move_callback = self.view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.on_move)
        self.view.viewAxonometric()
        self.view.fitAll()

    def pick_at(self, x, y):
        width, height = self.view.getSize()
        ray = coin.SoRayPickAction(coin.SbViewportRegion(width, height))
        ray.setPoint(coin.SbVec2s(int(x), int(height - 1 - y)))
        ray.setPickAll(True)
        pick_root = coin.SoSeparator()
        pick_root.addChild(self.view.getCameraNode())
        pick_root.addChild(self.scene)
        ray.apply(pick_root)
        targets = self.planes.items() if hasattr(self, 'planes') else self.nodes
        targets = list(targets)
        for point in ray.getPickedPointList():
            for key, group in targets:
                if point.getPath().containsNode(group):
                    return key
        return None

    def on_mouse(self, callback):
        event = callback.getEvent()
        if event.getButton() != coin.SoMouseButtonEvent.BUTTON1 or event.getState() != coin.SoButtonEvent.DOWN:
            return
        width, height = self.view.getSize()
        ray = coin.SoRayPickAction(coin.SbViewportRegion(width, height))
        ray.setPoint(event.getPosition())
        ray.setPickAll(True)
        pick_root = coin.SoSeparator()
        pick_root.addChild(self.view.getCameraNode())
        pick_root.addChild(self.scene)
        ray.apply(pick_root)
        for point in ray.getPickedPointList():
            path = point.getPath()
            for name, group in self.planes.items():
                if path.containsNode(group):
                    callback.setHandled()
                    QtCore.QTimer.singleShot(0, lambda plane=name: self.choose(plane))
                    return
        # Planar model faces are handled by FreeCAD's normal selection.

    def on_move(self, callback):
        event = callback.getEvent()
        width, height = self.view.getSize()
        ray = coin.SoRayPickAction(coin.SbViewportRegion(width, height))
        ray.setPoint(event.getPosition())
        ray.setPickAll(True)
        pick_root = coin.SoSeparator()
        pick_root.addChild(self.view.getCameraNode())
        pick_root.addChild(self.scene)
        ray.apply(pick_root)
        hovered = None
        for point in ray.getPickedPointList():
            for name, group in self.planes.items():
                if point.getPath().containsNode(group):
                    hovered = name
                    break
            if hovered:
                break
        if hovered != self.hovered:
            self.hovered = hovered
            for name, material in self.materials.items():
                material.transparency = 0.2 if name == hovered else 0.55

    def close(self):
        if getattr(self, 'move_callback', None) is not None:
            self.view.removeEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.move_callback)
            self.move_callback = None
        if self.callback is not None:
            self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
            self.callback = None
        if self.annotation is not None:
            self.scene.removeChild(self.annotation)
            self.annotation = None


class RegionPicker:
    def __init__(self, sketch, regions, choose):
        self.view = Gui.activeDocument().activeView()
        self.scene = self.view.getSceneGraph()
        self.choose = choose
        self.regions = regions
        self.root = coin.SoSeparator()
        self.materials = []
        self.nodes = []
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.SHAPE
        self.root.addChild(pick)
        for key, face in regions:
            group = coin.SoSeparator()
            material = coin.SoMaterial()
            material.diffuseColor = (0.2, 0.55, 0.95)
            material.transparency = 0.65
            group.addChild(material)
            points, triangles = face.tessellate(0.1)
            points = [sketch.Placement.multVec(p) for p in points]
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            mesh = coin.SoIndexedFaceSet()
            indices = [i for tri in triangles for i in (*tri, -1)]
            mesh.coordIndex.setValues(0, len(indices), indices)
            group.addChild(coords)
            group.addChild(mesh)
            self.root.addChild(group)
            self.nodes.append((key, group))
            self.materials.append(material)
        self.annotation = coin.SoAnnotation()
        self.annotation.addChild(self.root)
        self.scene.addChild(self.annotation)
        self.callback = self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.on_mouse)

    def on_mouse(self, callback):
        event = callback.getEvent()
        if event.getButton() != coin.SoMouseButtonEvent.BUTTON1 or event.getState() != coin.SoButtonEvent.DOWN:
            return
        width, height = self.view.getSize()
        ray = coin.SoRayPickAction(coin.SbViewportRegion(width, height))
        ray.setPoint(event.getPosition())
        ray.setPickAll(True)
        pick_root = coin.SoSeparator()
        pick_root.addChild(self.view.getCameraNode())
        pick_root.addChild(self.scene)
        ray.apply(pick_root)
        for point in ray.getPickedPointList():
            for key, group in self.nodes:
                if point.getPath().containsNode(group):
                    callback.setHandled()
                    QtCore.QTimer.singleShot(0, lambda k=key: self.choose(k))
                    return

    def highlight(self, selected):
        for (key, _), material in zip(self.nodes, self.materials):
            material.diffuseColor = (1, 0.65, 0.15) if key in selected else (0.2, 0.55, 0.95)
            material.transparency = 0.35 if key in selected else 0.75

    pick_at = PlanePicker.pick_at
    close = PlanePicker.close

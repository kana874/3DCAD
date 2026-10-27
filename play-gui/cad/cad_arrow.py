# SPDX-License-Identifier: LGPL-2.1-or-later
"""Interactive screen-space handle anchored to the extrusion axis."""
import math
from PySide6 import QtCore, QtGui, QtWidgets


class ExtrusionArrow(QtWidgets.QWidget):
    def __init__(self, owner, view, viewer):
        super().__init__(viewer)
        self.owner, self.view, self.viewer = owner, view, viewer
        self.setObjectName('CAD_ExtrudeArrow')
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setCursor(QtCore.Qt.SizeAllCursor)
        self.setToolTip('矢印をドラッグして押し出し距離を変更')
        self.resize(54, 54)
        self.origin = self.normal = None
        self.axis = (0.0, -1.0)
        self.scale = 1.0
        self.dragging = False
        self.show()
        self.raise_()

    def screen(self, point):
        px, py = self.view.getPointOnScreen(point)
        width, height = self.view.getSize()
        return (px * self.viewer.width() / max(width, 1),
                (height - 1 - py) * self.viewer.height() / max(height, 1))

    def set_axis(self, origin, normal):
        self.origin, self.normal = origin, normal
        self.reposition()

    def reposition(self):
        if self.origin is None or self.owner.session is None:
            return
        try:
            distance, _, reverse, symmetric, _ = self.owner.extrusion_values()
            sign = -1 if reverse else 1
            base = self.screen(self.origin)
            sample = self.screen(self.origin + self.normal * 10.0)
            dx, dy = sample[0] - base[0], sample[1] - base[1]
            magnitude = math.hypot(dx, dy)
            if magnitude < 2:
                self.axis, self.scale = (0.0, -1.0), 2.0
            else:
                self.axis, self.scale = (dx / magnitude, dy / magnitude), magnitude / 10.0
            offset = distance * (0.5 if symmetric else 1.0) * sign
            tip = self.screen(self.origin + self.normal * offset)
            x = max(0, min(self.viewer.width() - self.width(), tip[0] - self.width()/2))
            y = max(0, min(self.viewer.height() - self.height(), tip[1] - self.height()/2))
            self.move(round(x), round(y))
            self.update()
        except Exception:
            # An invalid partially typed distance should not interrupt editing.
            return

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        dx, dy = self.axis
        reverse = self.owner.fields['direction'].currentData() == 'reverse'
        sign = -1 if reverse else 1
        dx, dy = dx * sign, dy * sign
        center = QtCore.QPointF(self.width()/2, self.height()/2)
        start = center - QtCore.QPointF(dx * 17, dy * 17)
        tip = center + QtCore.QPointF(dx * 17, dy * 17)
        left = tip - QtCore.QPointF(dx * 12 - dy * 7, dy * 12 + dx * 7)
        right = tip - QtCore.QPointF(dx * 12 + dy * 7, dy * 12 - dx * 7)
        painter.setPen(QtGui.QPen(QtGui.QColor('#176fc2'), 4, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        painter.drawLine(start, tip)
        painter.setBrush(QtGui.QColor('#176fc2'))
        painter.drawPolygon(QtGui.QPolygonF([tip, left, right]))

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return super().mousePressEvent(event)
        try:
            distance, _, reverse, symmetric, _ = self.owner.extrusion_values()
        except Exception:
            return
        self.dragging = True
        self.drag_start = event.globalPosition()
        self.start_distance = distance * (-1 if reverse else 1)
        self.symmetric_drag = symmetric
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.dragging:
            return super().mouseMoveEvent(event)
        delta = event.globalPosition() - self.drag_start
        shift = (delta.x() * self.axis[0] + delta.y() * self.axis[1]) / max(self.scale, 0.01)
        if self.symmetric_drag:
            shift *= 2
        signed = self.start_distance + shift
        if not self.symmetric_drag:
            combo = self.owner.fields['direction']
            combo.setCurrentIndex(1 if signed < 0 else 0)
        value = min(100000, max(0.001, abs(signed)))
        self.owner.fields['distance'].setText('%.4f mm' % value)
        self.reposition()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.dragging and event.button() == QtCore.Qt.LeftButton:
            self.dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

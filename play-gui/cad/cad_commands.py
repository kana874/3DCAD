# SPDX-License-Identifier: LGPL-2.1-or-later
"""Named adapters to the commands actually shipped by the WASM build."""
SKETCH_TOOLS = [
 ('線', [('連続線／ポリライン', 'Sketcher_CreatePolyline'), ('単独線', 'Sketcher_CreateLine')]),
 ('四角形', [('2点矩形', 'Sketcher_CreateRectangle'), ('中心矩形', 'Sketcher_CreateRectangle_Center')]),
 ('円', [('中心円', 'Sketcher_CreateCircle'), ('3点円', 'Sketcher_Create3PointCircle')]),
 ('円弧', [('中心円弧', 'Sketcher_CreateArc'), ('3点円弧', 'Sketcher_Create3PointArc')]),
 ('楕円・円錐曲線', [('中心楕円', 'Sketcher_CreateEllipseByCenter'), ('3点楕円', 'Sketcher_CreateEllipseBy3Points'), ('楕円弧', 'Sketcher_CreateArcOfEllipse'), ('放物線弧', 'Sketcher_CreateArcOfParabola'), ('双曲線弧', 'Sketcher_CreateArcOfHyperbola')]),
 ('長穴', [('直線長穴', 'Sketcher_CreateSlot'), ('円弧長穴', 'Sketcher_CreateArcSlot'), ('長円', 'Sketcher_CreateOblong')]),
 ('多角形', [('正多角形', 'Sketcher_CreateRegularPolygon'), ('三角形', 'Sketcher_CreateTriangle'), ('正方形', 'Sketcher_CreateSquare'), ('五角形', 'Sketcher_CreatePentagon'), ('六角形', 'Sketcher_CreateHexagon'), ('七角形', 'Sketcher_CreateHeptagon'), ('八角形', 'Sketcher_CreateOctagon')]),
 ('スプライン・点', [('制御点スプライン', 'Sketcher_CreateBSpline'), ('補間スプライン', 'Sketcher_CreateBSplineByInterpolation'), ('閉スプライン', 'Sketcher_CreatePeriodicBSpline'), ('閉補間スプライン', 'Sketcher_CreatePeriodicBSplineByInterpolation'), ('点', 'Sketcher_CreatePoint')]),
]

from __future__ import annotations

from math import copysign, sqrt

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
)

from ..domain import LensElement, OpticalDesign, SurfaceSpec
from ..optics.optiland_adapter import FirstOrderAnalysis
from ..optics.paraxial import trace_parallel_rays


ROLE_KIND = 0
ROLE_ELEMENT = 1
ROLE_SURFACE = 2


class LensLayoutView(QGraphicsView):
    selectionRequested = Signal(str, int, int)
    insertionRequested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setBackgroundBrush(QColor("#f5f7f6"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._design: OpticalDesign | None = None
        self._analysis: FirstOrderAnalysis | None = None
        self._selected: tuple[str, int, int] | None = None
        self._fit_on_resize = True

    def set_design(self, design: OpticalDesign, analysis: FirstOrderAnalysis | None = None) -> None:
        self._design = design
        self._analysis = analysis
        self.rebuild()

    def set_selected(self, kind: str, element_index: int, surface_index: int = -1) -> None:
        self._selected = (kind, element_index, surface_index)
        self.rebuild()

    def rebuild(self) -> None:
        scene = self.scene()
        scene.clear()
        design = self._design
        if design is None or not design.elements:
            text = scene.addSimpleText("カタログからレンズを追加してください")
            text.setBrush(QColor("#56605d"))
            text.setPos(20, 20)
            return

        geometry, image_z = self._geometry(design)
        maximum_radius = max(element.outer_diameter_mm / 2 for element in design.elements)
        vertical_margin = max(12.0, maximum_radius * 0.8)
        scene.setSceneRect(QRectF(-8, -maximum_radius - vertical_margin, image_z + 16, 2 * (maximum_radius + vertical_margin)))

        grid_pen = QPen(QColor("#d9dfdc"), 0)
        grid_pen.setCosmetic(True)
        grid_step = 10.0
        x = 0.0
        while x <= image_z:
            scene.addLine(x, -maximum_radius - 4, x, maximum_radius + 4, grid_pen)
            x += grid_step
        axis_pen = QPen(QColor("#3c4642"), 0)
        axis_pen.setCosmetic(True)
        scene.addLine(-5, 0, image_z + 5, 0, axis_pen)

        self._draw_rays(design)
        colors = [QColor("#75b7c7"), QColor("#83b98c"), QColor("#d8ae62"), QColor("#9fa9d0")]
        for element_index, (element, surface_z) in enumerate(zip(design.elements, geometry, strict=True)):
            for region_index in range(len(element.surfaces) - 1):
                path = self._region_path(
                    surface_z[region_index],
                    element.surfaces[region_index],
                    surface_z[region_index + 1],
                    element.surfaces[region_index + 1],
                    element.outer_diameter_mm / 2,
                )
                item = QGraphicsPathItem(path)
                fill = colors[region_index % len(colors)]
                fill.setAlpha(150 if not element.is_catalog else 180)
                item.setBrush(fill)
                item.setPen(QPen(QColor("#314540"), 0))
                item.setData(ROLE_KIND, "element")
                item.setData(ROLE_ELEMENT, element_index)
                item.setData(ROLE_SURFACE, region_index)
                item.setToolTip(self._element_tooltip(element))
                scene.addItem(item)

            for surface_index, (surface, z) in enumerate(zip(element.surfaces, surface_z, strict=True)):
                path = self._surface_path(z, surface, element.outer_diameter_mm / 2)
                surface_item = QGraphicsPathItem(path)
                selected = self._selected == ("surface", element_index, surface_index)
                surface_item.setPen(QPen(QColor("#d28b19" if selected else "#26322f"), 0 if not selected else 1.3))
                surface_item.setData(ROLE_KIND, "surface")
                surface_item.setData(ROLE_ELEMENT, element_index)
                surface_item.setData(ROLE_SURFACE, surface_index)
                radius_text = "Plane" if surface.is_plane else f"R {surface.radius_mm:.3f} mm"
                surface_item.setToolTip(f"Surface {surface_index + 1}\n{radius_text}\nCA {surface.clear_aperture_mm or 0:.2f} mm")
                scene.addItem(surface_item)

            selected_element = self._selected and self._selected[1] == element_index
            if selected_element:
                bounds = QRectF(
                    min(surface_z) - 0.8,
                    -element.outer_diameter_mm / 2 - 0.8,
                    max(surface_z) - min(surface_z) + 1.6,
                    element.outer_diameter_mm + 1.6,
                )
                highlight = scene.addRect(bounds, QPen(QColor("#d28b19"), 0, Qt.PenStyle.DashLine))
                highlight.setZValue(4)

            label = QGraphicsSimpleTextItem(element.part_number or f"L{element_index + 1}")
            label.setBrush(QColor("#26322f"))
            label.setScale(0.18)
            label.setPos(surface_z[0], -element.outer_diameter_mm / 2 - 4.2)
            scene.addItem(label)

            gap_start = surface_z[-1]
            gap_end = gap_start + element.gap_after_mm
            gap_rect = QGraphicsRectItem(QRectF(gap_start, -maximum_radius, max(gap_end - gap_start, 0.2), 2 * maximum_radius))
            gap_rect.setPen(QPen(Qt.PenStyle.NoPen))
            gap_rect.setBrush(QColor(0, 0, 0, 1))
            gap_rect.setData(ROLE_KIND, "gap")
            gap_rect.setData(ROLE_ELEMENT, element_index)
            gap_rect.setData(ROLE_SURFACE, -1)
            gap_rect.setToolTip(f"Air gap {element.gap_after_mm:.3f} mm\nRight-click to insert")
            scene.addItem(gap_rect)

            if element_index == design.stop_after_element:
                stop_pen = QPen(QColor("#b3423f"), 0)
                stop_pen.setCosmetic(True)
                stop_height = min(maximum_radius + 3, element.outer_diameter_mm / 2 + 4)
                scene.addLine(gap_start, -stop_height, gap_start, -element.outer_diameter_mm / 2, stop_pen)
                scene.addLine(gap_start, element.outer_diameter_mm / 2, gap_start, stop_height, stop_pen)

        image_pen = QPen(QColor("#276b62"), 0.8)
        image_pen.setCosmetic(True)
        scene.addLine(image_z, -design.settings.sensor_height_mm / 2, image_z, design.settings.sensor_height_mm / 2, image_pen)
        image_label = QGraphicsSimpleTextItem("IMAGE")
        image_label.setBrush(QColor("#276b62"))
        image_label.setScale(0.2)
        image_label.setPos(image_z - 2.0, -design.settings.sensor_height_mm / 2 - 4.5)
        scene.addItem(image_label)
        self._draw_back_focus_dimension(design, geometry[-1][-1], image_z, maximum_radius + 7)

        if self._fit_on_resize:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_rays(self, design: OpticalDesign) -> None:
        if self._analysis is None or not self._analysis.valid:
            return
        ray_colors = ["#b3423f", "#d28b19", "#276b62", "#386fa4", "#7a4d8b"]
        for color, ray in zip(ray_colors, trace_parallel_rays(design, self._analysis.refractive_indices), strict=False):
            if len(ray) < 2:
                continue
            path = QPainterPath(QPointF(ray[0].z_mm, ray[0].y_mm))
            for point in ray[1:]:
                path.lineTo(point.z_mm, point.y_mm)
            item = QGraphicsPathItem(path)
            pen = QPen(QColor(color), 0)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setZValue(3)
            self.scene().addItem(item)

    def _draw_back_focus_dimension(self, design: OpticalDesign, start: float, end: float, y: float) -> None:
        pen = QPen(QColor("#59625f"), 0)
        pen.setCosmetic(True)
        self.scene().addLine(start, y, end, y, pen)
        self.scene().addLine(start, y - 1, start, y + 1, pen)
        self.scene().addLine(end, y - 1, end, y + 1, pen)
        label = QGraphicsSimpleTextItem(f"BFL {design.elements[-1].gap_after_mm:.2f} mm")
        label.setBrush(QColor("#59625f"))
        label.setScale(0.17)
        label.setPos((start + end) / 2 - 8, y + 0.8)
        self.scene().addItem(label)

    @staticmethod
    def _geometry(design: OpticalDesign) -> tuple[list[list[float]], float]:
        z = 0.0
        geometry: list[list[float]] = []
        for element in design.elements:
            positions: list[float] = []
            for surface_index, surface in enumerate(element.surfaces):
                positions.append(z)
                if surface_index < len(element.surfaces) - 1:
                    z += surface.thickness_after_mm
            geometry.append(positions)
            z += element.gap_after_mm
        return geometry, z

    @classmethod
    def _region_path(
        cls,
        front_z: float,
        front: SurfaceSpec,
        back_z: float,
        back: SurfaceSpec,
        half_diameter: float,
    ) -> QPainterPath:
        front_points = cls._surface_points(front_z, front, half_diameter)
        back_points = cls._surface_points(back_z, back, half_diameter)
        path = QPainterPath(front_points[0])
        for point in front_points[1:]:
            path.lineTo(point)
        for point in reversed(back_points):
            path.lineTo(point)
        path.closeSubpath()
        return path

    @classmethod
    def _surface_path(cls, z: float, surface: SurfaceSpec, half_diameter: float) -> QPainterPath:
        points = cls._surface_points(z, surface, half_diameter)
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        return path

    @staticmethod
    def _surface_points(z: float, surface: SurfaceSpec, half_diameter: float) -> list[QPointF]:
        points: list[QPointF] = []
        usable_radius = half_diameter
        if not surface.is_plane:
            usable_radius = min(usable_radius, abs(float(surface.radius_mm)) * 0.97)
        for index in range(25):
            y = -usable_radius + 2 * usable_radius * index / 24
            if surface.is_plane:
                sag = 0.0
            else:
                radius = float(surface.radius_mm)
                sag = radius - copysign(sqrt(max(radius * radius - y * y, 0.0)), radius)
            points.append(QPointF(z + sag, y))
        return points

    @staticmethod
    def _element_tooltip(element: LensElement) -> str:
        identity = " / ".join(item for item in (element.manufacturer, element.part_number) if item)
        return f"{element.name}\n{identity}\nDiameter {element.outer_diameter_mm:.2f} mm"

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.data(ROLE_KIND):
                kind = str(item.data(ROLE_KIND))
                element = int(item.data(ROLE_ELEMENT))
                surface = int(item.data(ROLE_SURFACE))
                self.selectionRequested.emit(kind, element, surface)
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None or item.data(ROLE_KIND) != "gap":
            super().contextMenuEvent(event)
            return
        element_index = int(item.data(ROLE_ELEMENT))
        menu = QMenu(self)
        catalog_action = menu.addAction("選択中のカタログレンズを挿入")
        custom_action = menu.addAction("カスタムレンズを挿入")
        chosen = menu.exec(event.globalPos())
        if chosen is catalog_action:
            self.insertionRequested.emit("catalog", element_index + 1)
        elif chosen is custom_action:
            self.insertionRequested.emit("custom", element_index + 1)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._fit_on_resize = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_on_resize and self.scene().items():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def reset_view(self) -> None:
        self._fit_on_resize = True
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

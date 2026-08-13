from __future__ import annotations

from math import floor, hypot, isfinite, sqrt

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QDoubleSpinBox,
    QMenu,
    QToolTip,
)

from ..domain import LensElement, OpticalDesign, SurfaceSpec
from ..optics.optiland_adapter import FirstOrderAnalysis


ROLE_KIND = 0
ROLE_ELEMENT = 1
ROLE_SURFACE = 2


class LensLayoutView(QGraphicsView):
    selectionRequested = Signal(str, int, int)
    insertionRequested = Signal(str, int)
    gapChangeRequested = Signal(int, float)
    elementActionRequested = Signal(str, int)
    surfaceActionRequested = Signal(str, int, int)
    imageEditRequested = Signal()

    def __init__(self, parent=None, editable: bool = True):
        super().__init__(parent)
        self._editable = editable
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
        self._gap_drag: tuple[int, float, float] | None = None
        self._gap_preview_value = 0.0
        self._context_menu: QMenu | None = None
        self._pending_gap_edit: tuple[int, float] | None = None
        self._gap_edit_timer = QTimer(self)
        self._gap_edit_timer.setSingleShot(True)
        self._gap_edit_timer.setInterval(250)
        self._gap_edit_timer.timeout.connect(self._flush_gap_edit)
        self._gap_spins: list[tuple[QDoubleSpinBox, QPointF]] = []
        self.horizontalScrollBar().valueChanged.connect(self._position_gap_spins)
        self.verticalScrollBar().valueChanged.connect(self._position_gap_spins)

    def set_design(self, design: OpticalDesign, analysis: FirstOrderAnalysis | None = None) -> None:
        self._design = design
        self._analysis = analysis
        self.rebuild()

    def set_selected(self, kind: str, element_index: int, surface_index: int = -1) -> None:
        self._selected = (kind, element_index, surface_index)
        self.rebuild()

    def rebuild(self) -> None:
        self._clear_gap_spins()
        scene = self.scene()
        scene.clear()
        design = self._design
        if design is None or not design.elements:
            text = scene.addSimpleText("カタログからレンズを追加してください")
            text.setBrush(QColor("#56605d"))
            text.setPos(20, 20)
            return

        geometry, image_z = self._geometry(design)
        last_surface_z = geometry[-1][-1]
        focus_z = self._paraxial_focus_z(last_surface_z)
        ray_min_z, ray_max_z, ray_radius = self._layout_ray_bounds()
        image_half_height = hypot(design.settings.sensor_width_mm, design.settings.sensor_height_mm) / 2.0
        base_radius = max(
            max(element.outer_diameter_mm / 2 for element in design.elements),
            image_half_height,
        )
        maximum_radius = max(base_radius, min(ray_radius, base_radius * 3.0))
        vertical_margin = max(12.0, maximum_radius * 0.8)
        scene_left = min(-14.0, ray_min_z - 3.0, focus_z - 8.0 if focus_z is not None else -14.0)
        scene_right = max(
            image_z + 24.0,
            ray_max_z + 12.0,
            focus_z + 16.0 if focus_z is not None else image_z + 24.0,
        )
        scene.setSceneRect(
            QRectF(
                scene_left,
                -maximum_radius - vertical_margin,
                scene_right - scene_left,
                2 * (maximum_radius + vertical_margin),
            )
        )

        grid_pen = QPen(QColor("#d9dfdc"), 0)
        grid_pen.setCosmetic(True)
        grid_step = 10.0
        x = floor(scene_left / grid_step) * grid_step
        while x <= scene_right:
            scene.addLine(x, -maximum_radius - 4, x, maximum_radius + 4, grid_pen)
            x += grid_step
        axis_pen = QPen(QColor("#3c4642"), 0)
        axis_pen.setCosmetic(True)
        scene.addLine(scene_left + 3, 0, scene_right - 3, 0, axis_pen)

        if self._editable:
            self._draw_front_insertion(geometry[0][0], maximum_radius)
        self._draw_rays(design, focus_z, last_surface_z, image_z)
        colors = [QColor("#75b7c7"), QColor("#83b98c"), QColor("#d8ae62"), QColor("#9fa9d0")]
        for element_index, (element, surface_z) in enumerate(zip(design.elements, geometry, strict=True)):
            for region_index in range(len(element.surfaces) - 1):
                if element.surfaces[region_index].material_after.strip().lower() == "air":
                    continue
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
                item.setZValue(1)
                item.setCursor(Qt.CursorShape.PointingHandCursor)
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
                type_text = "Even asphere" if surface.surface_type == "even_asphere" else "Standard"
                surface_item.setToolTip(
                    f"Surface {surface_index + 1}\n{type_text} / {radius_text} / K {surface.conic:g}\n"
                    f"CA {surface.clear_aperture_mm or 0:.2f} mm"
                )
                surface_item.setZValue(4)
                scene.addItem(surface_item)

                hit_item = QGraphicsPathItem(path)
                hit_pen = QPen(QColor(0, 0, 0, 1), 1.6)
                hit_item.setPen(hit_pen)
                hit_item.setData(ROLE_KIND, "surface")
                hit_item.setData(ROLE_ELEMENT, element_index)
                hit_item.setData(ROLE_SURFACE, surface_index)
                hit_item.setToolTip(surface_item.toolTip())
                hit_item.setCursor(Qt.CursorShape.PointingHandCursor)
                hit_item.setZValue(7)
                scene.addItem(hit_item)

                stop_surface_index = design.stop_surface_index
                if stop_surface_index is None or not 0 <= stop_surface_index < len(element.surfaces):
                    stop_surface_index = len(element.surfaces) - 1
                if element_index == design.stop_after_element and surface_index == stop_surface_index:
                    stop_pen = QPen(QColor("#b3423f"), 0)
                    stop_pen.setCosmetic(True)
                    stop_height = min(maximum_radius + 3, element.outer_diameter_mm / 2 + 4)
                    scene.addLine(z, -stop_height, z, -element.outer_diameter_mm / 2, stop_pen)
                    scene.addLine(z, element.outer_diameter_mm / 2, z, stop_height, stop_pen)

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
            label.setData(ROLE_KIND, "element")
            label.setData(ROLE_ELEMENT, element_index)
            label.setData(ROLE_SURFACE, -1)
            label.setToolTip(self._element_tooltip(element))
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setZValue(5)
            scene.addItem(label)

            gap_start = surface_z[-1]
            gap_end = gap_start + element.gap_after_mm
            gap_rect = QGraphicsRectItem(QRectF(gap_start, -maximum_radius, max(gap_end - gap_start, 0.8), 2 * maximum_radius))
            selected_gap = self._selected == ("gap", element_index, -1)
            gap_rect.setPen(QPen(QColor("#d28b19"), 0, Qt.PenStyle.DashLine) if selected_gap else QPen(Qt.PenStyle.NoPen))
            gap_rect.setBrush(QColor(210, 139, 25, 28) if selected_gap else QColor(0, 0, 0, 1))
            gap_rect.setData(ROLE_KIND, "gap")
            gap_rect.setData(ROLE_ELEMENT, element_index)
            gap_rect.setData(ROLE_SURFACE, -1)
            lock_text = " (固定中)" if element.gap_locked else ""
            gap_rect.setToolTip(f"空気間隔 {element.gap_after_mm:.3f} mm{lock_text}\n横ドラッグで変更 / 右クリックで挿入")
            gap_rect.setCursor(Qt.CursorShape.SizeHorCursor)
            gap_rect.setZValue(0)
            scene.addItem(gap_rect)
            if element_index < len(design.elements) - 1:
                dimension_y = maximum_radius + 2.5 + (element_index % 2) * 3.0
                self._draw_gap_dimension(element_index, gap_start, gap_end, dimension_y)

        image_pen = QPen(QColor("#276b62"), 0.8)
        image_pen.setCosmetic(True)
        image_item = scene.addLine(
            image_z,
            -image_half_height,
            image_z,
            image_half_height,
            image_pen,
        )
        image_item.setData(ROLE_KIND, "image")
        image_item.setData(ROLE_ELEMENT, -1)
        image_item.setData(ROLE_SURFACE, -1)
        image_item.setToolTip(
            f"像面 {design.settings.sensor_width_mm:.2f} x {design.settings.sensor_height_mm:.2f} mm\n"
            "クリックして像面・光線条件を編集"
        )
        image_item.setCursor(Qt.CursorShape.PointingHandCursor)
        image_item.setZValue(8)
        image_hit = QGraphicsRectItem(
            QRectF(image_z - 1.2, -image_half_height - 1.2, 2.4, 2 * image_half_height + 2.4)
        )
        image_hit.setPen(QPen(Qt.PenStyle.NoPen))
        image_hit.setBrush(QColor(0, 0, 0, 1))
        image_hit.setData(ROLE_KIND, "image")
        image_hit.setData(ROLE_ELEMENT, -1)
        image_hit.setData(ROLE_SURFACE, -1)
        image_hit.setToolTip(image_item.toolTip())
        image_hit.setCursor(Qt.CursorShape.PointingHandCursor)
        image_hit.setZValue(7)
        scene.addItem(image_hit)
        image_label = QGraphicsSimpleTextItem("IMAGE")
        image_label.setBrush(QColor("#276b62"))
        image_label.setScale(0.2)
        image_label.setPos(image_z - 2.0, -image_half_height - 4.5)
        image_label.setData(ROLE_KIND, "image")
        image_label.setData(ROLE_ELEMENT, -1)
        image_label.setData(ROLE_SURFACE, -1)
        image_label.setToolTip(image_item.toolTip())
        image_label.setCursor(Qt.CursorShape.PointingHandCursor)
        image_label.setZValue(8)
        scene.addItem(image_label)
        if focus_z is not None:
            self._draw_focus_marker(focus_z, maximum_radius)
        self._draw_back_focus_dimension(design, geometry[-1][-1], image_z, maximum_radius + 7)

        if self._fit_on_resize:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._position_gap_spins()

    def _draw_rays(
        self,
        design: OpticalDesign,
        focus_z: float | None,
        last_surface_z: float,
        image_z: float,
    ) -> None:
        if self._analysis is None:
            self._draw_ray_status("光線未解析")
            return
        if not self._analysis.valid:
            status = "光線解析待ち" if self._analysis.error == "解析待ち" else "光線解析失敗"
            self._draw_ray_status(status, error=status == "光線解析失敗")
            return
        ray_colors = ["#c93f3f", "#2a8f55", "#356fc3", "#c044b5", "#d18a22"]
        rays = self._analysis.layout_rays
        if not rays:
            self._draw_ray_status("実光線データなし", error=True)
            return
        for ray in rays:
            points = ray.get("points", [])
            if len(points) < 2:
                continue
            path = QPainterPath(QPointF(float(points[0]["z_mm"]), float(points[0]["y_mm"])))
            for point in points[1:]:
                path.lineTo(float(point["z_mm"]), float(point["y_mm"]))
            item = QGraphicsPathItem(path)
            field_index = int(ray.get("field_index", 0))
            pen = QPen(QColor(ray_colors[field_index % len(ray_colors)]), 0)
            pen.setCosmetic(True)
            pen.setColor(QColor(pen.color().red(), pen.color().green(), pen.color().blue(), 155))
            item.setPen(pen)
            item.setToolTip(
                f"逐次実光線 / 画角 {float(ray.get('field_angle_deg', 0.0)):.3f}° / "
                f"瞳 {float(ray.get('pupil_fraction', 0.0)):+.2f} / "
                f"波長 {float(ray.get('wavelength_um', 0.0)) * 1000.0:.1f} nm"
            )
            item.setZValue(3)
            self.scene().addItem(item)

            if focus_z is None or field_index != 0 or len(points) < 3:
                continue
            previous = points[-2]
            image = points[-1]
            previous_z = float(previous["z_mm"])
            previous_y = float(previous["y_mm"])
            image_point_z = float(image["z_mm"])
            image_y = float(image["y_mm"])
            dz = image_point_z - previous_z
            if abs(dz) < 1e-12:
                continue
            if focus_z < last_surface_z - 1e-6:
                guide_start_z, guide_start_y = previous_z, previous_y
            elif focus_z > image_z + 1e-6:
                guide_start_z, guide_start_y = image_point_z, image_y
            else:
                continue
            focus_y = previous_y + (image_y - previous_y) * (focus_z - previous_z) / dz
            guide = self.scene().addLine(
                guide_start_z,
                guide_start_y,
                focus_z,
                focus_y,
                QPen(QColor(178, 117, 34, 145), 0, Qt.PenStyle.DashLine),
            )
            guide.setZValue(2)

    def _paraxial_focus_z(self, last_surface_z: float) -> float | None:
        if self._analysis is None or not self._analysis.valid:
            return None
        distance = self._analysis.paraxial_focus_distance_mm
        if distance is None or not isfinite(distance):
            return None
        return last_surface_z + distance

    def _draw_focus_marker(self, focus_z: float, maximum_radius: float) -> None:
        if self._analysis is None or self._analysis.paraxial_focus_distance_mm is None:
            return
        virtual = self._analysis.paraxial_focus_distance_mm <= 0
        color = QColor("#b27522" if virtual else "#276b62")
        pen = QPen(color, 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        marker = self.scene().addLine(focus_z, -maximum_radius - 2, focus_z, maximum_radius + 2, pen)
        marker.setToolTip(
            f"{'虚焦点' if virtual else '近軸焦点'}: 最終面から "
            f"{self._analysis.paraxial_focus_distance_mm:.3f} mm"
        )
        marker.setZValue(2)
        label = QGraphicsSimpleTextItem("PARAXIAL VIRTUAL FOCUS" if virtual else "PARAXIAL FOCUS")
        label.setBrush(color)
        label.setScale(0.18)
        label.setPos(focus_z + 0.8, maximum_radius + 2.5)
        label.setToolTip(marker.toolTip())
        label.setZValue(5)
        self.scene().addItem(label)

    def _draw_ray_status(self, message: str, error: bool = False) -> None:
        label = QGraphicsSimpleTextItem(message)
        label.setBrush(QColor("#a13d3a" if error else "#68736f"))
        label.setScale(0.2)
        bounds = self.scene().sceneRect()
        label.setPos(bounds.left() + 3, bounds.top() + 3)
        label.setZValue(10)
        self.scene().addItem(label)

    def _layout_ray_bounds(self) -> tuple[float, float, float]:
        if self._analysis is None or not self._analysis.layout_rays:
            return -14.0, 0.0, 0.0
        z_values: list[float] = []
        y_values: list[float] = []
        for ray in self._analysis.layout_rays:
            for point in ray.get("points", []):
                z = float(point.get("z_mm", 0.0))
                y = float(point.get("y_mm", 0.0))
                if isfinite(z) and isfinite(y):
                    z_values.append(z)
                    y_values.append(abs(y))
        if not z_values:
            return -14.0, 0.0, 0.0
        return min(z_values), max(z_values), max(y_values, default=0.0)

    def _draw_back_focus_dimension(self, design: OpticalDesign, start: float, end: float, y: float) -> None:
        pen = QPen(QColor("#59625f"), 0)
        pen.setCosmetic(True)
        self.scene().addLine(start, y, end, y, pen)
        self.scene().addLine(start, y - 1, start, y + 1, pen)
        self.scene().addLine(end, y - 1, end, y + 1, pen)
        if self._editable:
            self._add_gap_spin(
                len(design.elements) - 1,
                start,
                end,
                y,
                prefix="BFL ",
            )
        else:
            self._add_dimension_label(f"BFL {design.elements[-1].gap_after_mm:.2f}", start, end, y)

    def _draw_gap_dimension(self, element_index: int, start: float, end: float, y: float) -> None:
        selected = self._selected == ("gap", element_index, -1)
        color = QColor("#d28b19" if selected else "#77817d")
        pen = QPen(color, 0)
        pen.setCosmetic(True)
        for line in (
            self.scene().addLine(start, y, end, y, pen),
            self.scene().addLine(start, y - 0.8, start, y + 0.8, pen),
            self.scene().addLine(end, y - 0.8, end, y + 0.8, pen),
        ):
            line.setZValue(2)
        if self._editable:
            self._add_gap_spin(element_index, start, end, y)
        elif self._design is not None:
            self._add_dimension_label(f"{self._design.elements[element_index].gap_after_mm:.2f}", start, end, y)
        hit_item = QGraphicsRectItem(QRectF(start, y - 1.5, max(end - start, 0.8), 3.0))
        hit_item.setPen(QPen(Qt.PenStyle.NoPen))
        hit_item.setBrush(QColor(0, 0, 0, 1))
        hit_item.setData(ROLE_KIND, "gap")
        hit_item.setData(ROLE_ELEMENT, element_index)
        hit_item.setData(ROLE_SURFACE, -1)
        hit_item.setToolTip("横ドラッグでレンズ間隔を変更")
        hit_item.setCursor(Qt.CursorShape.SizeHorCursor)
        hit_item.setZValue(6)
        self.scene().addItem(hit_item)

    def _add_dimension_label(self, text: str, start: float, end: float, y: float) -> None:
        label = QGraphicsSimpleTextItem(text)
        label.setBrush(QColor("#59625f"))
        label.setScale(0.16)
        label.setPos((start + end) / 2.0 - max(len(text), 3) * 0.35, y - 1.2)
        label.setZValue(5)
        self.scene().addItem(label)

    def _draw_front_insertion(self, first_surface_z: float, maximum_radius: float) -> None:
        rect = QGraphicsRectItem(QRectF(first_surface_z - 8.0, -maximum_radius, 6.0, 2 * maximum_radius))
        rect.setPen(QPen(QColor("#7a8581"), 0, Qt.PenStyle.DashLine))
        rect.setBrush(QColor(255, 255, 255, 150))
        rect.setData(ROLE_KIND, "front_gap")
        rect.setData(ROLE_ELEMENT, -1)
        rect.setData(ROLE_SURFACE, -1)
        rect.setToolTip("L1の物体側へレンズを挿入（右クリック）")
        rect.setCursor(Qt.CursorShape.PointingHandCursor)
        rect.setZValue(6)
        self.scene().addItem(rect)

        plus = QGraphicsSimpleTextItem("+")
        plus.setBrush(QColor("#276b62"))
        plus.setScale(0.55)
        plus.setPos(first_surface_z - 6.5, -2.7)
        plus.setData(ROLE_KIND, "front_gap")
        plus.setData(ROLE_ELEMENT, -1)
        plus.setData(ROLE_SURFACE, -1)
        plus.setToolTip(rect.toolTip())
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.setZValue(7)
        self.scene().addItem(plus)

    def _add_gap_spin(self, element_index: int, start: float, end: float, y: float, prefix: str = "") -> None:
        if self._design is None:
            return
        element = self._design.elements[element_index]
        spin = QDoubleSpinBox(self.viewport())
        spin.setObjectName(f"layoutGapSpin{element_index}")
        spin.setDecimals(3)
        spin.setRange(element.gap_min_mm, element.gap_max_mm or 10000.0)
        spin.setSingleStep(0.1)
        spin.setAccelerated(True)
        spin.setKeyboardTracking(False)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setSuffix(" mm")
        spin.setPrefix(prefix)
        spin.setValue(element.gap_after_mm)
        spin.setEnabled(not element.gap_locked)
        spin.setFixedSize(110 if prefix else 92, 24)
        spin.setToolTip("空気間隔を直接入力。上下ボタンで0.1 mmずつ調整")
        spin.valueChanged.connect(lambda value, index=element_index: self._queue_gap_edit(index, value))
        spin.editingFinished.connect(self._flush_gap_edit_soon)

        self._gap_spins.append((spin, QPointF((start + end) / 2, y + 0.7)))
        spin.show()

    def _clear_gap_spins(self) -> None:
        for spin, _ in self._gap_spins:
            spin.blockSignals(True)
            spin.hide()
            spin.deleteLater()
        self._gap_spins.clear()

    def _position_gap_spins(self) -> None:
        viewport_rect = self.viewport().rect()
        visible_bounds = viewport_rect.adjusted(-120, -30, 120, 30)
        for spin, scene_position in self._gap_spins:
            position = self.mapFromScene(scene_position)
            spin.move(position.x() - spin.width() // 2, position.y())
            spin.setVisible(visible_bounds.contains(position))

    def _queue_gap_edit(self, element_index: int, value: float) -> None:
        self._pending_gap_edit = (element_index, value)
        self._gap_edit_timer.start()

    def _flush_gap_edit_soon(self) -> None:
        self._gap_edit_timer.stop()
        QTimer.singleShot(0, self._flush_gap_edit)

    def _flush_gap_edit(self) -> None:
        pending = self._pending_gap_edit
        self._pending_gap_edit = None
        if pending is None or self._design is None:
            return
        element_index, value = pending
        if not 0 <= element_index < len(self._design.elements):
            return
        if abs(self._design.elements[element_index].gap_after_mm - value) <= 1e-9:
            return
        self.gapChangeRequested.emit(element_index, value)

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
            radius = float(surface.radius_mm)
            if 1 + surface.conic > 0:
                usable_radius = min(usable_radius, abs(radius) / sqrt(1 + surface.conic) * 0.97)
        for index in range(25):
            y = -usable_radius + 2 * usable_radius * index / 24
            if surface.is_plane:
                sag = 0.0
            else:
                radius = float(surface.radius_mm)
                radial_square = y * y
                root = sqrt(max(1 - (1 + surface.conic) * radial_square / (radius * radius), 0.0))
                denominator = radius * (1 + root)
                sag = radial_square / denominator if denominator else 0.0
                if surface.surface_type == "even_asphere":
                    for coefficient_index, coefficient in enumerate(surface.asphere_coefficients):
                        sag += coefficient * radial_square ** (coefficient_index + 1)
                if not isfinite(sag):
                    sag = 0.0
            points.append(QPointF(z + sag, y))
        return points

    @staticmethod
    def _element_tooltip(element: LensElement) -> str:
        identity = " / ".join(item for item in (element.manufacturer, element.part_number) if item)
        return f"{element.name}\n{identity}\nDiameter {element.outer_diameter_mm:.2f} mm"

    def mousePressEvent(self, event) -> None:
        if not self._editable:
            QGraphicsView.mousePressEvent(self, event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            item = self._interactive_item_at(event.position().toPoint())
            if item is not None:
                kind = str(item.data(ROLE_KIND))
                element = int(item.data(ROLE_ELEMENT))
                surface = int(item.data(ROLE_SURFACE))
                if kind == "front_gap":
                    self._show_front_insertion_menu(event.globalPosition().toPoint())
                    event.accept()
                    return
                if kind == "image":
                    self.imageEditRequested.emit()
                    event.accept()
                    return
                self.selectionRequested.emit(kind, element, surface)
                if kind == "gap" and self._design is not None and not self._design.elements[element].gap_locked:
                    self._gap_drag = (element, self._design.elements[element].gap_after_mm, self.mapToScene(event.position().toPoint()).x())
                    self._gap_preview_value = self._design.elements[element].gap_after_mm
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._editable:
            QGraphicsView.mouseMoveEvent(self, event)
            return
        if self._gap_drag is not None and self._design is not None:
            element_index, initial_value, start_x = self._gap_drag
            element = self._design.elements[element_index]
            value = initial_value + self.mapToScene(event.position().toPoint()).x() - start_x
            value = max(element.gap_min_mm, value)
            if element.gap_max_mm is not None:
                value = min(element.gap_max_mm, value)
            self._gap_preview_value = value
            QToolTip.showText(event.globalPosition().toPoint(), f"間隔 {value:.3f} mm", self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self._editable:
            QGraphicsView.mouseReleaseEvent(self, event)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._gap_drag is not None:
            element_index, initial_value, _ = self._gap_drag
            value = self._gap_preview_value
            self._gap_drag = None
            if abs(value - initial_value) > 1e-6:
                self.gapChangeRequested.emit(element_index, value)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        if not self._editable:
            event.ignore()
            return
        item = self._interactive_item_at(event.pos())
        if item is None:
            super().contextMenuEvent(event)
            return
        kind = str(item.data(ROLE_KIND))
        element_index = int(item.data(ROLE_ELEMENT))
        surface_index = int(item.data(ROLE_SURFACE))
        if kind == "front_gap":
            self._show_front_insertion_menu(event.globalPos())
            return

        if kind == "image":
            menu = QMenu(self)
            edit_action = menu.addAction("像面・光線条件を編集")
            edit_action.triggered.connect(self.imageEditRequested)
            self._show_context_menu(menu, event.globalPos())
            return

        menu = QMenu(self)
        self.selectionRequested.emit(kind, element_index, surface_index)
        if kind == "gap":
            zero_action = menu.addAction("接触 (0 mm)")
            lock_action = menu.addAction("間隔固定を切替")
            stop_action = menu.addAction("ここを絞り位置にする")
            menu.addSeparator()
            catalog_action = menu.addAction("選択中のカタログレンズを挿入")
            custom_action = menu.addAction("カスタムレンズを挿入")
            zero_action.triggered.connect(lambda: self.surfaceActionRequested.emit("gap_zero", element_index, -1))
            lock_action.triggered.connect(lambda: self.surfaceActionRequested.emit("gap_toggle_lock", element_index, -1))
            stop_action.triggered.connect(lambda: self.surfaceActionRequested.emit("set_stop", element_index, -1))
            catalog_action.triggered.connect(lambda: self.insertionRequested.emit("catalog", element_index + 1))
            custom_action.triggered.connect(lambda: self.insertionRequested.emit("custom", element_index + 1))
            self._show_context_menu(menu, event.globalPos())
            return

        if kind == "surface":
            before_action = menu.addAction("面を前へ追加")
            after_action = menu.addAction("面を後へ追加")
            duplicate_surface_action = menu.addAction("面を複製")
            delete_surface_action = menu.addAction("面を削除")
            menu.addSeparator()
            plane_action = menu.addAction("平面 / 球面を切替")
            lock_radius_action = menu.addAction("曲率固定を切替")
            before_action.triggered.connect(lambda: self.surfaceActionRequested.emit("surface_insert_before", element_index, surface_index))
            after_action.triggered.connect(lambda: self.surfaceActionRequested.emit("surface_insert_after", element_index, surface_index))
            duplicate_surface_action.triggered.connect(lambda: self.surfaceActionRequested.emit("surface_duplicate", element_index, surface_index))
            delete_surface_action.triggered.connect(lambda: self.surfaceActionRequested.emit("surface_delete", element_index, surface_index))
            plane_action.triggered.connect(lambda: self.surfaceActionRequested.emit("surface_toggle_plane", element_index, surface_index))
            lock_radius_action.triggered.connect(lambda: self.surfaceActionRequested.emit("surface_toggle_radius_lock", element_index, surface_index))
            menu.addSeparator()

        duplicate_action = menu.addAction("レンズを複製")
        reverse_action = menu.addAction("レンズを反転")
        stop_action = menu.addAction("この面を絞り位置にする" if kind == "surface" else "後方を絞り位置にする")
        customize_action = None
        if self._design is not None and self._design.elements[element_index].is_catalog:
            customize_action = menu.addAction("カスタム化")
        menu.addSeparator()
        insert_before_action = menu.addAction("カスタムレンズを前へ挿入")
        insert_after_action = menu.addAction("カスタムレンズを後へ挿入")
        menu.addSeparator()
        delete_action = menu.addAction("レンズを削除")
        duplicate_action.triggered.connect(lambda: self.surfaceActionRequested.emit("element_duplicate", element_index, surface_index))
        reverse_action.triggered.connect(lambda: self.elementActionRequested.emit("reverse", element_index))
        stop_target = surface_index if kind == "surface" else -1
        stop_action.triggered.connect(lambda: self.surfaceActionRequested.emit("set_stop", element_index, stop_target))
        if customize_action is not None:
            customize_action.triggered.connect(lambda: self.elementActionRequested.emit("customize", element_index))
        insert_before_action.triggered.connect(lambda: self.insertionRequested.emit("custom", element_index))
        insert_after_action.triggered.connect(lambda: self.insertionRequested.emit("custom", element_index + 1))
        delete_action.triggered.connect(lambda: self.elementActionRequested.emit("delete", element_index))
        self._show_context_menu(menu, event.globalPos())

    def _show_front_insertion_menu(self, global_position) -> None:
        menu = QMenu(self)
        catalog_action = menu.addAction("選択中のカタログレンズをL1の前へ挿入")
        custom_action = menu.addAction("カスタムレンズをL1の前へ挿入")
        catalog_action.triggered.connect(lambda: self.insertionRequested.emit("catalog", 0))
        custom_action.triggered.connect(lambda: self.insertionRequested.emit("custom", 0))
        self._show_context_menu(menu, global_position)

    def _show_context_menu(self, menu: QMenu, global_position) -> None:
        if self._context_menu is not None:
            previous_menu = self._context_menu
            self._context_menu = None
            previous_menu.close()
            previous_menu.deleteLater()
        self._context_menu = menu
        menu.aboutToHide.connect(lambda current=menu: self._context_menu_closed(current))
        menu.popup(global_position)

    def _context_menu_closed(self, menu: QMenu) -> None:
        if self._context_menu is menu:
            self._context_menu = None
        menu.deleteLater()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete and self._selected is not None and self._selected[0] in {"element", "surface"}:
            self.elementActionRequested.emit("delete", self._selected[1])
            event.accept()
            return
        super().keyPressEvent(event)

    def _interactive_item_at(self, position):
        items_here = self.items(position)
        for item in items_here:
            if item.data(ROLE_KIND) == "image":
                return item
        if self.mapToScene(position).x() < -0.5:
            for item in items_here:
                if item.data(ROLE_KIND) == "front_gap":
                    return item
        for item in items_here:
            if item.data(ROLE_KIND) == "gap" and item.zValue() >= 5:
                return item
        for item in items_here:
            if item.data(ROLE_KIND) == "element" and item.zValue() >= 5:
                return item

        nearest_surface = None
        nearest_distance = float("inf")
        for item in self.scene().items():
            if item.data(ROLE_KIND) != "surface" or item.zValue() != 7 or not isinstance(item, QGraphicsPathItem):
                continue
            distance = self._path_distance_in_view(item, position)
            if distance < nearest_distance:
                nearest_surface = item
                nearest_distance = distance
        if nearest_surface is not None and nearest_distance <= 7.0:
            return nearest_surface

        for item in items_here:
            if item.data(ROLE_KIND) == "element":
                return item
        for item in items_here:
            if item.data(ROLE_KIND) == "gap":
                return item
        return None

    def _path_distance_in_view(self, item: QGraphicsPathItem, position) -> float:
        shortest = float("inf")
        for polygon in item.path().toSubpathPolygons():
            points = [self.mapFromScene(item.mapToScene(point)) for point in polygon]
            for start, end in zip(points, points[1:]):
                dx = end.x() - start.x()
                dy = end.y() - start.y()
                if dx == 0 and dy == 0:
                    distance = hypot(position.x() - start.x(), position.y() - start.y())
                else:
                    ratio = ((position.x() - start.x()) * dx + (position.y() - start.y()) * dy) / (dx * dx + dy * dy)
                    ratio = min(max(ratio, 0.0), 1.0)
                    closest_x = start.x() + ratio * dx
                    closest_y = start.y() + ratio * dy
                    distance = hypot(position.x() - closest_x, position.y() - closest_y)
                shortest = min(shortest, distance)
        return shortest

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._fit_on_resize = False
        self._position_gap_spins()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_on_resize and self.scene().items():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._position_gap_spins()

    def reset_view(self) -> None:
        self._fit_on_resize = True
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._position_gap_spins()

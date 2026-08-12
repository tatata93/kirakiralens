from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..catalog.database import CatalogProduct, CatalogRepository
from ..domain import LensElement, OpticalDesign, SurfaceSpec
from ..optics.optiland_adapter import FirstOrderAnalysis


SHAPE_LABELS = {
    "plano_convex": "平凸",
    "plano_concave": "平凹",
    "double_convex": "両凸",
    "double_concave": "両凹",
    "achromatic_doublet": "色消し接合",
    "custom": "カスタム",
}


def spin_box(minimum: float, maximum: float, decimals: int = 3, suffix: str = " mm") -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    return widget


class CatalogPanel(QWidget):
    productActivated = Signal(int)
    selectionChanged = Signal(int)

    def __init__(self, repository: CatalogRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self._products: list[CatalogProduct] = []
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(180)
        self._refresh_timer.timeout.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        filters = QGridLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("型番・名称")
        self.shape = QComboBox()
        self.shape.addItem("全形状", "")
        for value in repository.filter_values("shape"):
            self.shape.addItem(SHAPE_LABELS.get(value, value), value)
        self.material = QComboBox()
        self.material.addItem("全硝材", "")
        for value in repository.filter_values("material"):
            self.material.addItem(value, value)
        self.max_diameter = spin_box(0, 500, 1)
        self.max_diameter.setSpecialValueText("径制限なし")
        self.max_diameter.setValue(50)
        self.include_incomplete = QCheckBox("不完全データも表示")
        filters.addWidget(self.search, 0, 0, 1, 2)
        filters.addWidget(self.shape, 1, 0)
        filters.addWidget(self.material, 1, 1)
        filters.addWidget(self.max_diameter, 2, 0, 1, 2)
        filters.addWidget(self.include_incomplete, 3, 0, 1, 2)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["型番", "形状", "径", "EFL", "硝材"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.add_button = QPushButton("設計へ追加")
        self.add_button.setEnabled(False)
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        footer.addWidget(self.add_button)
        layout.addLayout(footer)

        for widget in (self.search, self.shape, self.material, self.max_diameter, self.include_incomplete):
            signal = getattr(widget, "textChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled")
            signal.connect(lambda *_: self._refresh_timer.start())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.activate_selected())
        self.add_button.clicked.connect(self.activate_selected)
        self.refresh()

    def refresh(self) -> None:
        max_diameter = self.max_diameter.value() or None
        self._products = self.repository.query_products(
            search=self.search.text().strip(),
            shape=str(self.shape.currentData() or ""),
            material=str(self.material.currentData() or ""),
            max_diameter_mm=max_diameter,
            designable_only=not self.include_incomplete.isChecked(),
            limit=500,
        )
        self.table.setRowCount(len(self._products))
        for row, product in enumerate(self._products):
            values = [
                product.part_number,
                SHAPE_LABELS.get(product.shape, product.shape),
                "" if product.outer_diameter_mm is None else f"{product.outer_diameter_mm:g}",
                "" if product.effective_focal_length_mm is None else f"{product.effective_focal_length_mm:g}",
                product.materials,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        total = self.repository.count_products()
        suffix = "上限500件" if len(self._products) == 500 else f"全{total}件"
        self.count_label.setText(f"{len(self._products)}件 / {suffix}")
        self.add_button.setEnabled(False)

    def selected_product_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._products):
            return None
        return self._products[row].id

    def activate_selected(self) -> None:
        product_id = self.selected_product_id()
        if product_id is not None:
            self.productActivated.emit(product_id)

    def _selection_changed(self) -> None:
        product_id = self.selected_product_id()
        self.add_button.setEnabled(product_id is not None)
        if product_id is not None:
            self.selectionChanged.emit(product_id)


class InspectorPanel(QWidget):
    designChanged = Signal()
    reverseRequested = Signal(int)
    customizeRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.design: OpticalDesign | None = None
        self.element_index = -1
        self.surface_index = -1
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        element_group = QGroupBox("レンズ")
        element_form = QFormLayout(element_group)
        self.name_edit = QLineEdit()
        self.identity_label = QLabel("-")
        self.identity_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diameter = spin_box(0.1, 500)
        self.gap = spin_box(0.0, 1000)
        self.element_lock = QCheckBox("固定")
        self.diameter_lock = QCheckBox("径を固定")
        self.gap_lock = QCheckBox("間隔を固定")
        element_form.addRow("名称", self.name_edit)
        element_form.addRow("メーカー / 型番", self.identity_label)
        element_form.addRow("外径", self.diameter)
        element_form.addRow("後方間隔", self.gap)
        element_form.addRow(self.element_lock)
        element_form.addRow(self.diameter_lock)
        element_form.addRow(self.gap_lock)
        button_row = QHBoxLayout()
        self.reverse_button = QPushButton("反転")
        self.customize_button = QPushButton("カスタム化")
        button_row.addWidget(self.reverse_button)
        button_row.addWidget(self.customize_button)
        element_form.addRow(button_row)
        layout.addWidget(element_group)

        surface_group = QGroupBox("面")
        surface_form = QFormLayout(surface_group)
        self.surface_label = QLabel("-")
        self.plane = QCheckBox("平面")
        self.radius = spin_box(-100000, 100000)
        self.material = QLineEdit()
        self.clear_aperture = spin_box(0.0, 500)
        self.radius_lock = QCheckBox("曲率を固定")
        self.material_lock = QCheckBox("硝材を固定")
        self.aperture_lock = QCheckBox("有効径を固定")
        surface_form.addRow("選択", self.surface_label)
        surface_form.addRow(self.plane)
        surface_form.addRow("曲率半径", self.radius)
        surface_form.addRow("面後の媒質", self.material)
        surface_form.addRow("有効径", self.clear_aperture)
        surface_form.addRow(self.radius_lock)
        surface_form.addRow(self.material_lock)
        surface_form.addRow(self.aperture_lock)
        layout.addWidget(surface_group)

        analysis_group = QGroupBox("一次解析")
        analysis_form = QFormLayout(analysis_group)
        self.engine = QLabel("-")
        self.efl = QLabel("-")
        self.bfl = QLabel("-")
        self.fno = QLabel("-")
        self.epd = QLabel("-")
        self.track = QLabel("-")
        self.analysis_status = QLabel("")
        self.analysis_status.setWordWrap(True)
        analysis_form.addRow("エンジン", self.engine)
        analysis_form.addRow("EFL", self.efl)
        analysis_form.addRow("BFL", self.bfl)
        analysis_form.addRow("F値", self.fno)
        analysis_form.addRow("入射瞳径", self.epd)
        analysis_form.addRow("全長", self.track)
        analysis_form.addRow(self.analysis_status)
        layout.addWidget(analysis_group)
        layout.addStretch(1)

        for widget in (self.name_edit, self.diameter, self.gap, self.element_lock, self.diameter_lock, self.gap_lock):
            signal = getattr(widget, "editingFinished", None) or getattr(widget, "toggled")
            signal.connect(self._apply_element)
        for widget in (self.plane, self.radius, self.material, self.clear_aperture, self.radius_lock, self.material_lock, self.aperture_lock):
            signal = getattr(widget, "editingFinished", None) or getattr(widget, "toggled")
            signal.connect(self._apply_surface)
        self.reverse_button.clicked.connect(lambda: self.reverseRequested.emit(self.element_index))
        self.customize_button.clicked.connect(lambda: self.customizeRequested.emit(self.element_index))

    def set_selection(self, design: OpticalDesign, element_index: int, surface_index: int = -1) -> None:
        self.design = design
        self.element_index = element_index
        self.surface_index = surface_index
        self._load()

    def clear_selection(self) -> None:
        self.design = None
        self.element_index = -1
        self.surface_index = -1
        self._load()

    def set_analysis(self, result: FirstOrderAnalysis, design: OpticalDesign) -> None:
        self.engine.setText(result.engine)
        if result.valid:
            self.efl.setText(self._metric(result.effective_focal_length_mm, design.settings.focal_length_target_mm))
            self.bfl.setText(self._metric(result.back_focal_length_mm, design.settings.back_focus_target_mm))
            self.fno.setText(f"F/{result.image_f_number:.3g}")
            self.epd.setText(f"{result.entrance_pupil_diameter_mm:.3f} mm")
            self.track.setText(f"{result.total_track_mm:.3f} mm")
            self.analysis_status.setText("; ".join(result.warnings))
            self.analysis_status.setStyleSheet("color: #8a5a13;")
        else:
            for label in (self.efl, self.bfl, self.fno, self.epd, self.track):
                label.setText("-")
            self.analysis_status.setText(result.error)
            self.analysis_status.setStyleSheet("color: #a13d3a;")

    @staticmethod
    def _metric(value: float | None, target: float) -> str:
        return "-" if value is None else f"{value:.3f} mm  (目標 {target:.3f})"

    def _load(self) -> None:
        self._updating = True
        valid = self.design is not None and 0 <= self.element_index < len(self.design.elements)
        for widget in (
            self.name_edit,
            self.diameter,
            self.gap,
            self.element_lock,
            self.diameter_lock,
            self.gap_lock,
            self.reverse_button,
            self.customize_button,
        ):
            widget.setEnabled(valid)
        if not valid:
            self.identity_label.setText("-")
            self.surface_label.setText("-")
            self._updating = False
            return
        element = self.design.elements[self.element_index]
        self.name_edit.setText(element.name)
        self.identity_label.setText(" / ".join(item for item in (element.manufacturer, element.part_number) if item) or "Custom")
        self.diameter.setValue(element.outer_diameter_mm)
        self.gap.setValue(element.gap_after_mm)
        self.element_lock.setChecked(element.element_locked)
        self.diameter_lock.setChecked(element.diameter_locked)
        self.gap_lock.setChecked(element.gap_locked)
        self.diameter.setEnabled(not element.is_catalog)
        self.customize_button.setEnabled(element.is_catalog)
        self.reverse_button.setEnabled(not element.orientation_locked)

        surface_valid = 0 <= self.surface_index < len(element.surfaces)
        for widget in (
            self.plane,
            self.radius,
            self.material,
            self.clear_aperture,
            self.radius_lock,
            self.material_lock,
            self.aperture_lock,
        ):
            widget.setEnabled(surface_valid and not element.is_catalog)
        if surface_valid:
            surface = element.surfaces[self.surface_index]
            self.surface_label.setText(f"S{self.surface_index + 1}")
            self.plane.setChecked(surface.is_plane)
            self.radius.setValue(0.0 if surface.is_plane else float(surface.radius_mm))
            self.radius.setEnabled(not surface.is_plane and not element.is_catalog)
            self.material.setText(surface.material_after)
            self.clear_aperture.setValue(surface.clear_aperture_mm or 0.0)
            self.radius_lock.setChecked(surface.radius_locked)
            self.material_lock.setChecked(surface.material_locked)
            self.aperture_lock.setChecked(surface.clear_aperture_locked)
        else:
            self.surface_label.setText("面を選択")
        self._updating = False

    def _apply_element(self) -> None:
        if self._updating or self.design is None or self.element_index < 0:
            return
        element = self.design.elements[self.element_index]
        element.name = self.name_edit.text().strip() or element.name
        if not element.is_catalog:
            element.outer_diameter_mm = self.diameter.value()
        element.gap_after_mm = self.gap.value()
        element.element_locked = self.element_lock.isChecked()
        element.diameter_locked = self.diameter_lock.isChecked()
        element.gap_locked = self.gap_lock.isChecked()
        self.designChanged.emit()

    def _apply_surface(self) -> None:
        if self._updating or self.design is None or self.element_index < 0 or self.surface_index < 0:
            return
        element = self.design.elements[self.element_index]
        if element.is_catalog:
            return
        surface = element.surfaces[self.surface_index]
        surface.radius_mm = None if self.plane.isChecked() else self.radius.value()
        surface.material_after = self.material.text().strip() or "air"
        surface.clear_aperture_mm = self.clear_aperture.value()
        surface.radius_locked = self.radius_lock.isChecked()
        surface.material_locked = self.material_lock.isChecked()
        surface.clear_aperture_locked = self.aperture_lock.isChecked()
        self.radius.setEnabled(not self.plane.isChecked())
        self.designChanged.emit()


class SurfaceTable(QTableWidget):
    designChanged = Signal()
    surfaceSelected = Signal(int, int)

    HEADERS = ["要素", "面", "曲率半径", "次面まで", "面後の媒質", "有効径", "状態"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(self.HEADERS)):
            self.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.design: OpticalDesign | None = None
        self._row_map: list[tuple[int, int]] = []
        self.itemChanged.connect(self._item_changed)
        self.itemSelectionChanged.connect(self._selection_changed)

    def set_design(self, design: OpticalDesign) -> None:
        self.design = design
        self.blockSignals(True)
        self._row_map.clear()
        row_count = sum(len(element.surfaces) for element in design.elements)
        self.setRowCount(row_count)
        row = 0
        for element_index, element in enumerate(design.elements):
            for surface_index, surface in enumerate(element.surfaces):
                self._row_map.append((element_index, surface_index))
                is_last = surface_index == len(element.surfaces) - 1
                values = [
                    element.part_number or element.name,
                    str(surface_index + 1),
                    "Plane" if surface.is_plane else f"{surface.radius_mm:.6g}",
                    f"{element.gap_after_mm if is_last else surface.thickness_after_mm:.6g}",
                    surface.material_after,
                    "" if surface.clear_aperture_mm is None else f"{surface.clear_aperture_mm:.6g}",
                    "Catalog" if element.is_catalog else "Custom",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    editable = not element.is_catalog and column in (2, 3, 4, 5)
                    if is_last and column == 3:
                        editable = True
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if column in (1, 2, 3, 5):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.setItem(row, column, item)
                row += 1
        self.blockSignals(False)

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self.design is None or item.row() >= len(self._row_map):
            return
        element_index, surface_index = self._row_map[item.row()]
        element = self.design.elements[element_index]
        surface = element.surfaces[surface_index]
        is_last = surface_index == len(element.surfaces) - 1
        try:
            if item.column() == 2 and not element.is_catalog:
                surface.radius_mm = None if item.text().strip().lower() in {"plane", "flat", "inf"} else float(item.text())
            elif item.column() == 3:
                value = max(0.0, float(item.text()))
                if is_last:
                    element.gap_after_mm = value
                elif not element.is_catalog:
                    surface.thickness_after_mm = value
            elif item.column() == 4 and not element.is_catalog:
                surface.material_after = item.text().strip() or "air"
            elif item.column() == 5 and not element.is_catalog:
                surface.clear_aperture_mm = max(0.0, float(item.text()))
            else:
                return
        except ValueError:
            self.set_design(self.design)
            return
        self.designChanged.emit()

    def _selection_changed(self) -> None:
        row = self.currentRow()
        if 0 <= row < len(self._row_map):
            self.surfaceSelected.emit(*self._row_map[row])

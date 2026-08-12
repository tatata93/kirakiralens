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
    QStyle,
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
        filters.setHorizontalSpacing(6)
        filters.setVerticalSpacing(5)
        self.search = QLineEdit()
        self.search.setPlaceholderText("型番・名称を検索")
        self.manufacturer = QComboBox()
        self.manufacturer.addItem("全メーカー", "")
        for value in repository.filter_values("manufacturer"):
            self.manufacturer.addItem(value, value)
        self.shape = QComboBox()
        self.shape.addItem("全形状", "")
        for value in repository.filter_values("shape"):
            self.shape.addItem(SHAPE_LABELS.get(value, value), value)
        self.material = QComboBox()
        self.material.addItem("全硝材", "")
        for value in repository.filter_values("material"):
            self.material.addItem(value, value)
        self.coating = QComboBox()
        self.coating.addItem("全コーティング", "")
        for value in repository.filter_values("coating"):
            self.coating.addItem(value, value)

        self.min_diameter = spin_box(0, 10000, 1)
        self.min_diameter.setPrefix("最小 ")
        self.min_diameter.setSpecialValueText("下限なし")
        self.min_diameter.setValue(12.5)
        self.min_diameter.setMaximumWidth(150)
        self.max_diameter = spin_box(0, 10000, 1)
        self.max_diameter.setPrefix("最大 ")
        self.max_diameter.setSpecialValueText("上限なし")
        self.max_diameter.setValue(50)
        self.max_diameter.setMaximumWidth(150)
        diameter_row = QWidget()
        diameter_layout = QHBoxLayout(diameter_row)
        diameter_layout.setContentsMargins(0, 0, 0, 0)
        diameter_layout.setSpacing(5)
        diameter_layout.addWidget(self.min_diameter)
        diameter_layout.addWidget(self.max_diameter)

        self.min_clear_aperture = spin_box(0, 10000, 1)
        self.min_clear_aperture.setPrefix("CA ≥ ")
        self.min_clear_aperture.setSpecialValueText("CA制限なし")
        self.power = QComboBox()
        self.power.addItem("正負すべて", "")
        self.power.addItem("正レンズ", "positive")
        self.power.addItem("負レンズ", "negative")

        self.efl_range_enabled = QCheckBox("EFL範囲")
        self.min_efl = spin_box(-100000, 100000, 1)
        self.min_efl.setPrefix("最小 ")
        self.min_efl.setValue(-100)
        self.min_efl.setMaximumWidth(150)
        self.max_efl = spin_box(-100000, 100000, 1)
        self.max_efl.setPrefix("最大 ")
        self.max_efl.setValue(100)
        self.max_efl.setMaximumWidth(150)
        efl_row = QWidget()
        efl_layout = QHBoxLayout(efl_row)
        efl_layout.setContentsMargins(0, 0, 0, 0)
        efl_layout.setSpacing(5)
        efl_layout.addWidget(self.min_efl)
        efl_layout.addWidget(self.max_efl)
        self.min_efl.setEnabled(False)
        self.max_efl.setEnabled(False)

        self.wavelength = spin_box(0, 100000, 0, " nm")
        self.wavelength.setPrefix("波長 ")
        self.wavelength.setSpecialValueText("波長制限なし")
        self.sort = QComboBox()
        self.sort.addItem("目標 |EFL| に近い順", "target_efl")
        self.sort.addItem("外径の大きい順", "diameter_desc")
        self.sort.addItem("EFLの小さい順", "efl_asc")
        self.sort.addItem("型番順", "part_number")
        for combo in (self.manufacturer, self.shape, self.material, self.coating, self.power, self.sort):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setMinimumWidth(0)
        self.target_efl = 50.0
        self._design_f_number = 4.0
        self._design_max_diameter = 50.0

        self.include_incomplete = QCheckBox("不完全データも表示")
        self.photo_filter_button = QPushButton("撮影用絞込")
        self.photo_filter_button.setToolTip("設計の焦点距離、F値、最大径に合わせる")
        self.clear_filter_button = QPushButton("全解除")
        filters.addWidget(self.search, 0, 0, 1, 4)
        filters.addWidget(self.manufacturer, 1, 0, 1, 2)
        filters.addWidget(self.shape, 1, 2, 1, 2)
        filters.addWidget(self.material, 2, 0, 1, 2)
        filters.addWidget(self.coating, 2, 2, 1, 2)
        filters.addWidget(QLabel("外径範囲"), 3, 0)
        filters.addWidget(diameter_row, 3, 1, 1, 3)
        filters.addWidget(self.min_clear_aperture, 4, 0, 1, 2)
        filters.addWidget(self.power, 4, 2, 1, 2)
        filters.addWidget(self.efl_range_enabled, 5, 0)
        filters.addWidget(efl_row, 5, 1, 1, 3)
        filters.addWidget(self.wavelength, 6, 0, 1, 2)
        filters.addWidget(self.sort, 6, 2, 1, 2)
        filters.addWidget(self.photo_filter_button, 7, 0)
        filters.addWidget(self.clear_filter_button, 7, 1)
        filters.addWidget(self.include_incomplete, 7, 2, 1, 2)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["型番", "形状", "外径", "CA", "EFL", "硝材"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumWidth(0)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column, width in enumerate((82, 92, 58, 58, 72)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.details = QLabel("部品を選択すると仕様を表示します")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setMinimumHeight(42)
        layout.addWidget(self.details)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.add_button = QPushButton("設計へ追加")
        self.add_button.setEnabled(False)
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        footer.addWidget(self.add_button)
        layout.addLayout(footer)

        for widget in (
            self.search,
            self.manufacturer,
            self.shape,
            self.material,
            self.coating,
            self.min_diameter,
            self.max_diameter,
            self.min_clear_aperture,
            self.power,
            self.efl_range_enabled,
            self.min_efl,
            self.max_efl,
            self.wavelength,
            self.sort,
            self.include_incomplete,
        ):
            signal = getattr(widget, "textChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled")
            signal.connect(lambda *_: self._refresh_timer.start())
        self.efl_range_enabled.toggled.connect(self.min_efl.setEnabled)
        self.efl_range_enabled.toggled.connect(self.max_efl.setEnabled)
        self.photo_filter_button.clicked.connect(self.apply_photo_filter)
        self.clear_filter_button.clicked.connect(self.clear_filters)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.activate_selected())
        self.add_button.clicked.connect(self.activate_selected)
        self.refresh()

    def refresh(self) -> None:
        min_diameter = self.min_diameter.value() or None
        max_diameter = self.max_diameter.value() or None
        min_clear_aperture = self.min_clear_aperture.value() or None
        wavelength = self.wavelength.value() or None
        efl_enabled = self.efl_range_enabled.isChecked()
        self._products = self.repository.query_products(
            search=self.search.text().strip(),
            manufacturer=str(self.manufacturer.currentData() or ""),
            shape=str(self.shape.currentData() or ""),
            material=str(self.material.currentData() or ""),
            coating=str(self.coating.currentData() or ""),
            min_diameter_mm=min_diameter,
            max_diameter_mm=max_diameter,
            min_clear_aperture_mm=min_clear_aperture,
            min_efl_mm=self.min_efl.value() if efl_enabled else None,
            max_efl_mm=self.max_efl.value() if efl_enabled else None,
            power=str(self.power.currentData() or ""),
            wavelength_nm=wavelength,
            designable_only=not self.include_incomplete.isChecked(),
            sort=str(self.sort.currentData()),
            target_efl_mm=self.target_efl,
            limit=1000,
        )
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._products))
            for row, product in enumerate(self._products):
                values = [
                    product.part_number,
                    SHAPE_LABELS.get(product.shape, product.shape),
                    "" if product.outer_diameter_mm is None else f"{product.outer_diameter_mm:g}",
                    "" if product.clear_aperture_mm is None else f"{product.clear_aperture_mm:g}",
                    "" if product.effective_focal_length_mm is None else f"{product.effective_focal_length_mm:g}",
                    product.materials,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column in (2, 3, 4):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        total = self.repository.count_products()
        suffix = "上限1000件" if len(self._products) == 1000 else f"全{total}件"
        self.count_label.setText(f"{len(self._products)}件 / {suffix}")
        self.add_button.setEnabled(False)
        self.details.setText("部品を選択すると仕様を表示します")

    def set_design_targets(self, focal_length_mm: float, f_number: float, max_diameter_mm: float) -> None:
        changed = (
            abs(self.target_efl - abs(focal_length_mm)) > 1e-9
            or abs(self._design_f_number - f_number) > 1e-9
            or abs(self._design_max_diameter - max_diameter_mm) > 1e-9
        )
        self.target_efl = abs(focal_length_mm)
        self._design_f_number = f_number
        self._design_max_diameter = max_diameter_mm
        if abs(self.max_diameter.value() - max_diameter_mm) > 1e-9:
            self.max_diameter.setValue(max_diameter_mm)
        if changed:
            self._refresh_timer.start()

    def apply_photo_filter(self) -> None:
        self.min_diameter.setValue(self.target_efl / max(self._design_f_number, 0.1))
        self.max_diameter.setValue(self._design_max_diameter)
        self.power.setCurrentIndex(0)
        self.sort.setCurrentIndex(self.sort.findData("target_efl"))
        self._refresh_timer.start()

    def clear_filters(self) -> None:
        self.search.clear()
        for combo in (self.manufacturer, self.shape, self.material, self.coating, self.power):
            combo.setCurrentIndex(0)
        self.min_diameter.setValue(0)
        self.max_diameter.setValue(0)
        self.min_clear_aperture.setValue(0)
        self.efl_range_enabled.setChecked(False)
        self.wavelength.setValue(0)
        self.include_incomplete.setChecked(False)
        self.sort.setCurrentIndex(self.sort.findData("target_efl"))
        self._refresh_timer.start()

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
            product = self._products[self.table.currentRow()]
            wavelength = "-"
            if product.wavelength_min_nm is not None and product.wavelength_max_nm is not None:
                wavelength = f"{product.wavelength_min_nm:g}–{product.wavelength_max_nm:g} nm"
            self.details.setText(
                f"{product.manufacturer} {product.part_number}  {product.title}\n"
                f"外径 {product.outer_diameter_mm or 0:g} / CA {product.clear_aperture_mm or 0:g} / "
                f"EFL {product.effective_focal_length_mm or 0:g} / BFL {product.back_focal_length_mm or 0:g} mm\n"
                f"{product.materials} / {product.coating or 'コーティングなし'} / {wavelength}"
            )
            self.selectionChanged.emit(product_id)


class InspectorPanel(QWidget):
    designChanged = Signal()
    reverseRequested = Signal(int)
    customizeRequested = Signal(int)
    deleteRequested = Signal(int)
    surfaceSelectionRequested = Signal(int, int)

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
        self.diameter = spin_box(0.1, 10000)
        self.gap = spin_box(0.0, 100000)
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
        self.delete_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "削除")
        self.delete_button.setToolTip("選択中のレンズを設計から削除")
        button_row.addWidget(self.reverse_button)
        button_row.addWidget(self.customize_button)
        button_row.addWidget(self.delete_button)
        element_form.addRow(button_row)
        layout.addWidget(element_group)

        surface_group = QGroupBox("面")
        surface_form = QFormLayout(surface_group)
        self.surface_selector = QComboBox()
        self.plane = QCheckBox("平面")
        self.radius = spin_box(-100000, 100000)
        self.material = QLineEdit()
        self.clear_aperture = spin_box(0.0, 10000)
        self.radius_lock = QCheckBox("曲率を固定")
        self.material_lock = QCheckBox("硝材を固定")
        self.aperture_lock = QCheckBox("有効径を固定")
        self.catalog_surface_note = QLabel("")
        self.catalog_surface_note.setWordWrap(True)
        surface_form.addRow("編集する面", self.surface_selector)
        surface_form.addRow(self.plane)
        surface_form.addRow("曲率半径", self.radius)
        surface_form.addRow("面後の媒質", self.material)
        surface_form.addRow("有効径", self.clear_aperture)
        surface_form.addRow(self.radius_lock)
        surface_form.addRow(self.material_lock)
        surface_form.addRow(self.aperture_lock)
        surface_form.addRow(self.catalog_surface_note)
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
        self.delete_button.clicked.connect(lambda: self.deleteRequested.emit(self.element_index))
        self.surface_selector.currentIndexChanged.connect(self._surface_selected)

    def set_selection(self, design: OpticalDesign, element_index: int, surface_index: int = -1) -> None:
        self.design = design
        self.element_index = element_index
        if 0 <= element_index < len(design.elements):
            surface_count = len(design.elements[element_index].surfaces)
            self.surface_index = surface_index if 0 <= surface_index < surface_count else 0
        else:
            self.surface_index = -1
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
            self.delete_button,
            self.surface_selector,
        ):
            widget.setEnabled(valid)
        if not valid:
            self.identity_label.setText("-")
            self.surface_selector.clear()
            self.catalog_surface_note.clear()
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

        self.surface_selector.clear()
        for index, surface in enumerate(element.surfaces):
            side = "入射面" if index == 0 else "射出面" if index == len(element.surfaces) - 1 else "接合面"
            radius = "平面" if surface.is_plane else f"R {surface.radius_mm:g} mm"
            self.surface_selector.addItem(f"S{index + 1}  {side}  ({radius})", index)
        self.surface_selector.setCurrentIndex(self.surface_index)
        self.catalog_surface_note.setText("カタログ品は処方を保持します。変更する場合は「カスタム化」を押してください。" if element.is_catalog else "")

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
            self.plane.setChecked(surface.is_plane)
            self.radius.setValue(0.0 if surface.is_plane else float(surface.radius_mm))
            self.radius.setEnabled(not surface.is_plane and not element.is_catalog)
            self.material.setText(surface.material_after)
            self.clear_aperture.setValue(surface.clear_aperture_mm or 0.0)
            self.radius_lock.setChecked(surface.radius_locked)
            self.material_lock.setChecked(surface.material_locked)
            self.aperture_lock.setChecked(surface.clear_aperture_locked)
        else:
            self.surface_selector.setCurrentIndex(-1)
        self._updating = False

    def _surface_selected(self, combo_index: int) -> None:
        if self._updating or combo_index < 0 or self.element_index < 0:
            return
        self.surface_index = int(self.surface_selector.itemData(combo_index))
        self._load()
        self.surfaceSelectionRequested.emit(self.element_index, self.surface_index)

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
        surface.radius_mm = None if self.plane.isChecked() else self.radius.value() or 50.0
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

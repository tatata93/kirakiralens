from __future__ import annotations

from math import inf, isclose, isinf

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain import OpticalDesign
from ..optics.configuration import (
    SENSOR_PRESETS,
    WAVELENGTH_PRESETS,
    resolved_field_angles,
    sensor_angle_of_view,
    sensor_preset_for_size,
)


class NumberListEditor(QWidget):
    changed = Signal()

    def __init__(self, value_header: str, value_range: tuple[float, float], decimals: int, parent=None):
        super().__init__(parent)
        self.value_range = value_range
        self.decimals = decimals
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([value_header, "重み"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.changed)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("+")
        self.add_button.setToolTip("行を追加")
        self.remove_button = QPushButton("−")
        self.remove_button.setToolTip("選択した行を削除")
        self.add_button.setFixedWidth(34)
        self.remove_button.setFixedWidth(34)
        self.add_button.clicked.connect(self.add_row)
        self.remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_values(self, values: list[float], weights: list[float]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(values))
        for row, value in enumerate(values):
            self.table.setItem(row, 0, QTableWidgetItem(f"{value:.{self.decimals}f}"))
            weight = weights[row] if row < len(weights) else 1.0
            self.table.setItem(row, 1, QTableWidgetItem(f"{weight:.3g}"))
        self.table.blockSignals(False)

    def values(self) -> tuple[list[float], list[float]]:
        values: list[float] = []
        weights: list[float] = []
        minimum, maximum = self.value_range
        for row in range(self.table.rowCount()):
            try:
                value = float(self.table.item(row, 0).text())
                weight = float(self.table.item(row, 1).text())
            except (AttributeError, ValueError):
                continue
            values.append(min(max(value, minimum), maximum))
            weights.append(max(weight, 0.0))
        return (values or [minimum], weights or [1.0])

    def add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(f"{self.value_range[0]:.{self.decimals}f}"))
        self.table.setItem(row, 1, QTableWidgetItem("1"))
        self.table.setCurrentCell(row, 0)
        self.changed.emit()

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for row in rows:
            self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self.add_row()
        self.changed.emit()


class SystemSettingsWindow(QDialog):
    designChanged = Signal()

    def __init__(self, design: OpticalDesign, parent=None):
        super().__init__(parent)
        self.design = design
        self._loading = False
        self.setWindowTitle("像面・光線条件")
        self.resize(660, 590)
        self.setMinimumSize(580, 520)
        self.setModal(False)
        self._build_ui()
        self.set_design(design)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_image_tab(), "像面")
        self.tabs.addTab(self._build_field_tab(), "視野・光線")
        self.tabs.addTab(self._build_wavelength_tab(), "波長")
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("適用")
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("閉じる")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _build_image_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.sensor_preset = QComboBox()
        for key, label, _, _ in SENSOR_PRESETS:
            self.sensor_preset.addItem(label, key)
        self.sensor_width = self._double_spin(0.1, 200.0, 2, " mm")
        self.sensor_height = self._double_spin(0.1, 200.0, 2, " mm")
        self.image_distance = self._double_spin(0.0, 1000.0, 3, " mm")
        self.image_distance.setSingleStep(0.1)
        self.image_distance.setAccelerated(True)
        self.image_distance_lock = QCheckBox("像面位置を固定")
        self.auto_focus = QCheckBox("レンズ変更時に像面を最良焦点へ追従")
        self.bfl_tolerance = self._double_spin(0.0, 100.0, 3, " mm")
        self.bfl_hard = QCheckBox("バックフォーカスを必須制約にする")
        self.cover_glass = self._double_spin(0.0, 20.0, 3, " mm")
        self.infinite_object = QCheckBox("無限遠")
        self.object_distance = self._double_spin(1.0, 10000000.0, 1, " mm")
        self.angle_label = QLabel("-")
        self.angle_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("センサー", self.sensor_preset)
        form.addRow("幅", self.sensor_width)
        form.addRow("高さ", self.sensor_height)
        form.addRow("最終面から像面", self.image_distance)
        form.addRow(self.image_distance_lock)
        form.addRow(self.auto_focus)
        form.addRow("BFL許容差", self.bfl_tolerance)
        form.addRow(self.bfl_hard)
        form.addRow("カバーガラス", self.cover_glass)
        form.addRow("物体距離", self.object_distance)
        form.addRow("", self.infinite_object)
        form.addRow("画角", self.angle_label)
        self.sensor_preset.currentIndexChanged.connect(self._sensor_preset_changed)
        self.sensor_width.valueChanged.connect(self._sensor_size_changed)
        self.sensor_height.valueChanged.connect(self._sensor_size_changed)
        self.infinite_object.toggled.connect(lambda checked: self.object_distance.setEnabled(not checked))
        return page

    def _build_field_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.field_mode = QComboBox()
        self.field_mode.addItem("センサー対角の最大画角", "sensor")
        self.field_mode.addItem("任意の半画角", "angles")
        form.addRow("視野指定", self.field_mode)
        layout.addLayout(form)
        self.field_editor = NumberListEditor("像高比", (0.0, 1.0), 3)
        layout.addWidget(self.field_editor, 1)
        density = QFormLayout()
        self.layout_rays = self._integer_spin(1, 31, 2)
        self.spot_rings = self._integer_spin(2, 30, 1)
        self.ray_fan_points = self._integer_spin(11, 501, 10)
        self.curve_points = self._integer_spin(11, 201, 10)
        density.addRow("構成図の光線数 / 視野", self.layout_rays)
        density.addRow("スポット瞳リング数", self.spot_rings)
        density.addRow("横収差の光線数", self.ray_fan_points)
        density.addRow("MTF・像面曲線の点数", self.curve_points)
        layout.addLayout(density)
        self.field_mode.currentIndexChanged.connect(self._field_mode_changed)
        return page

    def _build_wavelength_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.wavelength_preset = QComboBox()
        for key, (label, _, _, _) in WAVELENGTH_PRESETS.items():
            self.wavelength_preset.addItem(label, key)
        self.wavelength_preset.addItem("カスタム", "custom")
        self.primary_wavelength = QComboBox()
        form.addRow("プリセット", self.wavelength_preset)
        form.addRow("主波長", self.primary_wavelength)
        layout.addLayout(form)
        self.wavelength_editor = NumberListEditor("波長 [nm]", (200.0, 2500.0), 2)
        layout.addWidget(self.wavelength_editor, 1)
        self.wavelength_preset.currentIndexChanged.connect(self._wavelength_preset_changed)
        self.wavelength_editor.changed.connect(self._refresh_primary_wavelengths)
        return page

    @staticmethod
    def _double_spin(minimum: float, maximum: float, decimals: int, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def _integer_spin(minimum: int, maximum: int, step: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setKeyboardTracking(False)
        return spin

    def set_design(self, design: OpticalDesign) -> None:
        self.design = design
        settings = design.settings
        settings.normalize()
        self._loading = True
        preset = sensor_preset_for_size(settings.sensor_width_mm, settings.sensor_height_mm)
        self.sensor_preset.setCurrentIndex(max(0, self.sensor_preset.findData(preset)))
        self.sensor_width.setValue(settings.sensor_width_mm)
        self.sensor_height.setValue(settings.sensor_height_mm)
        self.image_distance.setValue(design.elements[-1].gap_after_mm if design.elements else settings.back_focus_target_mm)
        self.image_distance_lock.setChecked(bool(design.elements and design.elements[-1].gap_locked))
        self.auto_focus.setChecked(settings.auto_focus_enabled)
        self.bfl_tolerance.setValue(settings.back_focus_tolerance_mm)
        self.bfl_hard.setChecked(settings.back_focus_hard)
        self.cover_glass.setValue(settings.cover_glass_thickness_mm)
        infinite_object = isinf(settings.object_distance_mm)
        self.infinite_object.setChecked(infinite_object)
        self.object_distance.setValue(1000.0 if infinite_object else settings.object_distance_mm)
        self.object_distance.setEnabled(not infinite_object)
        self.field_mode.setCurrentIndex(max(0, self.field_mode.findData(settings.field_mode)))
        self._set_field_editor(settings.field_mode)
        self.layout_rays.setValue(settings.layout_ray_count)
        self.spot_rings.setValue(settings.spot_ring_count)
        self.ray_fan_points.setValue(settings.ray_fan_point_count)
        self.curve_points.setValue(settings.analysis_curve_point_count)
        self.wavelength_preset.setCurrentIndex(self.wavelength_preset.findData(self._matching_wavelength_preset()))
        self.wavelength_editor.set_values(
            [value * 1000.0 for value in settings.wavelengths_um],
            settings.wavelength_weights,
        )
        self._refresh_primary_wavelengths(settings.primary_wavelength_um)
        self._loading = False
        self._update_angle_label()

    def _matching_wavelength_preset(self) -> str:
        wavelengths = self.design.settings.wavelengths_um
        for key, (_, values, _, _) in WAVELENGTH_PRESETS.items():
            if len(values) == len(wavelengths) and all(isclose(a, b, abs_tol=1e-6) for a, b in zip(values, wavelengths)):
                return key
        return "custom"

    def _sensor_preset_changed(self) -> None:
        if self._loading:
            return
        key = self.sensor_preset.currentData()
        for preset_key, _, width, height in SENSOR_PRESETS:
            if key == preset_key and key != "custom":
                self._loading = True
                self.sensor_width.setValue(width)
                self.sensor_height.setValue(height)
                self._loading = False
                break
        self._update_angle_label()

    def _sensor_size_changed(self) -> None:
        if self._loading:
            return
        key = sensor_preset_for_size(self.sensor_width.value(), self.sensor_height.value())
        self._loading = True
        self.sensor_preset.setCurrentIndex(max(0, self.sensor_preset.findData(key)))
        self._loading = False
        self._update_angle_label()

    def _update_angle_label(self) -> None:
        old_width = self.design.settings.sensor_width_mm
        old_height = self.design.settings.sensor_height_mm
        self.design.settings.sensor_width_mm = self.sensor_width.value()
        self.design.settings.sensor_height_mm = self.sensor_height.value()
        angles = sensor_angle_of_view(self.design.settings)
        self.design.settings.sensor_width_mm = old_width
        self.design.settings.sensor_height_mm = old_height
        self.angle_label.setText(
            f"横 {angles['horizontal_deg']:.2f}° / 縦 {angles['vertical_deg']:.2f}° / 対角 {angles['diagonal_deg']:.2f}°"
        )

    def _field_mode_changed(self) -> None:
        if not self._loading:
            self._set_field_editor(str(self.field_mode.currentData()))

    def _set_field_editor(self, mode: str) -> None:
        settings = self.design.settings
        if mode == "angles":
            values = settings.field_angles_deg
            self.field_editor.table.setHorizontalHeaderLabels(["半画角 [deg]", "重み"])
            self.field_editor.value_range = (0.0, 89.0)
            self.field_editor.decimals = 3
        else:
            values = settings.field_fractions
            self.field_editor.table.setHorizontalHeaderLabels(["像高比", "重み"])
            self.field_editor.value_range = (0.0, 1.0)
            self.field_editor.decimals = 3
        self.field_editor.set_values(values, settings.field_weights)

    def _wavelength_preset_changed(self) -> None:
        if self._loading or self.wavelength_preset.currentData() == "custom":
            return
        _, wavelengths, weights, primary = WAVELENGTH_PRESETS[str(self.wavelength_preset.currentData())]
        self.wavelength_editor.set_values([value * 1000.0 for value in wavelengths], weights)
        self._refresh_primary_wavelengths(primary)

    def _refresh_primary_wavelengths(self, selected_um: float | None = None) -> None:
        current = selected_um
        if current is None and self.primary_wavelength.count():
            current = float(self.primary_wavelength.currentData())
        wavelengths_nm, _ = self.wavelength_editor.values()
        self.primary_wavelength.blockSignals(True)
        self.primary_wavelength.clear()
        for wavelength_nm in wavelengths_nm:
            self.primary_wavelength.addItem(f"{wavelength_nm:.2f} nm", wavelength_nm / 1000.0)
        if current is not None and self.primary_wavelength.count():
            closest = min(
                range(self.primary_wavelength.count()),
                key=lambda index: abs(float(self.primary_wavelength.itemData(index)) - current),
            )
            self.primary_wavelength.setCurrentIndex(closest)
        self.primary_wavelength.blockSignals(False)

    def apply(self) -> None:
        settings = self.design.settings
        image_distance_changed = bool(
            self.design.elements
            and abs(self.design.elements[-1].gap_after_mm - self.image_distance.value()) > 1e-9
        )
        settings.sensor_width_mm = self.sensor_width.value()
        settings.sensor_height_mm = self.sensor_height.value()
        settings.sensor_preset = sensor_preset_for_size(settings.sensor_width_mm, settings.sensor_height_mm)
        settings.back_focus_target_mm = self.image_distance.value()
        settings.back_focus_tolerance_mm = self.bfl_tolerance.value()
        settings.back_focus_hard = self.bfl_hard.isChecked()
        settings.auto_focus_enabled = (
            self.auto_focus.isChecked()
            and not self.image_distance_lock.isChecked()
            and not image_distance_changed
        )
        settings.cover_glass_thickness_mm = self.cover_glass.value()
        settings.object_distance_mm = inf if self.infinite_object.isChecked() else self.object_distance.value()
        if self.design.elements:
            self.design.elements[-1].gap_after_mm = self.image_distance.value()
            self.design.elements[-1].gap_locked = self.image_distance_lock.isChecked()
        settings.field_mode = str(self.field_mode.currentData())
        field_values, settings.field_weights = self.field_editor.values()
        if settings.field_mode == "angles":
            settings.field_angles_deg = field_values
        else:
            settings.field_fractions = field_values
        wavelengths_nm, settings.wavelength_weights = self.wavelength_editor.values()
        settings.wavelengths_um = [value / 1000.0 for value in wavelengths_nm]
        if self.primary_wavelength.count():
            settings.primary_wavelength_um = float(self.primary_wavelength.currentData())
        settings.layout_ray_count = self.layout_rays.value()
        settings.spot_ring_count = self.spot_rings.value()
        settings.ray_fan_point_count = self.ray_fan_points.value()
        settings.analysis_curve_point_count = self.curve_points.value()
        settings.normalize()
        self.designChanged.emit()
        self.set_design(self.design)

    def show_image_tab(self) -> None:
        self.tabs.setCurrentIndex(0)

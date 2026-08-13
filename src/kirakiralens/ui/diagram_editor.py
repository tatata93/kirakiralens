from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..domain import OpticalDesign


def _spin(minimum: float, maximum: float, decimals: int = 3) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(decimals)
    control.setSuffix(" mm")
    control.setKeyboardTracking(False)
    control.setMinimumWidth(105)
    return control


def _number(minimum: float, maximum: float, decimals: int = 6) -> QDoubleSpinBox:
    control = _spin(minimum, maximum, decimals)
    control.setSuffix("")
    return control


class DiagramEditor(QFrame):
    designChanged = Signal()
    selectionRequested = Signal(str, int, int)
    actionRequested = Signal(str, int, int)
    insertionRequested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diagramEditor")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.design: OpticalDesign | None = None
        self.kind = ""
        self.element_index = -1
        self.surface_index = -1
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 6)
        root.setSpacing(4)
        heading = QHBoxLayout()
        self.title = QLabel("構成図で項目を選択")
        self.title.setStyleSheet("font-weight: 600;")
        self.face_selector = QComboBox()
        self.face_selector.setMinimumWidth(190)
        self.face_selector.setVisible(False)
        heading.addWidget(self.title)
        heading.addWidget(self.face_selector)
        heading.addStretch(1)
        root.addLayout(heading)

        self.pages = QStackedWidget()
        self.empty_page = QLabel("面、レンズ、または間隔をクリックしてください")
        self.empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.surface_page = self._build_surface_page()
        self.element_page = self._build_element_page()
        self.gap_page = self._build_gap_page()
        for page in (self.empty_page, self.surface_page, self.element_page, self.gap_page):
            self.pages.addWidget(page)
        root.addWidget(self.pages)

        self.face_selector.currentIndexChanged.connect(self._face_selected)
        self._connect_controls()

    def _build_surface_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.surface_plane = QCheckBox("平面")
        self.surface_type = QComboBox()
        self.surface_type.addItem("標準球面 / 円錐面", "standard")
        self.surface_type.addItem("偶数次非球面", "even_asphere")
        self.surface_radius = _spin(-1_000_000, 1_000_000)
        self.surface_distance = _spin(0, 100_000)
        self.surface_material = QLineEdit()
        self.surface_material.setPlaceholderText("面後の媒質")
        self.surface_nd = QLineEdit()
        self.surface_nd.setPlaceholderText("空欄はガラスカタログ")
        self.surface_vd = QLineEdit()
        self.surface_vd.setPlaceholderText("空欄はガラスカタログ")
        self.surface_aperture = _spin(0, 10_000)
        self.surface_coating = QLineEdit()
        self.surface_coating.setPlaceholderText("コーティング")
        self.surface_diameter = _spin(0.1, 10_000)
        self.surface_conic = _number(-1_000_000, 1_000_000)
        self.surface_coefficients = QLineEdit()
        self.surface_coefficients.setPlaceholderText("C2, C4, C6, ... をカンマ区切り")
        self.surface_comment = QLineEdit()
        self.surface_comment.setPlaceholderText("面コメント")
        self.radius_lock = QCheckBox("曲率固定")
        self.distance_lock = QCheckBox("距離固定")
        self.material_lock = QCheckBox("媒質固定")
        self.aperture_lock = QCheckBox("有効径固定")
        self.diameter_lock = QCheckBox("外径固定")
        self.conic_lock = QCheckBox("コーニック固定")
        self.asphere_lock = QCheckBox("非球面係数固定")
        self.stop_surface = QCheckBox("絞り位置")
        grid.addWidget(self.surface_plane, 0, 0)
        grid.addWidget(QLabel("曲率半径"), 0, 1)
        grid.addWidget(self.surface_radius, 0, 2)
        grid.addWidget(QLabel("次面まで"), 0, 3)
        grid.addWidget(self.surface_distance, 0, 4)
        grid.addWidget(QLabel("面後の媒質"), 0, 5)
        grid.addWidget(self.surface_material, 0, 6)
        grid.addWidget(QLabel("有効径"), 1, 1)
        grid.addWidget(self.surface_aperture, 1, 2)
        grid.addWidget(QLabel("外径"), 1, 3)
        grid.addWidget(self.surface_diameter, 1, 4)
        grid.addWidget(QLabel("コーティング"), 1, 5)
        grid.addWidget(self.surface_coating, 1, 6)
        grid.addWidget(self.surface_type, 2, 0, 1, 2)
        grid.addWidget(QLabel("コーニック"), 2, 2)
        grid.addWidget(self.surface_conic, 2, 3)
        grid.addWidget(self.surface_coefficients, 2, 4, 1, 2)
        grid.addWidget(self.surface_comment, 2, 6)
        grid.addWidget(QLabel("屈折率 nD"), 3, 0)
        grid.addWidget(self.surface_nd, 3, 1, 1, 2)
        grid.addWidget(QLabel("アッベ数 vd"), 3, 3)
        grid.addWidget(self.surface_vd, 3, 4, 1, 2)

        locks = QHBoxLayout()
        for control in (
            self.radius_lock,
            self.distance_lock,
            self.material_lock,
            self.aperture_lock,
            self.diameter_lock,
            self.conic_lock,
            self.asphere_lock,
            self.stop_surface,
        ):
            locks.addWidget(control)
        locks.addStretch(1)
        grid.addLayout(locks, 4, 0, 1, 7)

        actions = QHBoxLayout()
        add_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        copy_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        trash_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        self.surface_before = QPushButton(add_icon, "面を前へ追加")
        self.surface_after = QPushButton(add_icon, "面を後へ追加")
        self.surface_duplicate = QPushButton(copy_icon, "面を複製")
        self.surface_delete = QPushButton(trash_icon, "面を削除")
        self.surface_customize = QPushButton("カスタム化")
        for button in (self.surface_before, self.surface_after, self.surface_duplicate, self.surface_delete, self.surface_customize):
            actions.addWidget(button)
        actions.addStretch(1)
        grid.addLayout(actions, 5, 0, 1, 7)
        return page

    def _build_element_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        self.element_name = QLineEdit()
        self.element_diameter = _spin(0.1, 10_000)
        self.element_gap = _spin(0, 100_000)
        self.element_lock = QCheckBox("レンズ固定")
        self.element_diameter_lock = QCheckBox("外径固定")
        self.element_gap_lock = QCheckBox("間隔固定")
        self.element_stop = QCheckBox("後方を絞り位置")
        grid.addWidget(QLabel("名称"), 0, 0)
        grid.addWidget(self.element_name, 0, 1, 1, 2)
        grid.addWidget(QLabel("外径"), 0, 3)
        grid.addWidget(self.element_diameter, 0, 4)
        grid.addWidget(QLabel("後方間隔"), 0, 5)
        grid.addWidget(self.element_gap, 0, 6)
        lock_row = QHBoxLayout()
        for control in (self.element_lock, self.element_diameter_lock, self.element_gap_lock, self.element_stop):
            lock_row.addWidget(control)
        lock_row.addStretch(1)
        grid.addLayout(lock_row, 1, 0, 1, 7)

        actions = QHBoxLayout()
        self.element_reverse = QPushButton("反転")
        self.element_duplicate = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon), "複製")
        self.element_customize = QPushButton("カスタム化")
        self.element_delete = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "削除")
        self.element_insert_before = QPushButton("前へ挿入")
        self.element_insert_after = QPushButton("後へ挿入")
        for button in (
            self.element_reverse,
            self.element_duplicate,
            self.element_customize,
            self.element_delete,
            self.element_insert_before,
            self.element_insert_after,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        grid.addLayout(actions, 2, 0, 1, 7)
        return page

    def _build_gap_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        self.gap_value = _spin(0, 100_000)
        self.gap_min = _spin(0, 100_000)
        self.gap_max = _spin(0, 100_000)
        self.gap_max.setSpecialValueText("上限なし")
        self.gap_locked = QCheckBox("間隔固定")
        self.gap_stop = QCheckBox("絞り位置")
        grid.addWidget(QLabel("間隔"), 0, 0)
        grid.addWidget(self.gap_value, 0, 1)
        grid.addWidget(QLabel("最小"), 0, 2)
        grid.addWidget(self.gap_min, 0, 3)
        grid.addWidget(QLabel("最大"), 0, 4)
        grid.addWidget(self.gap_max, 0, 5)
        grid.addWidget(self.gap_locked, 0, 6)
        grid.addWidget(self.gap_stop, 0, 7)
        actions = QHBoxLayout()
        self.gap_zero = QPushButton("接触 (0 mm)")
        self.gap_insert_catalog = QPushButton("選択中のカタログ品を挿入")
        self.gap_insert_custom = QPushButton("カスタムレンズを挿入")
        for button in (self.gap_zero, self.gap_insert_catalog, self.gap_insert_custom):
            actions.addWidget(button)
        actions.addStretch(1)
        grid.addLayout(actions, 1, 0, 1, 8)
        return page

    def _connect_controls(self) -> None:
        for control in (
            self.surface_radius,
            self.surface_distance,
            self.surface_material,
            self.surface_nd,
            self.surface_vd,
            self.surface_aperture,
            self.surface_coating,
            self.surface_diameter,
            self.surface_conic,
            self.surface_coefficients,
            self.surface_comment,
        ):
            control.editingFinished.connect(self._apply_surface)
        for control in (
            self.surface_plane,
            self.radius_lock,
            self.distance_lock,
            self.material_lock,
            self.aperture_lock,
            self.diameter_lock,
            self.conic_lock,
            self.asphere_lock,
            self.stop_surface,
        ):
            control.toggled.connect(self._apply_surface)
        self.surface_type.currentIndexChanged.connect(self._surface_type_changed)
        for control in (self.element_name, self.element_diameter, self.element_gap):
            control.editingFinished.connect(self._apply_element)
        for control in (self.element_lock, self.element_diameter_lock, self.element_gap_lock, self.element_stop):
            control.toggled.connect(self._apply_element)
        for control in (self.gap_value, self.gap_min, self.gap_max):
            control.editingFinished.connect(self._apply_gap)
        for control in (self.gap_locked, self.gap_stop):
            control.toggled.connect(self._apply_gap)

        self.surface_before.clicked.connect(lambda: self._action("surface_insert_before"))
        self.surface_after.clicked.connect(lambda: self._action("surface_insert_after"))
        self.surface_duplicate.clicked.connect(lambda: self._action("surface_duplicate"))
        self.surface_delete.clicked.connect(lambda: self._action("surface_delete"))
        self.surface_customize.clicked.connect(lambda: self._action("customize"))
        self.element_reverse.clicked.connect(lambda: self._action("reverse"))
        self.element_duplicate.clicked.connect(lambda: self._action("element_duplicate"))
        self.element_customize.clicked.connect(lambda: self._action("customize"))
        self.element_delete.clicked.connect(lambda: self._action("delete"))
        self.element_insert_before.clicked.connect(lambda: self.insertionRequested.emit("custom", self.element_index))
        self.element_insert_after.clicked.connect(lambda: self.insertionRequested.emit("custom", self.element_index + 1))
        self.gap_zero.clicked.connect(self._zero_gap)
        self.gap_insert_catalog.clicked.connect(lambda: self.insertionRequested.emit("catalog", self.element_index + 1))
        self.gap_insert_custom.clicked.connect(lambda: self.insertionRequested.emit("custom", self.element_index + 1))

    def set_selection(self, design: OpticalDesign, kind: str, element_index: int, surface_index: int = -1) -> None:
        self.design = design
        self.kind = kind
        self.element_index = element_index
        self.surface_index = surface_index
        self._load()

    def clear_selection(self, design: OpticalDesign | None = None) -> None:
        self.design = design
        self.kind = ""
        self.element_index = -1
        self.surface_index = -1
        self._load()

    def _load(self) -> None:
        self._updating = True
        valid = self.design is not None and 0 <= self.element_index < len(self.design.elements)
        if not valid:
            self.title.setText("構成図で項目を選択")
            self.face_selector.setVisible(False)
            self.pages.setCurrentWidget(self.empty_page)
            self._updating = False
            return
        element = self.design.elements[self.element_index]
        if self.kind == "surface":
            self.surface_index = min(max(self.surface_index, 0), len(element.surfaces) - 1)
            surface = element.surfaces[self.surface_index]
            is_last = self.surface_index == len(element.surfaces) - 1
            self.title.setText(f"L{self.element_index + 1}  面")
            self.face_selector.clear()
            for index, candidate in enumerate(element.surfaces):
                side = "入射面" if index == 0 else "射出面" if index == len(element.surfaces) - 1 else "接合面"
                radius = "平面" if candidate.is_plane else f"R {candidate.radius_mm:g}"
                self.face_selector.addItem(f"S{index + 1} {side} ({radius})", index)
            self.face_selector.setCurrentIndex(self.surface_index)
            self.face_selector.setVisible(True)
            self.surface_plane.setChecked(surface.is_plane)
            self.surface_radius.setValue(0 if surface.is_plane else float(surface.radius_mm))
            if is_last and self.design.explicit_stop_after_element == self.element_index:
                self.surface_distance.setValue(self.design.explicit_stop_offset_mm)
            else:
                self.surface_distance.setValue(element.gap_after_mm if is_last else surface.thickness_after_mm)
            self.surface_material.setText(surface.material_after)
            self.surface_nd.setText("" if surface.refractive_index_d is None else f"{surface.refractive_index_d:g}")
            self.surface_vd.setText("" if surface.abbe_number_d is None else f"{surface.abbe_number_d:g}")
            self.surface_aperture.setValue(surface.clear_aperture_mm or 0)
            self.surface_coating.setText(surface.coating)
            self.surface_diameter.setValue(element.outer_diameter_mm)
            self.surface_type.setCurrentIndex(max(0, self.surface_type.findData(surface.surface_type)))
            self.surface_conic.setValue(surface.conic)
            self.surface_coefficients.setText(", ".join(f"{value:g}" for value in surface.asphere_coefficients))
            self.surface_coefficients.setStyleSheet("")
            self.surface_comment.setText(surface.comment)
            self.radius_lock.setChecked(surface.radius_locked)
            self.distance_lock.setChecked(element.gap_locked if is_last else surface.thickness_locked)
            self.material_lock.setChecked(surface.material_locked)
            self.aperture_lock.setChecked(surface.clear_aperture_locked)
            self.diameter_lock.setChecked(element.diameter_locked)
            self.conic_lock.setChecked(surface.conic_locked)
            self.asphere_lock.setChecked(surface.asphere_locked)
            stop_surface_index = self.design.stop_surface_index
            if stop_surface_index is None or not 0 <= stop_surface_index < len(element.surfaces):
                stop_surface_index = len(element.surfaces) - 1
            self.stop_surface.setChecked(
                self.design.stop_after_element == self.element_index and stop_surface_index == self.surface_index
            )
            self.stop_surface.setEnabled(True)
            prescription_enabled = not element.is_catalog
            for control in (
                self.surface_plane,
                self.surface_radius,
                self.surface_material,
                self.surface_nd,
                self.surface_vd,
                self.surface_aperture,
                self.surface_coating,
                self.surface_diameter,
                self.surface_type,
                self.surface_conic,
                self.surface_coefficients,
                self.surface_comment,
                self.radius_lock,
                self.material_lock,
                self.aperture_lock,
                self.diameter_lock,
                self.conic_lock,
                self.asphere_lock,
                self.surface_before,
                self.surface_after,
                self.surface_duplicate,
                self.surface_delete,
            ):
                control.setEnabled(prescription_enabled)
            self.surface_distance.setEnabled(prescription_enabled or is_last)
            self.distance_lock.setEnabled(prescription_enabled or is_last)
            self.surface_radius.setEnabled(prescription_enabled and not surface.is_plane)
            self.surface_coefficients.setEnabled(prescription_enabled and surface.surface_type == "even_asphere")
            self.asphere_lock.setEnabled(prescription_enabled and surface.surface_type == "even_asphere")
            self.surface_delete.setEnabled(prescription_enabled and len(element.surfaces) > 2)
            self.surface_customize.setVisible(element.is_catalog)
            self.pages.setCurrentWidget(self.surface_page)
        elif self.kind == "gap":
            self.title.setText(f"L{self.element_index + 1} 後方間隔" + (" / BFL" if self.element_index == len(self.design.elements) - 1 else ""))
            self.face_selector.setVisible(False)
            self.gap_value.setValue(element.gap_after_mm)
            self.gap_min.setValue(element.gap_min_mm)
            self.gap_max.setValue(element.gap_max_mm or 0)
            self.gap_locked.setChecked(element.gap_locked)
            stop_surface_index = self.design.stop_surface_index
            if stop_surface_index is None or not 0 <= stop_surface_index < len(element.surfaces):
                stop_surface_index = len(element.surfaces) - 1
            self.gap_stop.setChecked(
                self.design.stop_after_element == self.element_index and stop_surface_index == len(element.surfaces) - 1
            )
            self.pages.setCurrentWidget(self.gap_page)
        else:
            self.title.setText(f"L{self.element_index + 1}  {element.part_number or element.name}")
            self.face_selector.setVisible(False)
            self.element_name.setText(element.name)
            self.element_diameter.setValue(element.outer_diameter_mm)
            self.element_gap.setValue(element.gap_after_mm)
            self.element_lock.setChecked(element.element_locked)
            self.element_diameter_lock.setChecked(element.diameter_locked)
            self.element_gap_lock.setChecked(element.gap_locked)
            stop_surface_index = self.design.stop_surface_index
            if stop_surface_index is None or not 0 <= stop_surface_index < len(element.surfaces):
                stop_surface_index = len(element.surfaces) - 1
            self.element_stop.setChecked(
                self.design.stop_after_element == self.element_index and stop_surface_index == len(element.surfaces) - 1
            )
            self.element_diameter.setEnabled(not element.is_catalog)
            self.element_customize.setVisible(element.is_catalog)
            self.pages.setCurrentWidget(self.element_page)
        self._updating = False

    def _face_selected(self, combo_index: int) -> None:
        if self._updating or combo_index < 0:
            return
        self.selectionRequested.emit("surface", self.element_index, int(self.face_selector.itemData(combo_index)))

    def _surface_type_changed(self) -> None:
        if self._updating:
            return
        is_asphere = self.surface_type.currentData() == "even_asphere"
        self.surface_coefficients.setEnabled(is_asphere)
        self.asphere_lock.setEnabled(is_asphere)
        self._apply_surface()

    def _apply_surface(self) -> None:
        if self._updating or self.design is None or self.kind != "surface":
            return
        element = self.design.elements[self.element_index]
        surface = element.surfaces[self.surface_index]
        is_last = self.surface_index == len(element.surfaces) - 1
        if not element.is_catalog:
            try:
                coefficients = [
                    float(value.strip())
                    for value in self.surface_coefficients.text().split(",")
                    if value.strip()
                ]
            except ValueError:
                self.surface_coefficients.setStyleSheet("border: 1px solid #a13d3a;")
                return
            self.surface_coefficients.setStyleSheet("")
            try:
                nd = float(self.surface_nd.text()) if self.surface_nd.text().strip() else None
                vd = float(self.surface_vd.text()) if self.surface_vd.text().strip() else None
                if (nd is None) != (vd is None) or (nd is not None and (nd <= 1.0 or vd <= 0.0)):
                    raise ValueError
            except ValueError:
                self.surface_nd.setStyleSheet("border: 1px solid #a13d3a;")
                self.surface_vd.setStyleSheet("border: 1px solid #a13d3a;")
                return
            self.surface_nd.setStyleSheet("")
            self.surface_vd.setStyleSheet("")
            radius = self.surface_radius.value()
            surface.radius_mm = None if self.surface_plane.isChecked() else radius or 50.0
            surface.material_after = self.surface_material.text().strip() or "air"
            surface.refractive_index_d = nd
            surface.abbe_number_d = vd
            surface.clear_aperture_mm = self.surface_aperture.value()
            surface.coating = self.surface_coating.text().strip()
            surface.surface_type = str(self.surface_type.currentData())
            surface.conic = self.surface_conic.value()
            surface.asphere_coefficients = coefficients if surface.surface_type == "even_asphere" else []
            surface.comment = self.surface_comment.text().strip()
            element.outer_diameter_mm = self.surface_diameter.value()
            surface.radius_locked = self.radius_lock.isChecked()
            surface.material_locked = self.material_lock.isChecked()
            surface.clear_aperture_locked = self.aperture_lock.isChecked()
            element.diameter_locked = self.diameter_lock.isChecked()
            surface.conic_locked = self.conic_lock.isChecked()
            surface.asphere_locked = self.asphere_lock.isChecked()
        if is_last:
            explicit_stop_here = self.design.explicit_stop_after_element == self.element_index
            old_distance = self.design.explicit_stop_offset_mm if explicit_stop_here else element.gap_after_mm
            distance_changed = abs(old_distance - self.surface_distance.value()) > 1e-9
            if explicit_stop_here:
                self.design.explicit_stop_offset_mm = min(
                    self.surface_distance.value(), element.gap_after_mm
                )
            else:
                element.gap_after_mm = self.surface_distance.value()
            element.gap_locked = self.distance_lock.isChecked()
            if self.element_index == len(self.design.elements) - 1 and not explicit_stop_here:
                self.design.settings.back_focus_target_mm = element.gap_after_mm
                if distance_changed:
                    self.design.settings.auto_focus_enabled = False
        elif not element.is_catalog:
            surface.thickness_after_mm = self.surface_distance.value()
            surface.thickness_locked = self.distance_lock.isChecked()
        if self.stop_surface.isChecked():
            self.design.stop_after_element = self.element_index
            self.design.stop_surface_index = self.surface_index
            self.design.explicit_stop_after_element = None
        self.designChanged.emit()

    def _apply_element(self) -> None:
        if self._updating or self.design is None or self.kind not in {"element", "surface"}:
            return
        element = self.design.elements[self.element_index]
        gap_changed = abs(element.gap_after_mm - self.element_gap.value()) > 1e-9
        element.name = self.element_name.text().strip() or element.name
        if not element.is_catalog:
            element.outer_diameter_mm = self.element_diameter.value()
        element.gap_after_mm = self.element_gap.value()
        element.element_locked = self.element_lock.isChecked()
        element.diameter_locked = self.element_diameter_lock.isChecked()
        element.gap_locked = self.element_gap_lock.isChecked()
        if self.element_stop.isChecked():
            self.design.stop_after_element = self.element_index
            self.design.stop_surface_index = len(element.surfaces) - 1
            self.design.explicit_stop_after_element = None
        if self.element_index == len(self.design.elements) - 1:
            self.design.settings.back_focus_target_mm = element.gap_after_mm
            if gap_changed:
                self.design.settings.auto_focus_enabled = False
        self.designChanged.emit()

    def _apply_gap(self) -> None:
        if self._updating or self.design is None or self.kind != "gap":
            return
        element = self.design.elements[self.element_index]
        gap_changed = abs(element.gap_after_mm - self.gap_value.value()) > 1e-9
        minimum = self.gap_min.value()
        maximum = self.gap_max.value() or None
        if maximum is not None and maximum < minimum:
            maximum = minimum
        element.gap_min_mm = minimum
        element.gap_max_mm = maximum
        element.gap_after_mm = max(minimum, self.gap_value.value())
        if maximum is not None:
            element.gap_after_mm = min(element.gap_after_mm, maximum)
        if self.design.explicit_stop_after_element == self.element_index:
            self.design.explicit_stop_offset_mm = min(
                self.design.explicit_stop_offset_mm, element.gap_after_mm
            )
        element.gap_locked = self.gap_locked.isChecked()
        if self.gap_stop.isChecked():
            self.design.stop_after_element = self.element_index
            self.design.stop_surface_index = len(element.surfaces) - 1
            self.design.explicit_stop_after_element = None
        if self.element_index == len(self.design.elements) - 1:
            self.design.settings.back_focus_target_mm = element.gap_after_mm
            if gap_changed:
                self.design.settings.auto_focus_enabled = False
        self.designChanged.emit()

    def _zero_gap(self) -> None:
        self.gap_value.setValue(0)
        self._apply_gap()

    def _action(self, action: str) -> None:
        self.actionRequested.emit(action, self.element_index, self.surface_index)

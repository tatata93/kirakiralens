from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..domain import OpticalDesign
from ..optics.optiland_adapter import FirstOrderAnalysis
from ..optics.reference_designs import (
    ReferenceExample,
    reference_example,
    reference_examples,
    validate_reference_analysis,
)


class ReferenceExamplesWindow(QDialog):
    loadRequested = Signal(str)
    calculateRequested = Signal()

    def __init__(self, design: OpticalDesign, analysis: FirstOrderAnalysis, parent=None):
        super().__init__(parent)
        self.design = design
        self.analysis = analysis
        self.setWindowTitle("特許実施例・計算照合")
        self.resize(900, 680)
        self.setMinimumSize(720, 560)
        self.setModal(False)
        self._build_ui()
        self.set_state(design, analysis)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("実施例"))
        self.example_combo = QComboBox()
        for example in reference_examples():
            self.example_combo.addItem(example.label, example.key)
        self.example_combo.setMinimumWidth(430)
        top.addWidget(self.example_combo, 1)
        self.source_button = QPushButton("公報を開く")
        self.source_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        top.addWidget(self.source_button)
        layout.addLayout(top)

        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.description)

        layout.addWidget(QLabel("公報記載の面データ"))
        self.prescription_table = QTableWidget(0, 6)
        self.prescription_table.setHorizontalHeaderLabels(
            ["面", "要素", "曲率半径 [mm]", "次面まで [mm]", "面後の媒質", "備考"]
        )
        self.prescription_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.prescription_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.prescription_table.verticalHeader().hide()
        self.prescription_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.prescription_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.prescription_table, 1)

        layout.addWidget(QLabel("公報値との照合"))
        self.validation_table = QTableWidget(0, 5)
        self.validation_table.setHorizontalHeaderLabels(["項目", "公報値", "計算値", "許容差", "判定"])
        self.validation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.validation_table.verticalHeader().hide()
        self.validation_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.validation_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.validation_table.setMaximumHeight(170)
        layout.addWidget(self.validation_table)

        bottom = QHBoxLayout()
        self.status_label = QLabel("未読込")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom.addWidget(self.status_label, 1)
        self.load_button = QPushButton("設計へ読み込む")
        self.load_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.calculate_button = QPushButton("再計算して照合")
        self.calculate_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        bottom.addWidget(self.load_button)
        bottom.addWidget(self.calculate_button)
        layout.addLayout(bottom)

        self.example_combo.currentIndexChanged.connect(self._refresh_example)
        self.source_button.clicked.connect(self._open_source)
        self.load_button.clicked.connect(lambda: self.loadRequested.emit(self.current_key()))
        self.calculate_button.clicked.connect(self.calculateRequested)

    def current_key(self) -> str:
        return str(self.example_combo.currentData())

    def set_state(self, design: OpticalDesign, analysis: FirstOrderAnalysis) -> None:
        self.design = design
        self.analysis = analysis
        if design.reference_example_key:
            index = self.example_combo.findData(design.reference_example_key)
            if index >= 0 and index != self.example_combo.currentIndex():
                self.example_combo.setCurrentIndex(index)
                return
        self._refresh_validation(reference_example(self.current_key()))

    def _refresh_example(self) -> None:
        example = reference_example(self.current_key())
        self.description.setText(example.description)
        self._fill_prescription(example)
        self._refresh_validation(example)

    def _fill_prescription(self, example: ReferenceExample) -> None:
        design = example.build()
        rows: list[list[str]] = []
        surface_number = 1
        for element_index, element in enumerate(design.elements):
            for surface_index, surface in enumerate(element.surfaces):
                is_last = surface_index == len(element.surfaces) - 1
                distance = element.gap_after_mm if is_last else surface.thickness_after_mm
                if is_last and design.explicit_stop_after_element == element_index:
                    distance = design.explicit_stop_offset_mm
                radius = "Plane" if surface.is_plane else f"{surface.radius_mm:.6g}"
                if surface.refractive_index_d is None:
                    material = "air"
                else:
                    material = f"nD {surface.refractive_index_d:.5f} / vd {surface.abbe_number_d:.2f}"
                note = "偶数次非球面" if surface.surface_type == "even_asphere" else ""
                rows.append([str(surface_number), element.name, radius, f"{distance:.6g}", material, note])
                surface_number += 1
                if is_last and design.explicit_stop_after_element == element_index:
                    remaining = element.gap_after_mm - design.explicit_stop_offset_mm
                    rows.append([str(surface_number), "絞り", "Plane", f"{remaining:.6g}", "air", "開口絞り"])
                    surface_number += 1
        self.prescription_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 2, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.prescription_table.setItem(row, column, item)

    def _refresh_validation(self, example: ReferenceExample) -> None:
        current = self.design.reference_example_key == example.key
        results = validate_reference_analysis(self.design, self.analysis) if current else []
        by_key = {result.key: result for result in results}
        self.validation_table.setRowCount(len(example.metrics))
        all_passed = bool(results)
        for row, metric in enumerate(example.metrics):
            result = by_key.get(metric.key)
            actual = "-" if result is None or result.actual is None else f"{result.actual:.6g} {metric.unit}".strip()
            passed = bool(result and result.passed)
            all_passed = all_passed and passed
            values = [
                metric.label,
                f"{metric.expected:.6g} {metric.unit}".strip(),
                actual,
                f"±{metric.tolerance:.6g} {metric.unit}".strip(),
                "合格" if passed else ("不一致" if result is not None else "未計算"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setForeground(QColor("#28734f" if passed else "#a1483d"))
                self.validation_table.setItem(row, column, item)
        if all_passed:
            self.status_label.setText("公報の公称値を許容差内で再現しています")
            self.status_label.setStyleSheet("color: #28734f; font-weight: 600;")
        elif current and self.analysis.valid:
            self.status_label.setText("公報値と一致しない項目があります")
            self.status_label.setStyleSheet("color: #a1483d; font-weight: 600;")
        elif current:
            self.status_label.setText("読み込み済み。再計算してください")
            self.status_label.setStyleSheet("")
        else:
            self.status_label.setText("この実施例は現在の設計に読み込まれていません")
            self.status_label.setStyleSheet("")

    def _open_source(self) -> None:
        example = reference_example(self.current_key())
        QDesktopServices.openUrl(QUrl(example.source_url))

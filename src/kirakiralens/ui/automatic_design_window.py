from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..catalog.database import CatalogRepository
from ..domain import LensElement, OpticalDesign
from ..optics.automatic_design import normalized_automatic_options, variable_candidates
from ..optics.classic_forms import CLASSIC_FORMS, build_classic_design, classic_form
from .automatic_design_controller import AutomaticDesignController
from .lens_view import LensLayoutView


class AutomaticDesignWindow(QMainWindow):
    applyRequested = Signal(object)

    def __init__(self, design: OpticalDesign, repository_root: Path, parent=None):
        super().__init__(parent)
        self.design = deepcopy(design)
        self.repository = CatalogRepository(repository_root / "data" / "generated" / "edmund_catalog.sqlite3")
        self.best_design: OpticalDesign | None = None
        self.candidate_payloads: list[dict] = []
        self._generation = 0
        self._running = False
        self._applying_merit_preset = False
        self._controller = AutomaticDesignController(repository_root / ".tmp" / "matplotlib", self)
        self._controller.progress.connect(self._progress)
        self._controller.finished.connect(self._finished)
        self._controller.runningChanged.connect(self._running_changed)
        self.setWindowTitle("自動設計 - KiraKiraLens")
        self.resize(1050, 820)
        self.setMinimumSize(900, 700)
        self._build_ui()
        self._refresh_variable_count()

    def _build_ui(self) -> None:
        central = QTabWidget()
        self.tabs = central
        settings_page = QWidget()
        layout = QVBoxLayout(settings_page)
        layout.setContentsMargins(12, 10, 12, 12)

        setup = QGroupBox("探索方法")
        setup_layout = QGridLayout(setup)
        self.method = QComboBox()
        self.method.addItem("局所（速い）", "local")
        self.method.addItem("大域（広く探索）", "global")
        self.search_scope = QComboBox()
        self.search_scope.addItem("今の構成を調整", "continuous")
        self.search_scope.addItem("今の部品数で市販レンズを交換", "discrete")
        self.search_scope.addItem("部品数も含めて自由探索", "topology")
        self.search_scope.addItem("古典型から市販レンズを探索", "classic")
        self.time_limit = QSpinBox()
        self.time_limit.setRange(1, 86400)
        self.time_limit.setSuffix(" 秒")
        self.time_limit.setValue(60)
        self.max_evaluations = QSpinBox()
        self.max_evaluations.setRange(10, 1000000)
        self.max_evaluations.setValue(500)
        self.variable_count = QLabel("-")
        setup_layout.addWidget(QLabel("探索モード"), 0, 0)
        setup_layout.addWidget(self.search_scope, 0, 1, 1, 3)
        setup_layout.addWidget(QLabel("仕上げ方式"), 1, 0)
        setup_layout.addWidget(self.method, 1, 1)
        setup_layout.addWidget(QLabel("最大時間"), 1, 2)
        setup_layout.addWidget(self.time_limit, 1, 3)
        setup_layout.addWidget(QLabel("最大計算回数"), 2, 0)
        setup_layout.addWidget(self.max_evaluations, 2, 1)
        setup_layout.addWidget(QLabel("変更可能な値"), 2, 2)
        setup_layout.addWidget(self.variable_count, 2, 3)
        layout.addWidget(setup)

        target_group = QGroupBox("必要な仕様")
        target_grid = QGridLayout(target_group)
        self.target_efl = self._value_spin(0.1, 2000.0, self.design.settings.focal_length_target_mm, " mm")
        self.efl_tolerance = self._value_spin(0.001, 100.0, 0.5, " mm", 3)
        self.efl_hard = QCheckBox("必須")
        self.target_f_number = self._value_spin(0.5, 64.0, self.design.settings.f_number_target, "", 2)
        self.bfl_constraint = QComboBox()
        self.bfl_constraint.addItem("目標値", "target")
        self.bfl_constraint.addItem("以上", "minimum")
        self.bfl_constraint.addItem("範囲", "range")
        self.bfl_constraint.addItem("制約なし", "off")
        self.target_bfl = self._value_spin(0.0, 1000.0, self.design.settings.back_focus_target_mm, " mm")
        self.minimum_bfl = self._value_spin(0.0, 1000.0, self.design.settings.back_focus_target_mm, " mm")
        self.maximum_bfl = self._value_spin(0.0, 1000.0, max(self.design.settings.back_focus_target_mm, 100.0), " mm")
        self.bfl_tolerance = self._value_spin(0.001, 100.0, self.design.settings.back_focus_tolerance_mm, " mm", 3)
        self.bfl_hard = QCheckBox("必須")
        self.track_limit_enabled = QCheckBox("全長上限")
        self.maximum_total_track = self._value_spin(0.1, 5000.0, 120.0, " mm")
        self.track_hard = QCheckBox("必須")
        self.track_hard.setChecked(True)
        target_grid.addWidget(QLabel("焦点距離 EFL"), 0, 0)
        target_grid.addWidget(self.target_efl, 0, 1)
        target_grid.addWidget(QLabel("許容差"), 0, 2)
        target_grid.addWidget(self.efl_tolerance, 0, 3)
        target_grid.addWidget(self.efl_hard, 0, 4)
        target_grid.addWidget(QLabel("目標F値"), 1, 0)
        target_grid.addWidget(self.target_f_number, 1, 1)
        target_grid.addWidget(QLabel("バックフォーカス条件"), 2, 0)
        target_grid.addWidget(self.bfl_constraint, 2, 1)
        self.target_bfl_label = QLabel("目標BFL")
        self.minimum_bfl_label = QLabel("最小BFL")
        self.maximum_bfl_label = QLabel("最大BFL")
        self.bfl_tolerance_label = QLabel("BFL許容差")
        target_grid.addWidget(self.target_bfl_label, 3, 0)
        target_grid.addWidget(self.target_bfl, 3, 1)
        target_grid.addWidget(self.minimum_bfl_label, 4, 0)
        target_grid.addWidget(self.minimum_bfl, 4, 1)
        target_grid.addWidget(self.maximum_bfl_label, 5, 0)
        target_grid.addWidget(self.maximum_bfl, 5, 1)
        target_grid.addWidget(self.bfl_tolerance_label, 6, 0)
        target_grid.addWidget(self.bfl_tolerance, 6, 1)
        target_grid.addWidget(self.bfl_hard, 2, 4)
        target_grid.addWidget(self.track_limit_enabled, 7, 0)
        target_grid.addWidget(self.maximum_total_track, 7, 1)
        target_grid.addWidget(self.track_hard, 7, 4)
        self.track_limit_enabled.toggled.connect(self.maximum_total_track.setEnabled)
        self.track_limit_enabled.toggled.connect(self.track_hard.setEnabled)
        self.maximum_total_track.setEnabled(False)
        self.track_hard.setEnabled(False)
        self.bfl_constraint.currentIndexChanged.connect(self._update_bfl_controls)

        self.discrete_group = QGroupBox("市販レンズと構成の探索")
        discrete_grid = QGridLayout(self.discrete_group)
        self.discrete_evaluations = QSpinBox()
        self.discrete_evaluations.setRange(1, 100000)
        self.discrete_evaluations.setValue(80)
        self.candidates_per_slot = QSpinBox()
        self.candidates_per_slot.setRange(1, 100)
        self.candidates_per_slot.setValue(8)
        self.result_count = QSpinBox()
        self.result_count.setRange(1, 50)
        self.result_count.setValue(10)
        self.mtf_screen_count = QSpinBox()
        self.mtf_screen_count.setRange(0, 20)
        self.mtf_screen_count.setValue(3)
        self.classic_form = QComboBox()
        for form in CLASSIC_FORMS.values():
            self.classic_form.addItem(form.label, form.key)
        self.classic_form.currentIndexChanged.connect(self._refresh_variable_count)
        self.manufacturer = QComboBox()
        self.manufacturer.addItem("全メーカー", "")
        for manufacturer in self.repository.filter_values("manufacturer"):
            self.manufacturer.addItem(manufacturer, manufacturer)
        self.allow_orientation = QCheckBox("表裏を探索")
        self.allow_orientation.setChecked(True)
        self.allow_order = QCheckBox("順序を探索")
        self.allow_order.setChecked(True)
        self.allow_stop_search = QCheckBox("絞り面を探索")
        self.allow_stop_search.setChecked(True)
        self.minimum_elements = QSpinBox()
        self.minimum_elements.setRange(1, 20)
        self.minimum_elements.setValue(max(1, len(self.design.elements) - 1))
        self.maximum_elements = QSpinBox()
        self.maximum_elements.setRange(1, 20)
        self.maximum_elements.setValue(min(20, max(len(self.design.elements) + 2, 4)))
        self.minimum_elements.valueChanged.connect(self.maximum_elements.setMinimum)
        self.maximum_elements.valueChanged.connect(self.minimum_elements.setMaximum)
        discrete_grid.addWidget(QLabel("構成候補の評価回数"), 0, 0)
        discrete_grid.addWidget(self.discrete_evaluations, 0, 1)
        discrete_grid.addWidget(QLabel("各位置の部品候補数"), 0, 2)
        discrete_grid.addWidget(self.candidates_per_slot, 0, 3)
        discrete_grid.addWidget(QLabel("メーカー"), 1, 0)
        discrete_grid.addWidget(self.manufacturer, 1, 1)
        discrete_grid.addWidget(self.allow_orientation, 1, 2)
        discrete_grid.addWidget(self.allow_order, 1, 3)
        discrete_grid.addWidget(QLabel("古典型"), 2, 0)
        discrete_grid.addWidget(self.classic_form, 2, 1)
        discrete_grid.addWidget(QLabel("保持する上位案"), 2, 2)
        discrete_grid.addWidget(self.result_count, 2, 3)
        discrete_grid.addWidget(QLabel("MTF詳細評価案"), 3, 2)
        discrete_grid.addWidget(self.mtf_screen_count, 3, 3)
        discrete_grid.addWidget(self.allow_stop_search, 3, 0, 1, 2)
        discrete_grid.addWidget(QLabel("部品数範囲"), 4, 0)
        discrete_grid.addWidget(self.minimum_elements, 4, 1)
        discrete_grid.addWidget(QLabel("～"), 4, 2)
        discrete_grid.addWidget(self.maximum_elements, 4, 3)
        self.search_scope.currentIndexChanged.connect(self._search_scope_changed)

        variable_group = QGroupBox("連続最適化で変更する値")
        variable_layout = QHBoxLayout(variable_group)
        self.vary_radii = QCheckBox("曲率半径")
        self.vary_radii.setChecked(True)
        self.vary_thicknesses = QCheckBox("レンズ厚")
        self.vary_air_gaps = QCheckBox("空気間隔")
        self.vary_air_gaps.setChecked(True)
        self.vary_image_plane = QCheckBox("像面位置")
        self.vary_image_plane.setChecked(True)
        for widget in (self.vary_radii, self.vary_thicknesses, self.vary_air_gaps, self.vary_image_plane):
            variable_layout.addWidget(widget)
            widget.toggled.connect(self._refresh_variable_count)
        variable_layout.addStretch(1)
        merit_group = QGroupBox("性能の配分")
        merit_grid = QGridLayout(merit_group)
        self.efl_weight = self._weight_spin(3.0)
        self.bfl_weight = self._weight_spin(2.0)
        self.spot_weight = self._weight_spin(10.0)
        self.longitudinal_weight = self._weight_spin(2.0)
        self.longitudinal_tolerance = self._value_spin(0.1, 100000.0, 100.0, " µm", 1)
        self.longitudinal_hard = QCheckBox("超過案を除外")
        self.distortion_weight = self._weight_spin(1.0)
        self.track_weight = self._weight_spin(1.0)
        self.merit_preset = QComboBox()
        self.merit_preset.addItem("バランス", "balanced")
        self.merit_preset.addItem("解像重視", "resolution")
        self.merit_preset.addItem("縦収差重視", "longitudinal")
        self.merit_preset.addItem("歪曲重視", "distortion")
        self.merit_preset.addItem("カスタム", "custom")
        self.merit_preset.currentIndexChanged.connect(self._apply_merit_preset)
        for widget in (
            self.efl_weight,
            self.bfl_weight,
            self.spot_weight,
            self.longitudinal_weight,
            self.distortion_weight,
            self.track_weight,
            self.longitudinal_tolerance,
        ):
            widget.valueChanged.connect(self._mark_custom_merit)
        merit_grid.addWidget(QLabel("評価プリセット"), 0, 0)
        merit_grid.addWidget(self.merit_preset, 0, 1, 1, 2)
        merit_grid.addWidget(QLabel("評価項目"), 1, 0)
        merit_grid.addWidget(QLabel("相対重み（0で無視）"), 1, 1)
        merit_grid.addWidget(QLabel("目標・許容値"), 1, 2)
        merit_grid.addWidget(QLabel("必須条件"), 1, 3)
        merit_grid.addWidget(QLabel("焦点距離"), 2, 0)
        merit_grid.addWidget(self.efl_weight, 2, 1)
        merit_grid.addWidget(QLabel("バックフォーカス"), 3, 0)
        merit_grid.addWidget(self.bfl_weight, 3, 1)
        merit_grid.addWidget(QLabel("多視野・多波長RMSスポット"), 4, 0)
        merit_grid.addWidget(self.spot_weight, 4, 1)
        merit_grid.addWidget(QLabel("縦収差RMS（軸上・全波長）"), 5, 0)
        merit_grid.addWidget(self.longitudinal_weight, 5, 1)
        merit_grid.addWidget(self.longitudinal_tolerance, 5, 2)
        merit_grid.addWidget(self.longitudinal_hard, 5, 3)
        merit_grid.addWidget(QLabel("歪曲"), 6, 0)
        merit_grid.addWidget(self.distortion_weight, 6, 1)
        merit_grid.addWidget(QLabel("全長超過"), 7, 0)
        merit_grid.addWidget(self.track_weight, 7, 1)
        self.longitudinal_tolerance.setToolTip("縦収差図の焦点ずれをRMS化した許容値")

        self.configuration_tabs = QTabWidget()
        goal_page = QWidget()
        goal_layout = QVBoxLayout(goal_page)
        goal_layout.addWidget(target_group)
        goal_layout.addStretch(1)
        search_page = QWidget()
        search_layout = QVBoxLayout(search_page)
        search_layout.addWidget(self.discrete_group)
        search_layout.addWidget(variable_group)
        search_layout.addStretch(1)
        quality_page = QWidget()
        quality_layout = QVBoxLayout(quality_page)
        quality_layout.addWidget(merit_group)
        quality_layout.addStretch(1)
        self.configuration_tabs.addTab(goal_page, "1  設計目標")
        self.configuration_tabs.addTab(search_page, "2  変更範囲")
        self.configuration_tabs.addTab(quality_page, "3  画質目標")
        layout.addWidget(self.configuration_tabs, 1)

        controls = QHBoxLayout()
        self.start_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "開始")
        self.stop_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop), "停止")
        self.apply_button = QPushButton("選択案を設計へ適用")
        self.stop_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self._controller.cancel)
        self.apply_button.clicked.connect(self._apply_best)
        self.minimum_elements.valueChanged.connect(self._refresh_variable_count)
        self.maximum_elements.valueChanged.connect(self._refresh_variable_count)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.apply_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        controls.addWidget(self.progress_bar, 1)
        layout.addLayout(controls)

        self.status = QLabel("待機中")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["項目", "開始時", "目標", "最良案"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().hide()
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        result_layout.addWidget(self.result_table)
        central.addTab(settings_page, "自動設計")
        central.addTab(self._build_candidate_page(), "候補比較")
        central.addTab(result_page, "結果概要")
        self.setCentralWidget(central)
        self._update_bfl_controls()
        self._search_scope_changed()

    def _build_candidate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.candidate_table = QTableWidget(0, 13)
        self.candidate_table.setHorizontalHeaderLabels(
            [
                "順位", "段階", "型", "制約", "スコア", "EFL", "F値", "BFL",
                "スポットRMS", "縦収差RMS", "MTF40", "歪曲", "全長",
            ]
        )
        self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidate_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidate_table.verticalHeader().hide()
        self.candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setStretchLastSection(True)
        self.candidate_table.currentCellChanged.connect(self._candidate_selected)
        splitter.addWidget(self.candidate_table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 6, 0, 0)
        self.candidate_summary = QLabel("探索後、候補を選択すると構成を比較できます")
        self.candidate_summary.setWordWrap(True)
        detail_layout.addWidget(self.candidate_summary)
        detail_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.candidate_preview = LensLayoutView(editable=False)
        self.candidate_preview.setMinimumHeight(240)
        detail_splitter.addWidget(self.candidate_preview)
        self.parts_table = QTableWidget(0, 6)
        self.parts_table.setHorizontalHeaderLabels(["位置", "メーカー", "型番", "形状", "向き", "後方間隔"])
        self.parts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.parts_table.verticalHeader().hide()
        self.parts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.parts_table.horizontalHeader().setStretchLastSection(True)
        detail_splitter.addWidget(self.parts_table)
        detail_splitter.setSizes([470, 410])
        detail_layout.addWidget(detail_splitter, 1)
        self.apply_candidate_button = QPushButton("この候補を設計へ適用")
        self.apply_candidate_button.setEnabled(False)
        self.apply_candidate_button.clicked.connect(self._apply_best)
        detail_layout.addWidget(self.apply_candidate_button)
        splitter.addWidget(detail)
        splitter.setSizes([260, 480])
        layout.addWidget(splitter)
        return page

    @staticmethod
    def _weight_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1000.0)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def _value_spin(minimum: float, maximum: float, value: float, suffix: str, decimals: int = 2) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        return spin

    def _apply_merit_preset(self, _index: int | None = None) -> None:
        presets = {
            "balanced": (3.0, 2.0, 10.0, 2.0, 1.0, 1.0, 100.0),
            "resolution": (3.0, 2.0, 16.0, 3.0, 1.0, 1.0, 100.0),
            "longitudinal": (3.0, 2.0, 8.0, 12.0, 1.0, 1.0, 50.0),
            "distortion": (3.0, 2.0, 7.0, 2.0, 10.0, 1.0, 100.0),
        }
        values = presets.get(str(self.merit_preset.currentData()))
        if values is None:
            return
        widgets = (
            self.efl_weight,
            self.bfl_weight,
            self.spot_weight,
            self.longitudinal_weight,
            self.distortion_weight,
            self.track_weight,
            self.longitudinal_tolerance,
        )
        self._applying_merit_preset = True
        try:
            for widget, value in zip(widgets, values, strict=True):
                widget.setValue(value)
        finally:
            self._applying_merit_preset = False

    def _mark_custom_merit(self, _value: float | None = None) -> None:
        if self._applying_merit_preset:
            return
        custom_index = self.merit_preset.findData("custom")
        if custom_index >= 0:
            self.merit_preset.setCurrentIndex(custom_index)

    def set_design(self, design: OpticalDesign) -> None:
        if self._running:
            return
        self.design = deepcopy(design)
        self.target_efl.setValue(design.settings.focal_length_target_mm)
        self.target_f_number.setValue(design.settings.f_number_target)
        self.target_bfl.setValue(design.settings.back_focus_target_mm)
        self.minimum_bfl.setValue(design.settings.back_focus_target_mm)
        self.minimum_elements.setValue(min(self.minimum_elements.value(), len(design.elements)))
        self.maximum_elements.setValue(max(self.maximum_elements.value(), len(design.elements)))
        self.best_design = None
        self.candidate_payloads = []
        self.candidate_table.setRowCount(0)
        self.parts_table.setRowCount(0)
        self.candidate_preview.set_design(design)
        self.candidate_summary.setText("探索後、候補を選択すると構成を比較できます")
        self.apply_button.setEnabled(False)
        self.apply_candidate_button.setEnabled(False)
        self._refresh_variable_count()
        self.status.setText("設計を更新しました")

    def _options(self) -> dict:
        return normalized_automatic_options(
            {
                "method": self.method.currentData(),
                "time_limit_seconds": self.time_limit.value(),
                "max_evaluations": self.max_evaluations.value(),
                "vary_radii": self.vary_radii.isChecked(),
                "vary_thicknesses": self.vary_thicknesses.isChecked(),
                "vary_air_gaps": self.vary_air_gaps.isChecked(),
                "vary_image_plane": self.vary_image_plane.isChecked(),
                "efl_weight": self.efl_weight.value(),
                "bfl_weight": self.bfl_weight.value(),
                "spot_weight": self.spot_weight.value(),
                "longitudinal_weight": self.longitudinal_weight.value(),
                "longitudinal_tolerance_um": self.longitudinal_tolerance.value(),
                "longitudinal_hard": self.longitudinal_hard.isChecked(),
                "distortion_weight": self.distortion_weight.value(),
                "track_weight": self.track_weight.value(),
                "target_efl_mm": self.target_efl.value(),
                "efl_tolerance_mm": self.efl_tolerance.value(),
                "efl_hard": self.efl_hard.isChecked(),
                "target_f_number": self.target_f_number.value(),
                "bfl_constraint": self.bfl_constraint.currentData(),
                "target_bfl_mm": self.target_bfl.value(),
                "minimum_bfl_mm": self.minimum_bfl.value(),
                "maximum_bfl_mm": self.maximum_bfl.value(),
                "bfl_tolerance_mm": self.bfl_tolerance.value(),
                "bfl_hard": self.bfl_hard.isChecked(),
                "maximum_total_track_mm": self.maximum_total_track.value() if self.track_limit_enabled.isChecked() else None,
                "track_hard": self.track_limit_enabled.isChecked() and self.track_hard.isChecked(),
                "discrete_search": self.search_scope.currentData() in {"discrete", "topology", "classic"},
                "discrete_evaluations": self.discrete_evaluations.value(),
                "result_count": self.result_count.value(),
                "mtf_screen_count": min(self.mtf_screen_count.value(), self.result_count.value()),
                "classic_form": self.classic_form.currentData() if self.search_scope.currentData() == "classic" else "",
                "allow_orientation_search": self.allow_orientation.isChecked(),
                "allow_order_search": self.allow_order.isChecked() and self.search_scope.currentData() in {"discrete", "topology"},
                "allow_element_count_search": self.search_scope.currentData() == "topology",
                "allow_stop_search": self.allow_stop_search.isChecked() and self.search_scope.currentData() == "topology",
                "minimum_element_count": self.minimum_elements.value(),
                "maximum_element_count": self.maximum_elements.value(),
            }
        )

    def _update_bfl_controls(self) -> None:
        mode = self.bfl_constraint.currentData()
        self.target_bfl_label.setVisible(mode == "target")
        self.target_bfl.setVisible(mode == "target")
        self.minimum_bfl_label.setVisible(mode in {"minimum", "range"})
        self.minimum_bfl.setVisible(mode in {"minimum", "range"})
        self.maximum_bfl_label.setVisible(mode == "range")
        self.maximum_bfl.setVisible(mode == "range")
        self.bfl_tolerance_label.setVisible(mode == "target")
        self.bfl_tolerance.setVisible(mode == "target")
        self.bfl_hard.setEnabled(mode != "off")

    def _search_scope_changed(self) -> None:
        mode = self.search_scope.currentData()
        self.discrete_group.setEnabled(mode in {"discrete", "topology", "classic"})
        self.classic_form.setEnabled(mode == "classic")
        self.allow_order.setEnabled(mode in {"discrete", "topology"})
        self.allow_stop_search.setEnabled(mode == "topology")
        self.minimum_elements.setEnabled(mode == "topology")
        self.maximum_elements.setEnabled(mode == "topology")
        self._refresh_variable_count()

    def _candidate_pool(self) -> list[list[dict]]:
        if self.search_scope.currentData() == "classic":
            pool, _ = self._classic_candidate_payload()
            return pool
        pool: list[list[dict]] = []
        minimum_aperture = self.target_efl.value() / max(self.target_f_number.value(), 0.5)
        for element in self.design.elements:
            candidates = [deepcopy(element)]
            if not element.element_locked:
                maximum_diameter = self.design.settings.max_outer_diameter_mm
                if element.diameter_max_mm is not None:
                    maximum_diameter = min(maximum_diameter, element.diameter_max_mm)
                products = self.repository.query_products(
                    power=self._element_power(element),
                    manufacturer=str(self.manufacturer.currentData()),
                    min_diameter_mm=element.diameter_min_mm,
                    max_diameter_mm=maximum_diameter,
                    min_clear_aperture_mm=minimum_aperture,
                    target_efl_mm=self.target_efl.value(),
                    limit=self.candidates_per_slot.value(),
                )
                seen = {element.catalog_product_id}
                for product in products:
                    if product.id in seen:
                        continue
                    candidate = self.repository.element_from_product(product.id)
                    candidate.gap_after_mm = element.gap_after_mm
                    candidate.gap_locked = element.gap_locked
                    candidate.gap_min_mm = element.gap_min_mm
                    candidate.gap_max_mm = element.gap_max_mm
                    candidates.append(candidate)
                    seen.add(product.id)
            pool.append([asdict(candidate) for candidate in candidates])
        return pool

    def _topology_pool(self) -> list[dict]:
        minimum_aperture = self.target_efl.value() / max(self.target_f_number.value(), 0.5)
        maximum_diameter = self.design.settings.max_outer_diameter_mm
        manufacturer = str(self.manufacturer.currentData())
        products = []
        for power in ("positive", "negative"):
            products.extend(
                self.repository.query_products(
                    power=power,
                    manufacturer=manufacturer,
                    max_diameter_mm=maximum_diameter,
                    min_clear_aperture_mm=minimum_aperture,
                    target_efl_mm=self.target_efl.value(),
                    limit=self.candidates_per_slot.value(),
                )
            )
        unique = []
        seen: set[int] = set()
        for product in products:
            if product.id in seen:
                continue
            unique.append(asdict(self.repository.element_from_product(product.id)))
            seen.add(product.id)
        return unique

    def _classic_candidate_payload(self) -> tuple[list[list[dict]], OpticalDesign]:
        form = classic_form(str(self.classic_form.currentData()))
        minimum_aperture = self.target_efl.value() / max(self.target_f_number.value(), 0.5)
        manufacturer = str(self.manufacturer.currentData())
        pool_elements: list[list[LensElement]] = []
        for slot in form.slots:
            target_part_efl = self.target_efl.value() * slot.target_efl_scale
            products = []
            for shape in slot.shapes:
                products.extend(
                    self.repository.query_products(
                        shape=shape,
                        power=slot.power,
                        manufacturer=manufacturer,
                        max_diameter_mm=self.design.settings.max_outer_diameter_mm,
                        min_clear_aperture_mm=minimum_aperture,
                        target_efl_mm=target_part_efl,
                        limit=max(self.candidates_per_slot.value(), 4),
                    )
                )
            products.sort(
                key=lambda product: (
                    abs(abs(product.effective_focal_length_mm or 1e9) - target_part_efl),
                    -(product.clear_aperture_mm or 0.0),
                    product.part_number,
                )
            )
            unique_products = []
            seen: set[int] = set()
            for product in products:
                if product.id in seen:
                    continue
                unique_products.append(product)
                seen.add(product.id)
                if len(unique_products) >= self.candidates_per_slot.value():
                    break
            if not unique_products:
                raise ValueError(f"{form.label}: {slot.label}に使えるカタログ部品がありません")
            pool_elements.append([self.repository.element_from_product(product.id) for product in unique_products])

        image_distance = self._classic_image_distance()
        seed = build_classic_design(
            self.design,
            form.key,
            [slot[0] for slot in pool_elements],
            self.target_efl.value(),
            image_distance,
        )
        pool = [[asdict(element) for element in slot] for slot in pool_elements]
        return pool, seed

    def _classic_image_distance(self) -> float:
        mode = self.bfl_constraint.currentData()
        if mode == "target":
            return self.target_bfl.value()
        if mode == "minimum":
            return self.minimum_bfl.value()
        if mode == "range":
            return (self.minimum_bfl.value() + self.maximum_bfl.value()) / 2.0
        if self.design.elements:
            return self.design.elements[-1].gap_after_mm
        return self.design.settings.back_focus_target_mm

    @staticmethod
    def _element_power(element) -> str:
        shape = element.shape.lower()
        if "concave" in shape or "negative" in shape or shape in {"pcv", "dcv"}:
            return "negative"
        return "positive"

    def _refresh_variable_count(self) -> None:
        mode = self.search_scope.currentData()
        count = len(variable_candidates(self.design, self._options()))
        if mode == "classic":
            form = classic_form(str(self.classic_form.currentData()))
            self.variable_count.setText(f"{form.label} / {len(form.slots)}部品 / 離散+連続")
        elif mode == "topology":
            self.variable_count.setText(
                f"自由構成 {self.minimum_elements.value()}～{self.maximum_elements.value()}部品 / 離散+連続"
            )
        else:
            self.variable_count.setText(f"連続 {count} 個" + (" / 離散あり" if mode == "discrete" else ""))
        can_start = count > 0 or mode in {"classic", "topology"} or (
            mode == "discrete" and bool(self.design.elements)
        )
        self.start_button.setEnabled(can_start and not self._running)

    def start(self) -> None:
        self._generation += 1
        self.best_design = None
        self.candidate_payloads = []
        self.apply_button.setEnabled(False)
        self.apply_candidate_button.setEnabled(False)
        self.result_table.setRowCount(0)
        self.candidate_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.status.setText("Optilandで実光線を評価しています")
        options = self._options()
        if options["discrete_search"]:
            try:
                if options["classic_form"]:
                    options["candidate_pool"], seed = self._classic_candidate_payload()
                    options["classic_seed_design"] = seed.to_dict()
                elif options["allow_element_count_search"]:
                    options["topology_pool"] = self._topology_pool()
                else:
                    options["candidate_pool"] = self._candidate_pool()
            except (KeyError, TypeError, ValueError) as exc:
                self.status.setText(str(exc))
                return
        self._controller.start(self._generation, self.design, options)

    @Slot(int, object)
    def _progress(self, generation: int, result: dict) -> None:
        if generation != self._generation:
            return
        elapsed = float(result.get("elapsed_seconds", 0.0))
        limit = max(float(result.get("time_limit_seconds", 1.0)), 1.0)
        phase = str(result.get("phase", "連続最適化"))
        self.progress_bar.setValue(min(int(elapsed / limit * 1000), 1000))
        self.status.setText(
            f"{phase}: 評価 {int(result.get('evaluations', 0))} 回 / "
            f"最良スコア {float(result.get('best_score', 0.0)):.5g} / {elapsed:.1f} 秒"
        )

    @Slot(int, object)
    def _finished(self, generation: int, result: dict) -> None:
        if generation != self._generation:
            return
        if not result.get("valid"):
            self.status.setText(str(result.get("error", "自動設計に失敗しました")))
            return
        self.best_design = OpticalDesign.from_dict(result["design"])
        self.apply_button.setEnabled(True)
        self.progress_bar.setValue(1000)
        self.status.setText(
            f"完了: {result.get('evaluations', 0)} 回 / {float(result.get('elapsed_seconds', 0)):.1f} 秒 / {result.get('method', '')}"
        )
        metrics = result.get("metrics", {})
        targets = result.get("targets", {})
        bfl_target = self._bfl_target_text(targets)
        track_target = (
            f"<= {targets['maximum_total_track_mm']:.6g}"
            if targets.get("maximum_total_track_mm") is not None
            else "制約なし"
        )
        rows = [
            ("評価スコア", result.get("initial_score"), 0.0, result.get("best_score")),
            ("実効焦点距離 [mm]", None, targets.get("effective_focal_length_mm"), metrics.get("effective_focal_length_mm")),
            ("F値", self.design.settings.f_number_target, targets.get("f_number"), metrics.get("image_f_number")),
            ("像面位置 [mm]", self.design.elements[-1].gap_after_mm, bfl_target, metrics.get("image_distance_mm")),
            ("最大RMSスポット [µm]", None, None, metrics.get("maximum_rms_spot_um")),
            (
                "縦収差RMS [µm]",
                None,
                f"<= {targets.get('longitudinal_tolerance_um', 0):.6g}",
                metrics.get("longitudinal_rms_um"),
            ),
            ("最大縦収差 [µm]", None, None, metrics.get("maximum_longitudinal_aberration_um")),
            ("軸上色収差 [µm]", None, None, metrics.get("axial_color_um")),
            ("全長 [mm]", None, track_target, metrics.get("total_track_mm")),
            ("Airy半径 [µm]", None, None, metrics.get("diffraction_airy_radius_um")),
        ]
        changes = result.get("changes", [])
        rows.extend((change.get("label"), change.get("before"), None, change.get("after")) for change in changes)
        self.result_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                text = "-" if value is None else f"{value:.6g}" if isinstance(value, (int, float)) else str(value)
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.result_table.setItem(row, column, item)
        candidates = list(result.get("candidates", []))
        if not candidates:
            candidates = [
                {
                    "rank": 1,
                    "stage": "continuous_optimized",
                    "score": result.get("best_score"),
                    "design": result["design"],
                    "metrics": metrics,
                    "topology": result.get("topology"),
                    "parts": self._parts_from_design(self.best_design),
                }
            ]
        self._populate_candidates(candidates)
        self.tabs.setCurrentIndex(1)

    def _populate_candidates(self, candidates: list[dict]) -> None:
        self.candidate_payloads = candidates
        self.candidate_table.blockSignals(True)
        self.candidate_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            metrics = candidate.get("metrics", {})
            topology = candidate.get("topology") or {}
            stage = "連続最適化" if candidate.get("stage") == "continuous_optimized" else "離散評価"
            values = [
                candidate.get("rank", row + 1),
                stage,
                topology.get("label", "自由構成"),
                "適合" if candidate.get("constraints_satisfied", True) else "未達",
                candidate.get("score"),
                metrics.get("effective_focal_length_mm"),
                metrics.get("image_f_number"),
                metrics.get("image_distance_mm"),
                metrics.get("maximum_rms_spot_um"),
                metrics.get("longitudinal_rms_um"),
                metrics.get("mtf40_min"),
                metrics.get("edge_distortion_percent"),
                metrics.get("total_track_mm"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(self._display_value(value))
                if column not in {1, 2, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.candidate_table.setItem(row, column, item)
        self.candidate_table.blockSignals(False)
        if candidates:
            self.candidate_table.setCurrentCell(0, 0)

    @Slot(int, int, int, int)
    def _candidate_selected(self, current_row: int, _current_column: int, _previous_row: int, _previous_column: int) -> None:
        if not 0 <= current_row < len(self.candidate_payloads):
            return
        candidate = self.candidate_payloads[current_row]
        design = OpticalDesign.from_dict(candidate["design"])
        self.best_design = design
        self.candidate_preview.set_design(design)
        topology = candidate.get("topology") or {}
        metrics = candidate.get("metrics", {})
        form_name = topology.get("label", "自由構成")
        stage = "連続最適化済み" if candidate.get("stage") == "continuous_optimized" else "離散粗評価"
        self.candidate_summary.setText(
            f"候補 {current_row + 1} / {len(self.candidate_payloads)}  {form_name}  {stage}  "
            f"EFL {self._display_value(metrics.get('effective_focal_length_mm'))} mm  "
            f"BFL {self._display_value(metrics.get('image_distance_mm'))} mm  "
            f"縦収差RMS {self._display_value(metrics.get('longitudinal_rms_um'))} µm  "
            f"MTF40 {self._display_value(metrics.get('mtf40_min'))}"
        )
        parts = candidate.get("parts") or self._parts_from_design(design)
        self.parts_table.setRowCount(len(parts))
        for row, part in enumerate(parts):
            values = [
                part.get("position", row + 1),
                part.get("manufacturer", ""),
                part.get("part_number") or part.get("name", ""),
                part.get("shape", ""),
                "反転" if part.get("orientation_reversed") else "正向き",
                part.get("gap_after_mm"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(self._display_value(value))
                if column in {0, 5}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.parts_table.setItem(row, column, item)
        self.apply_button.setEnabled(True)
        self.apply_candidate_button.setEnabled(True)

    @staticmethod
    def _parts_from_design(design: OpticalDesign) -> list[dict]:
        return [
            {
                "position": index + 1,
                "manufacturer": element.manufacturer,
                "part_number": element.part_number,
                "name": element.name,
                "shape": element.shape,
                "orientation_reversed": element.orientation_reversed,
                "gap_after_mm": element.gap_after_mm,
            }
            for index, element in enumerate(design.elements)
        ]

    @staticmethod
    def _display_value(value) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    @staticmethod
    def _bfl_target_text(targets: dict) -> str:
        mode = targets.get("bfl_constraint")
        if mode == "target":
            return f"{targets.get('target_bfl_mm', 0):.6g}"
        if mode == "minimum":
            return f">= {targets.get('minimum_bfl_mm', 0):.6g}"
        if mode == "range":
            return f"{targets.get('minimum_bfl_mm', 0):.6g} .. {targets.get('maximum_bfl_mm', 0):.6g}"
        return "制約なし"

    @Slot(bool)
    def _running_changed(self, running: bool) -> None:
        self._running = running
        mode = self.search_scope.currentData()
        can_start = bool(variable_candidates(self.design, self._options())) or mode in {"classic", "topology"} or (
            mode == "discrete" and bool(self.design.elements)
        )
        self.start_button.setEnabled(not running and can_start)
        self.stop_button.setEnabled(running)

    def _apply_best(self) -> None:
        if self.best_design is not None:
            self.applyRequested.emit(deepcopy(self.best_design))

    def shutdown(self) -> None:
        self._controller.shutdown()

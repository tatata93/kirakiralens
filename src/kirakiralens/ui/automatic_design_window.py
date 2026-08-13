from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..catalog.database import CatalogRepository
from ..domain import OpticalDesign
from ..optics.automatic_design import normalized_automatic_options, variable_candidates
from .automatic_design_controller import AutomaticDesignController


class AutomaticDesignWindow(QMainWindow):
    applyRequested = Signal(object)

    def __init__(self, design: OpticalDesign, repository_root: Path, parent=None):
        super().__init__(parent)
        self.design = deepcopy(design)
        self.repository = CatalogRepository(repository_root / "data" / "generated" / "edmund_catalog.sqlite3")
        self.best_design: OpticalDesign | None = None
        self._generation = 0
        self._running = False
        self._controller = AutomaticDesignController(repository_root / ".tmp" / "matplotlib", self)
        self._controller.progress.connect(self._progress)
        self._controller.finished.connect(self._finished)
        self._controller.runningChanged.connect(self._running_changed)
        self.setWindowTitle("自動設計 - KiraKiraLens")
        self.resize(900, 800)
        self.setMinimumSize(780, 700)
        self._build_ui()
        self._refresh_variable_count()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 12)

        setup = QGroupBox("探索")
        setup_layout = QGridLayout(setup)
        self.method = QComboBox()
        self.method.addItem("局所探索", "local")
        self.method.addItem("大域探索", "global")
        self.search_scope = QComboBox()
        self.search_scope.addItem("現在の構成を連続最適化", "continuous")
        self.search_scope.addItem("市販レンズを離散探索して連続最適化", "discrete")
        self.time_limit = QSpinBox()
        self.time_limit.setRange(1, 86400)
        self.time_limit.setSuffix(" 秒")
        self.time_limit.setValue(60)
        self.max_evaluations = QSpinBox()
        self.max_evaluations.setRange(10, 1000000)
        self.max_evaluations.setValue(500)
        self.variable_count = QLabel("-")
        setup_layout.addWidget(QLabel("探索対象"), 0, 0)
        setup_layout.addWidget(self.search_scope, 0, 1, 1, 3)
        setup_layout.addWidget(QLabel("連続探索方式"), 1, 0)
        setup_layout.addWidget(self.method, 1, 1)
        setup_layout.addWidget(QLabel("時間上限"), 1, 2)
        setup_layout.addWidget(self.time_limit, 1, 3)
        setup_layout.addWidget(QLabel("連続評価回数"), 2, 0)
        setup_layout.addWidget(self.max_evaluations, 2, 1)
        setup_layout.addWidget(QLabel("可変数"), 2, 2)
        setup_layout.addWidget(self.variable_count, 2, 3)
        layout.addWidget(setup)

        target_group = QGroupBox("数値目標")
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
        target_grid.addWidget(QLabel("焦点距離"), 0, 0)
        target_grid.addWidget(self.target_efl, 0, 1)
        target_grid.addWidget(QLabel("許容差"), 0, 2)
        target_grid.addWidget(self.efl_tolerance, 0, 3)
        target_grid.addWidget(self.efl_hard, 0, 4)
        target_grid.addWidget(QLabel("F値"), 1, 0)
        target_grid.addWidget(self.target_f_number, 1, 1)
        target_grid.addWidget(QLabel("BFL"), 2, 0)
        target_grid.addWidget(self.bfl_constraint, 2, 1)
        target_grid.addWidget(self.target_bfl, 2, 2)
        target_grid.addWidget(self.minimum_bfl, 2, 2)
        target_grid.addWidget(self.maximum_bfl, 2, 3)
        target_grid.addWidget(self.bfl_tolerance, 2, 3)
        target_grid.addWidget(self.bfl_hard, 2, 4)
        self.bfl_constraint.currentIndexChanged.connect(self._update_bfl_controls)
        layout.addWidget(target_group)

        self.discrete_group = QGroupBox("市販レンズ探索")
        discrete_grid = QGridLayout(self.discrete_group)
        self.discrete_evaluations = QSpinBox()
        self.discrete_evaluations.setRange(1, 100000)
        self.discrete_evaluations.setValue(80)
        self.candidates_per_slot = QSpinBox()
        self.candidates_per_slot.setRange(1, 100)
        self.candidates_per_slot.setValue(8)
        self.manufacturer = QComboBox()
        self.manufacturer.addItem("全メーカー", "")
        for manufacturer in self.repository.filter_values("manufacturer"):
            self.manufacturer.addItem(manufacturer, manufacturer)
        self.allow_orientation = QCheckBox("表裏を探索")
        self.allow_orientation.setChecked(True)
        self.allow_order = QCheckBox("順序を探索")
        self.allow_order.setChecked(True)
        discrete_grid.addWidget(QLabel("離散評価回数"), 0, 0)
        discrete_grid.addWidget(self.discrete_evaluations, 0, 1)
        discrete_grid.addWidget(QLabel("各位置の候補数"), 0, 2)
        discrete_grid.addWidget(self.candidates_per_slot, 0, 3)
        discrete_grid.addWidget(QLabel("メーカー"), 1, 0)
        discrete_grid.addWidget(self.manufacturer, 1, 1)
        discrete_grid.addWidget(self.allow_orientation, 1, 2)
        discrete_grid.addWidget(self.allow_order, 1, 3)
        layout.addWidget(self.discrete_group)
        self.search_scope.currentIndexChanged.connect(self._search_scope_changed)

        variable_group = QGroupBox("動かす項目")
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
        layout.addWidget(variable_group)

        merit_group = QGroupBox("評価の優先度")
        merit_form = QFormLayout(merit_group)
        self.efl_weight = self._weight_spin(3.0)
        self.bfl_weight = self._weight_spin(2.0)
        self.spot_weight = self._weight_spin(10.0)
        self.distortion_weight = self._weight_spin(1.0)
        merit_form.addRow("焦点距離", self.efl_weight)
        merit_form.addRow("像面位置", self.bfl_weight)
        merit_form.addRow("多視野・多波長RMSスポット", self.spot_weight)
        merit_form.addRow("歪曲", self.distortion_weight)
        layout.addWidget(merit_group)

        controls = QHBoxLayout()
        self.start_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "開始")
        self.stop_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop), "停止")
        self.apply_button = QPushButton("最良案を設計へ適用")
        self.stop_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self._controller.cancel)
        self.apply_button.clicked.connect(self._apply_best)
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
        layout.addWidget(self.result_table, 1)
        self.setCentralWidget(central)
        self._update_bfl_controls()
        self._search_scope_changed()

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

    def set_design(self, design: OpticalDesign) -> None:
        if self._running:
            return
        self.design = deepcopy(design)
        self.target_efl.setValue(design.settings.focal_length_target_mm)
        self.target_f_number.setValue(design.settings.f_number_target)
        self.target_bfl.setValue(design.settings.back_focus_target_mm)
        self.minimum_bfl.setValue(design.settings.back_focus_target_mm)
        self.best_design = None
        self.apply_button.setEnabled(False)
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
                "distortion_weight": self.distortion_weight.value(),
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
                "discrete_search": self.search_scope.currentData() == "discrete",
                "discrete_evaluations": self.discrete_evaluations.value(),
                "allow_orientation_search": self.allow_orientation.isChecked(),
                "allow_order_search": self.allow_order.isChecked(),
            }
        )

    def _update_bfl_controls(self) -> None:
        mode = self.bfl_constraint.currentData()
        self.target_bfl.setVisible(mode == "target")
        self.minimum_bfl.setVisible(mode in {"minimum", "range"})
        self.maximum_bfl.setVisible(mode == "range")
        self.bfl_tolerance.setVisible(mode == "target")
        self.bfl_hard.setEnabled(mode != "off")

    def _search_scope_changed(self) -> None:
        self.discrete_group.setEnabled(self.search_scope.currentData() == "discrete")
        self._refresh_variable_count()

    def _candidate_pool(self) -> list[list[dict]]:
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

    @staticmethod
    def _element_power(element) -> str:
        shape = element.shape.lower()
        if "concave" in shape or "negative" in shape or shape in {"pcv", "dcv"}:
            return "negative"
        return "positive"

    def _refresh_variable_count(self) -> None:
        count = len(variable_candidates(self.design, self._options()))
        discrete = self.search_scope.currentData() == "discrete"
        self.variable_count.setText(f"連続 {count} 個" + (" / 離散あり" if discrete else ""))
        self.start_button.setEnabled((count > 0 or (discrete and bool(self.design.elements))) and not self._running)

    def start(self) -> None:
        self._generation += 1
        self.best_design = None
        self.apply_button.setEnabled(False)
        self.result_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.status.setText("Optilandで実光線を評価しています")
        options = self._options()
        if options["discrete_search"]:
            options["candidate_pool"] = self._candidate_pool()
        self._controller.start(self._generation, self.design, options)

    @Slot(int, object)
    def _progress(self, generation: int, result: dict) -> None:
        if generation != self._generation:
            return
        elapsed = float(result.get("elapsed_seconds", 0.0))
        limit = max(float(result.get("time_limit_seconds", 1.0)), 1.0)
        self.progress_bar.setValue(min(int(elapsed / limit * 1000), 1000))
        self.status.setText(
            f"評価 {int(result.get('evaluations', 0))} 回 / 最良スコア {float(result.get('best_score', 0.0)):.5g} / {elapsed:.1f} 秒"
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
        rows = [
            ("評価スコア", result.get("initial_score"), 0.0, result.get("best_score")),
            ("実効焦点距離 [mm]", None, targets.get("effective_focal_length_mm"), metrics.get("effective_focal_length_mm")),
            ("F値", self.design.settings.f_number_target, targets.get("f_number"), metrics.get("image_f_number")),
            ("像面位置 [mm]", self.design.elements[-1].gap_after_mm, bfl_target, metrics.get("image_distance_mm")),
            ("最大RMSスポット [µm]", None, None, metrics.get("maximum_rms_spot_um")),
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
        can_start = bool(variable_candidates(self.design, self._options())) or (
            self.search_scope.currentData() == "discrete" and bool(self.design.elements)
        )
        self.start_button.setEnabled(not running and can_start)
        self.stop_button.setEnabled(running)

    def _apply_best(self) -> None:
        if self.best_design is not None:
            self.applyRequested.emit(deepcopy(self.best_design))

    def shutdown(self) -> None:
        self._controller.shutdown()

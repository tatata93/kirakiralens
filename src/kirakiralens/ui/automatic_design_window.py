from __future__ import annotations

from copy import deepcopy
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

from ..domain import OpticalDesign
from ..optics.automatic_design import normalized_automatic_options, variable_candidates
from .automatic_design_controller import AutomaticDesignController


class AutomaticDesignWindow(QMainWindow):
    applyRequested = Signal(object)

    def __init__(self, design: OpticalDesign, repository_root: Path, parent=None):
        super().__init__(parent)
        self.design = deepcopy(design)
        self.best_design: OpticalDesign | None = None
        self._generation = 0
        self._running = False
        self._controller = AutomaticDesignController(repository_root / ".tmp" / "matplotlib", self)
        self._controller.progress.connect(self._progress)
        self._controller.finished.connect(self._finished)
        self._controller.runningChanged.connect(self._running_changed)
        self.setWindowTitle("自動設計 - KiraKiraLens")
        self.resize(820, 680)
        self.setMinimumSize(720, 600)
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
        self.time_limit = QSpinBox()
        self.time_limit.setRange(1, 86400)
        self.time_limit.setSuffix(" 秒")
        self.time_limit.setValue(60)
        self.max_evaluations = QSpinBox()
        self.max_evaluations.setRange(10, 1000000)
        self.max_evaluations.setValue(500)
        self.variable_count = QLabel("-")
        setup_layout.addWidget(QLabel("方式"), 0, 0)
        setup_layout.addWidget(self.method, 0, 1)
        setup_layout.addWidget(QLabel("時間上限"), 0, 2)
        setup_layout.addWidget(self.time_limit, 0, 3)
        setup_layout.addWidget(QLabel("評価回数上限"), 1, 0)
        setup_layout.addWidget(self.max_evaluations, 1, 1)
        setup_layout.addWidget(QLabel("可変数"), 1, 2)
        setup_layout.addWidget(self.variable_count, 1, 3)
        layout.addWidget(setup)

        variable_group = QGroupBox("動かす項目")
        variable_layout = QHBoxLayout(variable_group)
        self.vary_radii = QCheckBox("曲率半径")
        self.vary_radii.setChecked(True)
        self.vary_thicknesses = QCheckBox("レンズ厚")
        self.vary_air_gaps = QCheckBox("空気間隔")
        self.vary_air_gaps.setChecked(True)
        self.vary_image_plane = QCheckBox("像面位置")
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
        self.result_table = QTableWidget(0, 3)
        self.result_table.setHorizontalHeaderLabels(["項目", "開始時", "最良案"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().hide()
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.result_table, 1)
        self.setCentralWidget(central)

    @staticmethod
    def _weight_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1000.0)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    def set_design(self, design: OpticalDesign) -> None:
        if self._running:
            return
        self.design = deepcopy(design)
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
            }
        )

    def _refresh_variable_count(self) -> None:
        count = len(variable_candidates(self.design, self._options()))
        self.variable_count.setText(f"{count} 個")
        self.start_button.setEnabled(count > 0 and not self._running)

    def start(self) -> None:
        self._generation += 1
        self.best_design = None
        self.apply_button.setEnabled(False)
        self.result_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.status.setText("Optilandで実光線を評価しています")
        self._controller.start(self._generation, self.design, self._options())

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
        rows = [
            ("評価スコア", result.get("initial_score"), result.get("best_score")),
            ("実効焦点距離 [mm]", self.design.settings.focal_length_target_mm, metrics.get("effective_focal_length_mm")),
            ("像面位置 [mm]", self.design.elements[-1].gap_after_mm, metrics.get("image_distance_mm")),
            ("最大RMSスポット [µm]", None, metrics.get("maximum_rms_spot_um")),
            ("Airy半径 [µm]", None, metrics.get("diffraction_airy_radius_um")),
        ]
        changes = result.get("changes", [])
        rows.extend((change.get("label"), change.get("before"), change.get("after")) for change in changes)
        self.result_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                text = "-" if value is None else f"{value:.6g}" if isinstance(value, (int, float)) else str(value)
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.result_table.setItem(row, column, item)

    @Slot(bool)
    def _running_changed(self, running: bool) -> None:
        self._running = running
        self.start_button.setEnabled(not running and bool(variable_candidates(self.design, self._options())))
        self.stop_button.setEnabled(running)

    def _apply_best(self) -> None:
        if self.best_design is not None:
            self.applyRequested.emit(deepcopy(self.best_design))

    def shutdown(self) -> None:
        self._controller.shutdown()


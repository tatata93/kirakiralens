from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain import OpticalDesign
from ..optics.performance import normalized_options
from ..optics.signature import design_signature
from .performance_controller import PerformanceController
from .plot_widgets import PlotWidget


WAVELENGTH_COLORS = ["#386fa4", "#2b776d", "#b3423f", "#7a4d8b", "#d28b19"]
FIELD_COLORS = ["#2b776d", "#d28b19", "#b3423f", "#386fa4"]


class PerformanceWindow(QMainWindow):
    def __init__(self, design: OpticalDesign, repository_root: Path, parent=None):
        super().__init__(parent)
        self.design = deepcopy(design)
        self._design_signature = design_signature(self.design)
        self._generation = 0
        self._running = False
        self._result: dict | None = None
        self._controller = PerformanceController(repository_root / ".tmp" / "matplotlib", self)
        self._controller.finished.connect(self._analysis_finished)
        self._controller.statusChanged.connect(self._set_status)
        self._controller.runningChanged.connect(self._running_changed)
        self.setWindowTitle("性能評価 - KiraKiraLens")
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("解析品質"))
        self.quality = QComboBox()
        self.quality.addItem("設計設定", "design")
        self.quality.addItem("プレビュー", "preview")
        self.quality.addItem("標準", "standard")
        self.quality.addItem("高精度", "high")
        self.quality.setCurrentIndex(0)
        controls.addWidget(self.quality)
        controls.addWidget(QLabel("MTF上限"))
        self.maximum_frequency = QDoubleSpinBox()
        self.maximum_frequency.setRange(20, 400)
        self.maximum_frequency.setDecimals(0)
        self.maximum_frequency.setSingleStep(10)
        self.maximum_frequency.setSuffix(" lp/mm")
        self.maximum_frequency.setValue(80)
        controls.addWidget(self.maximum_frequency)
        self.run_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "解析実行")
        self.stop_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop), "停止")
        self.stop_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_analysis)
        self.stop_button.clicked.connect(self._controller.cancel)
        controls.addWidget(self.run_button)
        controls.addWidget(self.stop_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(150)
        self.progress.hide()
        controls.addWidget(self.progress)
        controls.addStretch(1)
        self.status_label = QLabel("未解析。設計変更だけでは性能計算を開始しません")
        controls.addWidget(self.status_label)
        layout.addLayout(controls)
        self.angle_label = QLabel("")
        self.angle_label.setStyleSheet("color: #59625f;")
        layout.addWidget(self.angle_label)

        self.tabs = QTabWidget()
        self._build_summary_tab()
        self._build_mtf_tab()
        self._build_spot_tab()
        self._build_ray_fan_tab()
        self._build_longitudinal_tab()
        self._build_field_tab()
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

    def _build_summary_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.summary_table = QTableWidget(0, 9)
        self.summary_table.setHorizontalHeaderLabels(
            ["像高", "MTF10 T", "MTF10 S", "MTF20 T", "MTF20 S", "MTF40 T", "MTF40 S", "RMSスポット", "80%半径"]
        )
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.summary_table.verticalHeader().hide()
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.summary_table.setMaximumHeight(190)
        layout.addWidget(self.summary_table)

        metrics = QGridLayout()
        self.metric_labels: dict[str, QLabel] = {}
        metric_names = [
            ("mtf40_min", "全像高の最低MTF40"),
            ("corner_rms_spot_um", "隅のRMSスポット"),
            ("max_ray_fan_rms_um", "横収差RMS最大"),
            ("edge_distortion_percent", "隅の歪曲"),
            ("edge_astigmatism_mm", "隅の非点隔差"),
            ("primary_longitudinal_spherical_um", "d線の縦球面収差"),
            ("axial_color_um", "軸上色収差"),
        ]
        for index, (key, name) in enumerate(metric_names):
            row, column = divmod(index, 3)
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(8, 5, 8, 5)
            label = QLabel(name)
            label.setStyleSheet("color: #59625f;")
            value = QLabel("-")
            value.setStyleSheet("font-size: 16px; font-weight: 600; color: #26322f;")
            group_layout.addWidget(label)
            group_layout.addWidget(value)
            metrics.addWidget(group, row, column)
            self.metric_labels[key] = value
        layout.addLayout(metrics)
        self.method_label = QLabel("解析方式: -")
        self.method_label.setStyleSheet("color: #59625f;")
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #9c4b32;")
        layout.addWidget(self.method_label)
        layout.addWidget(self.warning_label)
        layout.addStretch(1)
        self.tabs.addTab(page, "概要")

    def _build_mtf_tab(self) -> None:
        self.mtf_plot = PlotWidget()
        self.tabs.addTab(self.mtf_plot, "MTF")

    def _build_spot_tab(self) -> None:
        self.spot_content = QWidget()
        self.spot_layout = QHBoxLayout(self.spot_content)
        self.spot_plots: list[PlotWidget] = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.spot_content)
        self.tabs.addTab(scroll, "スポット")

    def _build_ray_fan_tab(self) -> None:
        self.ray_content = QWidget()
        self.ray_grid = QGridLayout(self.ray_content)
        self.ray_plots: list[tuple[PlotWidget, PlotWidget]] = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.ray_content)
        self.tabs.addTab(scroll, "横収差")

    def _build_longitudinal_tab(self) -> None:
        self.longitudinal_plot = PlotWidget()
        self.tabs.addTab(self.longitudinal_plot, "縦収差")

    def _build_field_tab(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)
        self.field_plot = PlotWidget()
        self.distortion_plot = PlotWidget()
        layout.addWidget(self.field_plot, 1)
        layout.addWidget(self.distortion_plot, 1)
        self.tabs.addTab(page, "像面・歪曲")

    def set_design(self, design: OpticalDesign) -> None:
        signature = design_signature(design)
        if signature == self._design_signature:
            return
        self.design = deepcopy(design)
        self._design_signature = signature
        self._generation += 1
        if self._running:
            self._controller.cancel()
        self.status_label.setText("設計が変更されました。表示中の結果は古い状態です")
        self.setWindowTitle("性能評価 * - KiraKiraLens")

    def run_analysis(self) -> None:
        self._generation += 1
        options = {
            "quality": self.quality.currentData(),
            "max_frequency_lp_mm": self.maximum_frequency.value(),
        }
        self._controller.submit(self._generation, self.design, normalized_options(options, self.design))

    @Slot(int, object)
    def _analysis_finished(self, generation: int, result: dict) -> None:
        if generation != self._generation:
            return
        self._result = result
        if not result.get("valid"):
            warnings = result.get("warnings") or ["性能解析に失敗しました"]
            self.status_label.setText(" / ".join(str(item) for item in warnings))
            self.warning_label.setText("\n".join(str(item) for item in warnings))
            return
        self._render_result(result)
        self.status_label.setText(f"{result.get('engine', 'Optiland')} / 解析完了")
        self.setWindowTitle("性能評価 - KiraKiraLens")

    @Slot(bool)
    def _running_changed(self, running: bool) -> None:
        self._running = running
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.progress.setVisible(running)

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _render_result(self, result: dict) -> None:
        angles = result.get("angle_of_view", {})
        self.angle_label.setText(
            f"像面 {self.design.settings.sensor_width_mm:.2f} x {self.design.settings.sensor_height_mm:.2f} mm / "
            f"画角 横 {angles.get('horizontal_deg', 0):.2f}°  縦 {angles.get('vertical_deg', 0):.2f}°  "
            f"対角 {angles.get('diagonal_deg', 0):.2f}°"
        )
        self._render_summary(result)
        self._render_mtf(result.get("mtf", {}))
        self._render_spots(result.get("spots", {}))
        self._render_ray_fan(result.get("ray_fan", {}))
        self._render_longitudinal(result.get("longitudinal", {}))
        self._render_field_and_distortion(result.get("field_curvature", {}), result.get("distortion", {}))

    def _render_summary(self, result: dict) -> None:
        summary = result.get("summary", {})
        rows = summary.get("field_rows", [])
        self.summary_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("label"),
                self._format(row.get("mtf10_t"), 3),
                self._format(row.get("mtf10_s"), 3),
                self._format(row.get("mtf20_t"), 3),
                self._format(row.get("mtf20_s"), 3),
                self._format(row.get("mtf40_t"), 3),
                self._format(row.get("mtf40_s"), 3),
                f"{self._format(row.get('rms_spot_um'), 1)} µm",
                f"{self._format(row.get('r80_um'), 1)} µm",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.summary_table.setItem(row_index, column, item)
        metrics = summary.get("merit_metrics", {})
        units = {
            "mtf40_min": ("", 3),
            "corner_rms_spot_um": (" µm", 1),
            "max_ray_fan_rms_um": (" µm", 1),
            "edge_distortion_percent": (" %", 2),
            "edge_astigmatism_mm": (" mm", 3),
            "primary_longitudinal_spherical_um": (" µm", 1),
            "axial_color_um": (" µm", 1),
        }
        for key, label in self.metric_labels.items():
            suffix, decimals = units[key]
            label.setText(f"{self._format(metrics.get(key), decimals)}{suffix}")
        self.method_label.setText(
            f"解析方式: {result.get('method', '-')} / 波長重み: {result.get('mtf', {}).get('spectral_weighting', '-')}"
        )
        self.warning_label.setText("\n".join(str(item) for item in result.get("warnings", [])))

    def _render_mtf(self, mtf: dict) -> None:
        frequencies = mtf.get("frequencies_lp_mm", [])
        series = []
        for index, field in enumerate(mtf.get("fields", [])):
            color = FIELD_COLORS[index % len(FIELD_COLORS)]
            series.extend(
                [
                    {"label": f"{field['label']} T", "x": frequencies, "y": field["tangential"], "color": color},
                    {"label": f"{field['label']} S", "x": frequencies, "y": field["sagittal"], "color": color, "dashed": True},
                ]
            )
        maximum = max(frequencies, default=80.0)
        self.mtf_plot.set_plot("多波長MTF", "空間周波数 [lp/mm]", "コントラスト", series, (0, maximum), (0, 1))

    def _render_spots(self, spots: dict) -> None:
        airy_radius = spots.get("airy_radius_um")
        self._ensure_spot_plots(len(spots.get("fields", [])))
        for plot_index, plot in enumerate(self.spot_plots):
            fields = spots.get("fields", [])
            if plot_index >= len(fields):
                plot.set_plot("スポット", "X [µm]", "Y [µm]", [])
                continue
            field = fields[plot_index]
            series = [
                {
                    "label": f"{wave['wavelength_um']:.4f} µm",
                    "x": wave["x_um"],
                    "y": wave["y_um"],
                    "color": WAVELENGTH_COLORS[index % len(WAVELENGTH_COLORS)],
                }
                for index, wave in enumerate(field.get("series", []))
            ]
            title = f"{field['label']} / RMS {field['rms_um']:.1f} µm / R80 {field['r80_um']:.1f} µm"
            plot.set_plot(title, "X [µm]", "Y [µm]", series, reference_radius=airy_radius)

    def _render_ray_fan(self, ray_fan: dict) -> None:
        fields = ray_fan.get("fields", [])
        self._ensure_ray_plots(len(fields))
        for field_index, (tangential_plot, sagittal_plot) in enumerate(self.ray_plots):
            if field_index >= len(fields):
                tangential_plot.set_plot("横収差 T", "瞳座標", "光線誤差 [µm]", [])
                sagittal_plot.set_plot("横収差 S", "瞳座標", "光線誤差 [µm]", [])
                continue
            field = fields[field_index]
            for plot, key, suffix in (
                (tangential_plot, "tangential", "T"),
                (sagittal_plot, "sagittal", "S"),
            ):
                series = [
                    {
                        "label": f"{wave['wavelength_um']:.4f} µm",
                        "x": wave["pupil"],
                        "y": wave["error_um"],
                        "color": WAVELENGTH_COLORS[index % len(WAVELENGTH_COLORS)],
                    }
                    for index, wave in enumerate(field.get(key, []))
                ]
                plot.set_plot(
                    f"{field['label']} {suffix} / RMS {field['rms_um']:.1f} µm",
                    "正規化瞳座標",
                    "横光線収差 [µm]",
                    series,
                    (-1, 1),
                )

    def _ensure_spot_plots(self, count: int) -> None:
        while len(self.spot_plots) < count:
            plot = PlotWidget(scatter=True, equal_axes=True)
            plot.setMinimumWidth(300)
            self.spot_layout.addWidget(plot, 1)
            self.spot_plots.append(plot)
        while len(self.spot_plots) > count:
            plot = self.spot_plots.pop()
            self.spot_layout.removeWidget(plot)
            plot.deleteLater()

    def _ensure_ray_plots(self, count: int) -> None:
        while len(self.ray_plots) < count:
            row = len(self.ray_plots)
            tangential = PlotWidget()
            sagittal = PlotWidget()
            tangential.setMinimumHeight(250)
            sagittal.setMinimumHeight(250)
            self.ray_grid.addWidget(tangential, row, 0)
            self.ray_grid.addWidget(sagittal, row, 1)
            self.ray_plots.append((tangential, sagittal))
        while len(self.ray_plots) > count:
            tangential, sagittal = self.ray_plots.pop()
            for plot in (tangential, sagittal):
                self.ray_grid.removeWidget(plot)
                plot.deleteLater()

    def _render_longitudinal(self, longitudinal: dict) -> None:
        pupil = longitudinal.get("pupil", [])
        series = [
            {
                "label": f"{wave['wavelength_um']:.4f} µm",
                "x": wave["focus_shift_mm"],
                "y": pupil,
                "color": WAVELENGTH_COLORS[index % len(WAVELENGTH_COLORS)],
            }
            for index, wave in enumerate(longitudinal.get("series", []))
        ]
        self.longitudinal_plot.set_plot(
            "縦球面収差・軸上色収差",
            "d線近軸焦点からの移動 [mm]",
            "正規化瞳座標",
            series,
            y_range=(0, 1),
        )

    def _render_field_and_distortion(self, field_curvature: dict, distortion: dict) -> None:
        field_axis = field_curvature.get("field", [])
        field_series = []
        for index, wave in enumerate(field_curvature.get("series", [])):
            color = WAVELENGTH_COLORS[index % len(WAVELENGTH_COLORS)]
            field_series.extend(
                [
                    {"label": f"{wave['wavelength_um']:.4f} T", "x": field_axis, "y": wave["tangential_mm"], "color": color},
                    {"label": f"{wave['wavelength_um']:.4f} S", "x": field_axis, "y": wave["sagittal_mm"], "color": color, "dashed": True},
                ]
            )
        self.field_plot.set_plot("像面湾曲・非点収差", "正規化像高", "焦点移動 [mm]", field_series, (0, 1))

        distortion_axis = distortion.get("field", [])
        distortion_series = [
            {
                "label": f"{wave['wavelength_um']:.4f} µm",
                "x": distortion_axis,
                "y": wave["percent"],
                "color": WAVELENGTH_COLORS[index % len(WAVELENGTH_COLORS)],
            }
            for index, wave in enumerate(distortion.get("series", []))
        ]
        self.distortion_plot.set_plot("歪曲収差 (f-tan)", "正規化像高", "歪曲 [%]", distortion_series, (0, 1))

    @staticmethod
    def _format(value, decimals: int) -> str:
        if value is None:
            return "-"
        return f"{float(value):.{decimals}f}"

    def shutdown(self) -> None:
        self._controller.shutdown()

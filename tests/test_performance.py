from __future__ import annotations

import os
import json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kirakiralens.domain import OpticalDesign
from kirakiralens.optics.performance import evaluate_performance
from kirakiralens.ui.performance_window import PerformanceWindow


def test_performance_metrics_and_window_are_populated() -> None:
    design = OpticalDesign.starter()
    result = evaluate_performance(design, {"quality": "preview", "max_frequency_lp_mm": 80})

    assert result["valid"]
    assert not result["warnings"]
    assert {10.0, 20.0, 40.0}.issubset(result["mtf"]["frequencies_lp_mm"])
    assert len(result["spots"]["fields"]) == 3
    assert len(result["ray_fan"]["fields"]) == 3
    assert len(result["longitudinal"]["series"]) == 3
    assert len(result["field_curvature"]["series"]) == 3
    assert len(result["distortion"]["series"]) == 3
    assert result["petzval"]["curvature_per_mm"] != 0
    assert result["petzval"]["radius_mm"] is not None
    assert result["distortion_grid"]["grid_points"] == 9
    assert result["distortion_grid"]["maximum_distortion_percent"] >= 0
    metrics = result["summary"]["merit_metrics"]
    assert 0 <= metrics["mtf40_min"] <= 1
    assert metrics["corner_rms_spot_um"] > 0
    assert metrics["axial_color_um"] > 0
    assert metrics["petzval_sum_per_mm"] == result["petzval"]["curvature_per_mm"]
    json.dumps(result, allow_nan=False)

    application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    window = PerformanceWindow(design, root)
    window._render_result(result)
    window.show()
    application.processEvents()
    assert window.tabs.count() == 7
    assert window.summary_table.rowCount() == 3
    assert len(window.mtf_plot.series) == 6
    assert all(plot.series for plot in window.spot_plots)
    assert window.distortion_grid_plot.series
    assert "1/mm" in window.metric_labels["petzval_sum_per_mm"].text()
    window.shutdown()
    window.close()
    application.processEvents()

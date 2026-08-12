from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kirakiralens.ui.main_window import MainWindow


def test_main_window_constructs_with_generated_catalog() -> None:
    application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    window = MainWindow(root, analyze_on_start=False)

    assert window.repository.count_products() == 920
    assert window.design.settings.back_focus_target_mm == 45.46
    assert window.lens_view.scene().items()

    window._select("element", 0)
    assert window.inspector.surface_selector.count() == 2
    assert window.inspector.surface_index == 0
    window.inspector.surface_selector.setCurrentIndex(1)
    application.processEvents()
    assert window.selected_surface == 1

    window.set_gap_after_element(0, 12.5)
    assert window.design.elements[0].gap_after_mm == 12.5
    element_count = len(window.design.elements)
    window.delete_element(1)
    assert len(window.design.elements) == element_count - 1

    assert window.catalog_panel.min_diameter.maximum() == 10000
    assert window.inspector.diameter.maximum() == 10000
    window.close()
    application.processEvents()

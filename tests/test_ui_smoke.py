from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kirakiralens.ui.main_window import MainWindow


def test_main_window_constructs_with_generated_catalog() -> None:
    application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    window = MainWindow(root)

    assert window.repository.count_products() == 920
    assert window.design.settings.back_focus_target_mm == 45.46
    assert window.lens_view.scene().items()
    window.close()
    application.processEvents()

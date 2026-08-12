from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KiraKiraLens desktop application")
    parser.add_argument("--screenshot", type=Path, help="Save a screenshot and exit")
    args = parser.parse_args(argv)

    cache_directory = Path.cwd() / ".tmp" / "matplotlib"
    cache_directory.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_directory))
    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("KiraKiraLens")
    app.setOrganizationName("KiraKiraLens")
    app.setFont(QFont("Yu Gothic UI", 9))
    app.setStyleSheet(
        """
        QMainWindow, QWidget { background: #f5f7f6; color: #26322f; }
        QMenuBar, QToolBar, QStatusBar { background: #ffffff; border-color: #d8dfdc; }
        QToolBar { spacing: 6px; padding: 5px; border-bottom: 1px solid #d8dfdc; }
        QDockWidget::title { background: #e8eeeb; padding: 7px; font-weight: 600; }
        QLineEdit, QComboBox, QDoubleSpinBox, QTableWidget {
            background: #ffffff; border: 1px solid #cbd5d1; selection-background-color: #2b776d;
            selection-color: #ffffff;
        }
        QLineEdit, QComboBox, QDoubleSpinBox { min-height: 24px; padding: 1px 4px; }
        QPushButton { background: #ffffff; border: 1px solid #aebbb6; padding: 5px 9px; }
        QPushButton:hover { border-color: #2b776d; background: #edf5f2; }
        QPushButton:pressed { background: #dcece6; }
        QPushButton:disabled { color: #8c9692; background: #eef1f0; }
        QFrame#diagramEditor { background: #edf2ef; border: 0; border-bottom: 1px solid #cbd5d1; }
        QHeaderView::section { background: #e3e9e6; border: none; border-right: 1px solid #cbd5d1; padding: 5px; }
        QGroupBox { border-top: 1px solid #cbd5d1; margin-top: 10px; padding-top: 9px; font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 5px; padding: 0 4px; }
        """
    )
    window = MainWindow(analyze_on_start=not bool(args.screenshot))
    window.show()

    if args.screenshot:
        output = args.screenshot.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        def capture() -> None:
            window.grab().save(str(output))
            window.close()
            app.quit()

        QTimer.singleShot(1500, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

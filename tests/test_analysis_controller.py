from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from kirakiralens.domain import OpticalDesign
from kirakiralens.ui.analysis_controller import AnalysisController


def test_analysis_process_keeps_qt_event_loop_responsive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    application = QApplication.instance() or QApplication([])
    controller = AnalysisController()
    loop = QEventLoop()
    ticks = 0
    received: list[tuple[int, object]] = []

    ticker = QTimer()
    ticker.setInterval(50)

    def tick() -> None:
        nonlocal ticks
        ticks += 1

    def finished(generation: int, result: object) -> None:
        received.append((generation, result))
        loop.quit()

    ticker.timeout.connect(tick)
    controller.finished.connect(finished)
    ticker.start()
    controller.submit(7, OpticalDesign.starter())
    QTimer.singleShot(30_000, loop.quit)
    loop.exec()
    ticker.stop()
    controller.shutdown()
    application.processEvents()

    assert received
    generation, result = received[0]
    assert generation == 7
    assert result.valid, result.error
    assert ticks >= 10

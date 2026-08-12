from __future__ import annotations

import json
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from ..domain import OpticalDesign
from ..optics.optiland_adapter import FirstOrderAnalysis


class AnalysisController(QObject):
    """Run Optiland outside the UI process and coalesce superseded requests."""

    finished = Signal(int, object)
    statusChanged = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(["-m", "kirakiralens.optics.analysis_process"])
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.started.connect(self._send_pending)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._pending: tuple[int, dict] | None = None
        self._active_generation: int | None = None
        self._shutting_down = False
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(60000)
        self._timeout.timeout.connect(self._request_timed_out)

    def submit(self, generation: int, design: OpticalDesign) -> None:
        self._pending = (generation, design.to_dict())
        if self._active_generation is not None:
            return
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._stderr_buffer = ""
            self.statusChanged.emit("解析エンジンを起動中 (操作可能)")
            self.process.start()
            return
        if self.process.state() == QProcess.ProcessState.Running:
            self._send_pending()

    def _send_pending(self) -> None:
        if self._pending is None or self._active_generation is not None:
            return
        generation, design = self._pending
        self._pending = None
        self._active_generation = generation
        payload = json.dumps({"generation": generation, "design": design}, ensure_ascii=True) + "\n"
        self.process.write(payload.encode("utf-8"))
        self._timeout.start()
        self.statusChanged.emit("Optilandで解析中 (操作可能)")

    def _read_stdout(self) -> None:
        self._stdout_buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                generation = int(payload["generation"])
                result = FirstOrderAnalysis(**payload["result"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            self._timeout.stop()
            self._active_generation = None
            self.finished.emit(generation, result)
            self._send_pending()

    def _read_stderr(self) -> None:
        self._stderr_buffer += bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self._stderr_buffer = self._stderr_buffer[-8000:]

    def _request_timed_out(self) -> None:
        generation = self._active_generation
        self._active_generation = None
        self.process.kill()
        if generation is not None:
            self.finished.emit(
                generation,
                FirstOrderAnalysis(valid=False, engine="Optiland process", error="解析が60秒でタイムアウトしました"),
            )

    def _process_finished(self) -> None:
        self._timeout.stop()
        generation = self._active_generation
        self._active_generation = None
        if generation is not None and not self._shutting_down:
            error = self._stderr_buffer.strip().splitlines()[-1] if self._stderr_buffer.strip() else "解析プロセスが終了しました"
            self.finished.emit(generation, FirstOrderAnalysis(valid=False, engine="Optiland process", error=error))
        if self._pending is not None and not self._shutting_down:
            QTimer.singleShot(100, self.process.start)

    def _process_error(self, error) -> None:
        if self._shutting_down or error != QProcess.ProcessError.FailedToStart:
            return
        generation = self._active_generation
        self._active_generation = None
        if generation is None and self._pending is not None:
            generation, _ = self._pending
            self._pending = None
        if generation is not None:
            self.finished.emit(
                generation,
                FirstOrderAnalysis(valid=False, engine="Optiland process", error="解析プロセスを起動できませんでした"),
            )

    def shutdown(self) -> None:
        self._shutting_down = True
        self._pending = None
        self._timeout.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(500):
                self.process.kill()
                self.process.waitForFinished(500)

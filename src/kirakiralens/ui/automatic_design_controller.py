from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..domain import OpticalDesign


class AutomaticDesignController(QObject):
    progress = Signal(int, object)
    finished = Signal(int, object)
    runningChanged = Signal(bool)

    def __init__(self, cache_directory: Path, parent=None):
        super().__init__(parent)
        cache_directory.mkdir(parents=True, exist_ok=True)
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(["-m", "kirakiralens.optics.automatic_design_process"])
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("MPLCONFIGDIR", str(cache_directory))
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.started.connect(self._send_request)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self._pending: tuple[int, dict, dict] | None = None
        self._active_generation: int | None = None
        self._stdout = ""
        self._stderr = ""
        self._cancelled = False

    def start(self, generation: int, design: OpticalDesign, options: dict) -> None:
        self.cancel(silent=True)
        self._pending = (generation, design.to_dict(), options)
        self._cancelled = False
        self._stderr = ""
        self.runningChanged.emit(True)
        self.process.start()

    def _send_request(self) -> None:
        if self._pending is None:
            return
        generation, design, options = self._pending
        self._pending = None
        self._active_generation = generation
        payload = json.dumps({"generation": generation, "design": design, "options": options}, ensure_ascii=True) + "\n"
        self.process.write(payload.encode("utf-8"))

    def _read_stdout(self) -> None:
        self._stdout += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._stdout:
            line, self._stdout = self._stdout.split("\n", 1)
            try:
                payload = json.loads(line)
                generation = int(payload["generation"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if payload.get("type") == "progress":
                self.progress.emit(generation, payload.get("progress", {}))
            elif payload.get("type") == "result":
                self._active_generation = None
                self.runningChanged.emit(False)
                self.finished.emit(generation, payload.get("result", {}))

    def _read_stderr(self) -> None:
        self._stderr += bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self._stderr = self._stderr[-12000:]

    def cancel(self, silent: bool = False) -> None:
        self._pending = None
        self._active_generation = None
        self._cancelled = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        if not silent:
            self.runningChanged.emit(False)

    def _process_finished(self) -> None:
        generation = self._active_generation
        self._active_generation = None
        self.runningChanged.emit(False)
        if generation is not None and not self._cancelled:
            error = self._stderr.strip().splitlines()[-1] if self._stderr.strip() else "自動設計プロセスが終了しました"
            self.finished.emit(generation, {"valid": False, "error": error})

    def _process_error(self, error) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return
        generation = self._active_generation
        if generation is None and self._pending is not None:
            generation = self._pending[0]
        self._pending = None
        self._active_generation = None
        self.runningChanged.emit(False)
        if generation is not None:
            self.finished.emit(generation, {"valid": False, "error": "自動設計プロセスを起動できませんでした"})

    def shutdown(self) -> None:
        self.cancel(silent=True)


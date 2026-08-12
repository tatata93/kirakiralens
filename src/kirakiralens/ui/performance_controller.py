from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from ..domain import OpticalDesign
from ..optics.performance import normalized_options
from ..optics.signature import analysis_signature


class PerformanceController(QObject):
    finished = Signal(int, object)
    statusChanged = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self, cache_directory: Path, parent: QObject | None = None):
        super().__init__(parent)
        cache_directory.mkdir(parents=True, exist_ok=True)
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(["-m", "kirakiralens.optics.performance_process"])
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("MPLCONFIGDIR", str(cache_directory))
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.started.connect(self._send_pending)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)
        self._pending: tuple[int, dict, dict, str] | None = None
        self._active_generation: int | None = None
        self._active_signature: str | None = None
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._cancelled = False
        self._shutting_down = False
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(180000)
        self._timeout.timeout.connect(self._request_timed_out)

    def submit(self, generation: int, design: OpticalDesign, options: dict) -> None:
        resolved = normalized_options(options, design)
        signature = analysis_signature(design, resolved)
        if signature in self._cache:
            result = self._cache[signature]
            self._cache.move_to_end(signature)
            self.statusChanged.emit("設計と解析設定に変更がないため、保存済み結果を表示しました")
            QTimer.singleShot(0, lambda: self.finished.emit(generation, result))
            return
        if self._active_signature == signature:
            self.statusChanged.emit("同じ性能解析を実行中です")
            return
        self._pending = (generation, design.to_dict(), resolved, signature)
        self._cancelled = False
        if self._active_generation is not None:
            return
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._stderr_buffer = ""
            self.statusChanged.emit("性能解析エンジンを起動中。設計画面は操作できます")
            self.runningChanged.emit(True)
            self.process.start()
        else:
            self._send_pending()

    def cancel(self) -> None:
        self._pending = None
        self._active_generation = None
        self._active_signature = None
        self._cancelled = True
        self._timeout.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        else:
            self.runningChanged.emit(False)
        self.statusChanged.emit("性能解析を停止しました")

    def _send_pending(self) -> None:
        if self._pending is None or self._active_generation is not None:
            return
        generation, design, options, signature = self._pending
        self._pending = None
        self._active_generation = generation
        self._active_signature = signature
        payload = json.dumps(
            {"generation": generation, "design": design, "options": options},
            ensure_ascii=True,
        ) + "\n"
        self.process.write(payload.encode("utf-8"))
        self._timeout.start()
        self.runningChanged.emit(True)
        self.statusChanged.emit("実光線を追跡して性能を計算中。設計画面は操作できます")

    def _read_stdout(self) -> None:
        self._stdout_buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                generation = int(payload["generation"])
                result = dict(payload["result"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            signature = self._active_signature
            self._timeout.stop()
            self._active_generation = None
            self._active_signature = None
            if signature is not None and result.get("valid"):
                self._cache[signature] = result
                self._cache.move_to_end(signature)
                while len(self._cache) > 8:
                    self._cache.popitem(last=False)
            self.runningChanged.emit(False)
            self.finished.emit(generation, result)
            self._send_pending()

    def _read_stderr(self) -> None:
        self._stderr_buffer += bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self._stderr_buffer = self._stderr_buffer[-12000:]

    def _request_timed_out(self) -> None:
        generation = self._active_generation
        self._active_generation = None
        self._active_signature = None
        self.process.kill()
        self.runningChanged.emit(False)
        if generation is not None:
            self.finished.emit(
                generation,
                {"valid": False, "engine": "Optiland performance process", "warnings": ["性能解析が180秒でタイムアウトしました"]},
            )

    def _process_finished(self) -> None:
        self._timeout.stop()
        generation = self._active_generation
        self._active_generation = None
        self._active_signature = None
        self.runningChanged.emit(False)
        if generation is not None and not self._cancelled and not self._shutting_down:
            error = self._stderr_buffer.strip().splitlines()[-1] if self._stderr_buffer.strip() else "性能解析プロセスが終了しました"
            self.finished.emit(
                generation,
                {"valid": False, "engine": "Optiland performance process", "warnings": [error]},
            )

    def _process_error(self, error) -> None:
        if self._shutting_down or error != QProcess.ProcessError.FailedToStart:
            return
        generation = self._active_generation
        self._active_generation = None
        self._active_signature = None
        if generation is None and self._pending is not None:
            generation = self._pending[0]
            self._pending = None
        self.runningChanged.emit(False)
        if generation is not None:
            self.finished.emit(
                generation,
                {"valid": False, "engine": "Optiland performance process", "warnings": ["性能解析プロセスを起動できませんでした"]},
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

"""Non-blocking ani-cli bridge for the Qt UI.

Each resolve runs in its own QProcess, so the event loop never waits on the
network. Results come back through signals tagged with a request id.
"""

from __future__ import annotations

import itertools
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .ani_cli import (
    DEFAULT_TIMEOUT,
    AniCliError,
    ResolveRequest,
    build_command,
    clean_output,
    error_message,
    find_ani_cli,
    install_shim,
    parse_capture,
)


@dataclass
class _Job:
    request: ResolveRequest
    process: QProcess
    capture: str
    timer: QTimer
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False


class CliBridge(QObject):
    streamResolved = Signal(str, object)  # request_id, StreamInfo
    failed = Signal(str, str)             # request_id, message
    progress = Signal(str, str)           # request_id, status line from ani-cli

    def __init__(self, parent: QObject | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__(parent)
        self._timeout_ms = int(timeout * 1000)
        self._ids = itertools.count(1)
        self._jobs: dict[str, _Job] = {}
        self._ani_cli: str | None = None
        self._shim: str | None = None

    # -- public API -------------------------------------------------------------

    def resolve(self, request: ResolveRequest) -> str:
        """Start resolving a stream. Returns the request id used in signals."""
        request_id = f"r{next(self._ids)}"
        try:
            self._ani_cli = self._ani_cli or find_ani_cli()
            self._shim = self._shim or install_shim()
            fd, capture = tempfile.mkstemp(prefix="anigui-", suffix=".args")
            os.close(fd)
            cmd, env = build_command(request, self._ani_cli, self._shim, capture)
        except AniCliError as exc:
            QTimer.singleShot(0, lambda: self.failed.emit(request_id, str(exc)))
            return request_id

        proc = QProcess(self)
        qenv = QProcessEnvironment()
        for key, value in env.items():
            qenv.insert(key, value)
        proc.setProcessEnvironment(qenv)
        proc.setStandardInputFile(QProcess.nullDevice())

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_timeout(request_id))

        job = _Job(request, proc, capture, timer)
        self._jobs[request_id] = job

        proc.readyReadStandardOutput.connect(lambda: self._on_stdout(request_id))
        proc.readyReadStandardError.connect(lambda: self._on_stderr(request_id))
        proc.finished.connect(lambda code, _status: self._on_finished(request_id, code))
        proc.errorOccurred.connect(lambda err: self._on_error(request_id, err))

        proc.start(cmd[0], cmd[1:])
        timer.start(self._timeout_ms)
        return request_id

    def cancel(self, request_id: str) -> None:
        """Stop a resolve. No signal is emitted for a cancelled request."""
        job = self._jobs.get(request_id)
        if job:
            job.cancelled = True
            job.process.kill()  # _on_finished does the cleanup

    def active(self) -> list[str]:
        return list(self._jobs)

    # -- process callbacks --------------------------------------------------------

    def _on_stdout(self, request_id: str) -> None:
        job = self._jobs.get(request_id)
        if not job:
            return
        chunk = bytes(job.process.readAllStandardOutput()).decode("utf-8", "replace")
        job.stdout += chunk
        for line in clean_output(chunk).splitlines():
            if line.strip():
                self.progress.emit(request_id, line.strip())

    def _on_stderr(self, request_id: str) -> None:
        job = self._jobs.get(request_id)
        if job:
            job.stderr += bytes(job.process.readAllStandardError()).decode("utf-8", "replace")

    def _on_timeout(self, request_id: str) -> None:
        job = self._jobs.get(request_id)
        if job:
            job.timed_out = True
            job.process.kill()

    def _on_error(self, request_id: str, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            job = self._jobs.pop(request_id, None)
            if job:
                self._cleanup(job)
                self.failed.emit(request_id, f"Could not start ani-cli ({job.process.errorString()})")

    def _on_finished(self, request_id: str, code: int) -> None:
        job = self._jobs.pop(request_id, None)
        if not job:
            return
        try:
            if job.cancelled:
                return
            if job.timed_out:
                self.failed.emit(request_id, f"ani-cli timed out after {self._timeout_ms // 1000}s")
                return
            data = Path(job.capture).read_bytes() if os.path.exists(job.capture) else b""
            if code != 0 or not data:
                self.failed.emit(request_id, error_message(job.stdout, job.stderr, code))
                return
            try:
                self.streamResolved.emit(request_id, parse_capture(data))
            except AniCliError as exc:
                self.failed.emit(request_id, str(exc))
        finally:
            self._cleanup(job)

    @staticmethod
    def _cleanup(job: _Job) -> None:
        job.timer.stop()
        job.timer.deleteLater()
        job.process.deleteLater()
        try:
            os.unlink(job.capture)
        except OSError:
            pass

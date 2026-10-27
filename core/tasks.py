"""Run blocking calls on a QThreadPool and get results back on the UI thread.

    runner = TaskRunner()
    runner.submit(catalog.enrich, anime_id, title,
                  on_done=self.show_details, on_error=self.show_error,
                  group="details")   # newer task in the same group wins

Callbacks always run on the thread that owns the runner (the UI thread). With a
`group`, only the newest task's result is delivered, which suits search-as-you-type
and fast clicking between shows.
"""

from __future__ import annotations

import itertools
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

DoneCallback = Callable[[Any], None]
ErrorCallback = Callable[[str], None]


class _Relay(QObject):
    done = Signal(str, object)
    error = Signal(str, str)


class _Job(QRunnable):
    def __init__(self, task_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict, relay: _Relay) -> None:
        super().__init__()
        self.task_id, self.fn, self.args, self.kwargs, self.relay = task_id, fn, args, kwargs, relay
        self.setAutoDelete(True)

    def run(self) -> None:  # worker thread
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - every failure goes back to the UI
            self.relay.error.emit(self.task_id, str(exc) or type(exc).__name__)
        else:
            self.relay.done.emit(self.task_id, result)


class TaskRunner(QObject):
    finished = Signal(str, object)  # task_id, result (after callbacks run)
    failed = Signal(str, str)       # task_id, message

    def __init__(self, parent: QObject | None = None, max_threads: int = 6) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self._ids = itertools.count(1)
        self._callbacks: dict[str, tuple[DoneCallback | None, ErrorCallback | None]] = {}
        self._groups: dict[str, str] = {}   # group -> newest task id
        self._task_group: dict[str, str] = {}
        self._relay = _Relay(self)
        self._relay.done.connect(self._on_done)
        self._relay.error.connect(self._on_error)

    def submit(self, fn: Callable[..., Any], *args: Any, on_done: DoneCallback | None = None,
               on_error: ErrorCallback | None = None, group: str | None = None, **kwargs: Any) -> str:
        task_id = f"t{next(self._ids)}"
        self._callbacks[task_id] = (on_done, on_error)
        if group:
            self._groups[group] = task_id
            self._task_group[task_id] = group
        self.pool.start(_Job(task_id, fn, args, kwargs, self._relay))
        return task_id

    def cancel(self, task_id: str) -> None:
        """Drop the result of a task. The function itself still runs to completion."""
        self._callbacks.pop(task_id, None)

    def pending(self) -> int:
        return len(self._callbacks)

    def wait(self, msecs: int = -1) -> bool:
        return self.pool.waitForDone(msecs)

    # -- delivery (UI thread) ---------------------------------------------------------

    def _is_stale(self, task_id: str) -> bool:
        group = self._task_group.pop(task_id, None)
        if group is None:
            return False
        newest = self._groups.get(group)
        if newest == task_id:
            del self._groups[group]
            return False
        return True

    def _on_done(self, task_id: str, result: object) -> None:
        callbacks = self._callbacks.pop(task_id, None)
        stale = self._is_stale(task_id)
        if callbacks is None or stale:
            return
        if callbacks[0]:
            callbacks[0](result)
        self.finished.emit(task_id, result)

    def _on_error(self, task_id: str, message: str) -> None:
        callbacks = self._callbacks.pop(task_id, None)
        stale = self._is_stale(task_id)
        if callbacks is None or stale:
            return
        if callbacks[1]:
            callbacks[1](message)
        self.failed.emit(task_id, message)

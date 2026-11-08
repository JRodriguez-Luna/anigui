"""Your data (2.0): back up, restore, automatic backups, and bringing your AniList or MAL list over.

Everything runs off the main thread; a progress window shows the import as it goes.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog, QWidget

from core import backup, importer

from .context import DEFAULTS, AppContext


class DataTools(QObject):
    changed = Signal()                       # your data was replaced or added to: refresh everything
    message = Signal(str, bool)              # toast (text, error)
    _progress = Signal(int, int, str)        # from the worker thread

    def __init__(self, ctx: AppContext, parent: QWidget) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.window = parent
        self._dialog: QProgressDialog | None = None
        self._cancel = False
        self._progress.connect(self._on_progress)

    def prefs(self) -> dict:
        s = self.ctx.settings
        return {k: s.value(k) for k in s.allKeys()}

    # -- backups ------------------------------------------------------------------------------

    def back_up_now(self) -> Path | None:
        start = str(Path.home() / "Documents" / backup.default_name())
        path, _ = QFileDialog.getSaveFileName(self.window, "Back up AniGUI", start, f"AniGUI backup (*{backup.EXT})")
        if not path:
            return None
        try:
            out = backup.back_up(self.ctx.store, self.prefs(), Path(path))
        except OSError as exc:
            self.message.emit(f"Couldn't save the backup: {exc}", True)
            return None
        self.message.emit(f"Backed up to {out.name}", False)
        return out

    def restore(self, path: str | None = None, confirm: bool = True) -> bool:
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self.window, "Restore a backup", str(backup.backups_dir()),
                                                  f"AniGUI backup (*{backup.EXT})")
        if not path:
            return False
        try:
            manifest = backup.read_manifest(Path(path))
        except backup.BackupError as exc:
            self.message.emit(str(exc), True)
            return False
        if confirm:
            box = QMessageBox(QMessageBox.Icon.Question, "Restore backup",
                              f"Restore the backup from {manifest.get('created', '?').replace('T', ' at ')}?",
                              parent=self.window)
            box.setInformativeText("Your history, lists, ratings, notes and settings go back to how they were "
                                   "then. What's there now is backed up first, so you can undo this.")
            box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
            keep = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(keep)
            box.exec()
            if box.clickedButton() is keep:
                return False
        try:
            settings, safety = backup.restore(self.ctx.store, Path(path), self.prefs())
        except (backup.BackupError, OSError) as exc:
            self.message.emit(f"Nothing was changed: {exc}", True)
            return False
        for key, value in settings.items():
            if key in DEFAULTS:
                self.ctx.set_pref(key, value)
        self.changed.emit()
        self.message.emit(f"Restored. (What was there before is in {safety.name}.)", False)
        return True

    def auto_backup(self) -> None:
        if self.ctx.pref("auto_backup"):
            self.ctx.runner.submit(backup.auto_backup, self.ctx.store, self.prefs(), group="auto-backup")

    @staticmethod
    def show_folder() -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(backup.backups_dir())))

    # -- import -------------------------------------------------------------------------------

    def import_anilist(self, username: str) -> None:
        self._start(f"AniList: {username}", lambda: importer.from_anilist(self.ctx.catalog.anilist, username))

    def import_mal(self, path: str | None = None) -> None:
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self.window, "Choose your MyAnimeList export", str(Path.home() / "Downloads"),
                                                  "MyAnimeList export (*.xml *.gz)")
        if path:
            self._start("MyAnimeList", lambda: importer.from_mal(self.ctx.catalog.anilist, Path(path)))

    def _start(self, label: str, fetch) -> None:
        self._cancel = False
        dlg = QProgressDialog(f"Reading your list from {label}…", "Stop", 0, 0, self.window)
        dlg.setWindowTitle("Bringing your list over")
        dlg.setMinimumDuration(0)
        dlg.canceled.connect(lambda: setattr(self, "_cancel", True))
        dlg.show()
        self._dialog = dlg
        # Make a backup first, so an import can always be undone
        backup.auto_backup(self.ctx.store, self.prefs(), every=dt.timedelta(0))

        def run():
            entries = fetch()
            return importer.apply(self.ctx.store, self.ctx.catalog, entries,
                                  progress=lambda i, n, t: self._progress.emit(i, n, t),
                                  cancelled=lambda: self._cancel)
        self.ctx.runner.submit(run, on_done=self._done, on_error=self._failed, group="import")

    def _on_progress(self, i: int, n: int, title: str) -> None:
        if self._dialog is None:
            return
        self._dialog.setMaximum(max(1, n))
        self._dialog.setValue(i)
        self._dialog.setLabelText(f"Finding {title}… ({i + 1} of {n})" if title else "Done")

    def _done(self, result: importer.Result) -> None:
        if self._dialog is not None:
            self._dialog.reset()
            self._dialog = None
        self.changed.emit()
        text = f"Brought over {result.added} show{'s' if result.added != 1 else ''}"
        if result.rated:
            text += f", {result.rated} rating{'s' if result.rated != 1 else ''}"
        if result.episodes:
            text += f" and {result.episodes} watched episode{'s' if result.episodes != 1 else ''}"
        text += "."
        if result.not_found:
            text += f" {len(result.not_found)} aren't on hianime."
        self.message.emit(text, False)

    def _failed(self, msg: str) -> None:
        if self._dialog is not None:
            self._dialog.reset()
            self._dialog = None
        self.message.emit(msg.replace("ImportError_: ", ""), True)

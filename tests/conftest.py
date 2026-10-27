"""One QApplication for the whole test run (widget tests need it; core tests reuse it)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
except ImportError:  # PySide6 missing: Qt-dependent tests will fail on their own imports
    _APP = None

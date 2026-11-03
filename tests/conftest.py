"""One QApplication for the whole test run (widget tests need it; core tests reuse it)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
except ImportError:  # PySide6 missing: Qt-dependent tests will fail on their own imports
    _APP = None


def pytest_runtest_logreport(report):
    """On GitHub Actions, turn each failure into an annotation (the run page shows it
    without downloading logs)."""
    if report.failed and os.environ.get("GITHUB_ACTIONS"):
        detail = str(report.longrepr).strip().splitlines()
        tail = " | ".join(line.strip() for line in detail[-12:] if line.strip())
        print(f"\n::error title=test failed: {report.nodeid}::{tail[:1500]}", flush=True)

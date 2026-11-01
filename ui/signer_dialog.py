"""The publisher's review window: 'AniGUI v1.5.0 is ready to sign. Is this yours?'"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from core import signer


class SignDialog(QDialog):
    """Shows what's about to be signed. Only Sign touches the key."""

    def __init__(self, review: signer.Review, parent=None) -> None:
        super().__init__(parent)
        self.review = review
        self.result_text = ""
        p = review.pending
        self.setWindowTitle(f"Sign AniGUI {p.tag}?")
        self.setObjectName("SignerDialog")
        self.setFixedWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        title = QLabel(f"AniGUI {html.escape(p.tag)} is ready to sign", objectName="DialogTitle")
        ask = QLabel("Did you publish this release? Only sign it if you did. If you didn't, someone else may have "
                     "access to your GitHub account.", objectName="Muted", wordWrap=True)
        notes = p.notes.strip().splitlines()
        summary = html.escape(" · ".join(line.strip("-* #") for line in notes[:8] if line.strip())[:400])
        details = QLabel(
            f"<b>Published:</b> {html.escape(p.published_at)} by {html.escape(p.author)}<br>"
            f"<b>File:</b> {html.escape(p.dmg_name)} ({p.size / 1048576:.1f} MB)<br>"
            f"<b>SHA-256:</b> <span style='font-family:Menlo'>{review.sha256[:32]}<br>{review.sha256[32:]}</span><br>"
            f"<b>Notes:</b> {summary or 'none'}",
            objectName="SignerDetails", wordWrap=True)
        details.setTextFormat(Qt.TextFormat.RichText)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.problem = QLabel(" ".join(review.problems), objectName="SignerProblem", wordWrap=True)
        self.problem.setTextFormat(Qt.TextFormat.PlainText)
        self.problem.setVisible(bool(review.problems))

        self.sign_btn = QPushButton("Sign Release", objectName="Primary", cursor=Qt.CursorShape.PointingHandCursor)
        self.sign_btn.setEnabled(review.safe)
        self.sign_btn.clicked.connect(self._sign)
        self.reject_btn = QPushButton("I Didn't Publish This", cursor=Qt.CursorShape.PointingHandCursor)
        self.reject_btn.clicked.connect(self._reject)
        self.later_btn = QPushButton("Later", cursor=Qt.CursorShape.PointingHandCursor)
        self.later_btn.clicked.connect(self._later)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reject_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.later_btn)
        buttons.addWidget(self.sign_btn)

        col = QVBoxLayout(self)
        col.setContentsMargins(26, 24, 26, 22)
        col.setSpacing(12)
        col.addWidget(title)
        col.addWidget(ask)
        col.addWidget(details)
        col.addWidget(self.problem)
        col.addSpacing(6)
        col.addLayout(buttons)

    def _sign(self) -> None:
        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Signing…")
        try:
            signer.sign_and_upload(self.review)
        except signer.SignerError as exc:
            self.sign_btn.setText("Sign Release")
            self.sign_btn.setEnabled(self.review.safe)
            QMessageBox.warning(self, "Not signed", str(exc))
            return
        self.result_text = "signed"
        QMessageBox.information(self, "Signed", f"AniGUI {self.review.pending.tag} is signed. People will be "
                                                "offered the update within a day (or right away from "
                                                "Check for Updates).")
        self.accept()

    def _reject(self) -> None:
        sure = QMessageBox.question(
            self, "Not your release?",
            "AniGUI won't sign it, and nobody will be offered it.\n\nIf you really didn't publish it: change your "
            "GitHub password, check Settings → Sessions and Settings → Applications for anything you don't "
            "recognize, and delete the release.")
        if sure == QMessageBox.StandardButton.Yes:
            signer.reject(self.review.pending.tag)
            self.result_text = "rejected"
            self.accept()

    def _later(self) -> None:
        signer.snooze(self.review.pending.tag)
        self.result_text = "later"
        self.reject()

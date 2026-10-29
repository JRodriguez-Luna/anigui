"""Colors, fonts and the app-wide stylesheet."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication

BG = "#0A0A0F"
SIDEBAR = "#0E0E14"
SURFACE = "#15151D"
SURFACE_2 = "#1D1D28"
SURFACE_3 = "#272735"
BORDER = "#262633"
TEXT = "#ECECF1"
MUTED = "#9B9BAF"
FAINT = "#5E5E72"
ACCENT = "#FF6B3D"
ACCENT_HOVER = "#FF8559"
ACCENT_PRESSED = "#E85A2E"
GOOD = "#3DD68C"

RADIUS = 8


def qcolor(hex_color: str, alpha: int = 255) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def font(px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(QApplication.font())
    f.setPixelSize(int(px))
    f.setWeight(weight)
    return f


STYLESHEET = f"""
* {{ outline: none; }}
QWidget {{ background: transparent; color: {TEXT}; font-size: 13px; }}
QMainWindow, #Page, #PageBody {{ background: {BG}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}

/* Sidebar */
#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#Brand {{ font-size: 21px; font-weight: 800; color: {TEXT}; padding: 4px 6px 18px 6px; }}
#NavButton {{
    text-align: left; padding: 10px 14px; border: none; border-radius: {RADIUS}px;
    color: {MUTED}; font-size: 14px; font-weight: 600;
}}
#NavButton:hover {{ background: {SURFACE}; color: {TEXT}; }}
#NavButton:checked {{ background: {SURFACE_2}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}
#SidebarFooter {{ color: {FAINT}; font-size: 11px; padding: 6px; }}
#SidebarHeading {{ color: {FAINT}; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; }}
#Sidebar QComboBox {{ font-size: 12px; padding: 6px 10px; }}
#Sidebar QCheckBox {{ font-size: 12px; }}

/* Text */
#SectionTitle {{ font-size: 19px; font-weight: 700; }}
#SectionCount {{ color: {FAINT}; font-size: 13px; font-weight: 600; }}
#Muted {{ color: {MUTED}; }}
#Kicker {{ color: {ACCENT}; font-size: 12px; font-weight: 800; letter-spacing: 2px; }}
#HeroTitle {{ font-size: 40px; font-weight: 800; }}
#DetailTitle {{ font-size: 32px; font-weight: 800; }}
#Meta {{ color: {MUTED}; font-size: 13px; font-weight: 600; }}
#Synopsis {{ color: #C9C9D6; font-size: 14px; }}
#EmptyState {{ color: {MUTED}; font-size: 15px; }}
#Banner {{
    background: #3A1D12; color: #FFD9CC; border: 1px solid #6B3420;
    border-radius: {RADIUS}px; padding: 10px 14px; font-weight: 600;
}}

/* Buttons */
QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 9px 16px; font-weight: 700; font-size: 14px;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#Primary {{ background: {ACCENT}; border: none; color: white; padding: 10px 22px; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{ background: {SURFACE_3}; color: {FAINT}; }}
QPushButton#Glass {{ background: rgba(255,255,255,0.14); border: none; }}
QPushButton#Glass:hover {{ background: rgba(255,255,255,0.22); }}
QPushButton#Toggle {{ padding: 8px 14px; font-size: 13px; }}
QPushButton#Toggle:checked {{ background: {TEXT}; color: {BG}; border-color: {TEXT}; }}
QPushButton#RowAction {{
    background: transparent; border: none; color: {FAINT}; font-size: 13px; font-weight: 600; padding: 2px 6px;
}}
QPushButton#RowAction:hover {{ color: {TEXT}; }}
QPushButton#Arrow {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 15px;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
    padding: 0; font-size: 16px; color: {MUTED};
}}
QPushButton#Arrow:hover {{ color: {TEXT}; background: {SURFACE_2}; }}
QPushButton#Back {{ background: rgba(10,10,15,0.65); border: none; padding: 7px 14px; font-size: 13px; }}
QPushButton#Back:hover {{ background: rgba(40,40,52,0.9); }}

/* Inputs */
QLineEdit#SearchBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 12px 18px; font-size: 18px; selection-background-color: {ACCENT};
}}
QLineEdit#SearchBox:focus {{ border-color: {ACCENT}; }}
QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 8px 12px; font-weight: 700;
}}
QComboBox::drop-down {{ border: none; width: 22px; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("__CHEVRON__"); width: 10px; height: 6px; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
}}
QCheckBox {{ color: {MUTED}; font-weight: 600; spacing: 8px; }}
QCheckBox:disabled {{ color: {FAINT}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {SURFACE_3}; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("__CHECK__"); }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 5px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 16px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}

/* Scrolling */
QScrollArea {{ border: none; background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QListView {{ background: transparent; border: none; }}

/* Setup assistant and message boxes */
QDialog, QMessageBox {{ background: {BG}; }}
#DialogTitle {{ font-size: 24px; font-weight: 800; }}
#SetupRow {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#SetupTitle {{ font-size: 15px; font-weight: 700; }}
#SetupDot {{ font-size: 16px; font-weight: 900; color: {FAINT}; }}
#SetupDot[state="ok"] {{ color: {GOOD}; }}
#SetupDot[state="needed"] {{ color: {ACCENT}; }}
#SetupDot[state="warn"] {{ color: #F5B83D; }}
QRadioButton {{ color: {TEXT}; spacing: 8px; font-weight: 600; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1px solid {FAINT}; background: {SURFACE}; }}
QRadioButton::indicator:checked {{ border: 1px solid {ACCENT}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #FFFFFF, stop:0.32 #FFFFFF, stop:0.38 {ACCENT}, stop:1 {ACCENT}); }}
QMessageBox QLabel {{ color: {TEXT}; }}

#Toast {{
    background: {SURFACE_3}; color: {TEXT}; border: 1px solid #3A3A4C; border-radius: 10px;
    padding: 11px 18px; font-weight: 600;
}}
#Toast[kind="error"] {{ background: #3A1717; border-color: #6E2A2A; color: #FFD6D6; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, SURFACE_2), (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT), (QPalette.ColorRole.Button, SURFACE_2),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.ToolTipBase, SURFACE_2),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, FAINT),
    ]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET.replace("__CHEVRON__", _chevron_path()).replace("__CHECK__", _check_path()))


def _check_path() -> str:
    path = Path(tempfile.gettempdir()) / "anigui-check-v1.png"
    if not path.exists():
        img = QImage(28, 28, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#FFFFFF"), 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(7, 14.5), QPointF(12, 19.5), QPointF(21, 9)])
        p.end()
        img.save(str(path))
    return path.as_posix()


def _chevron_path() -> str:
    """Stylesheets can only load arrow images from files, so draw one at startup."""
    path = Path(tempfile.gettempdir()) / "anigui-chevron-v1.png"
    if not path.exists():
        img = QImage(20, 12, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(MUTED), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(3, 3), QPointF(10, 9), QPointF(17, 3)])
        p.end()
        img.save(str(path))
    return path.as_posix()

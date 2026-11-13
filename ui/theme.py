"""Colors, fonts and the app-wide stylesheet."""

from __future__ import annotations

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
MATURE = "#C0392B"

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
QMainWindow {{ background: {BG}; }}
#Page, #PageBody {{ background: transparent; }}   /* the window's backdrop (cinema.Ambient) shows through */
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}

/* Sidebar */
#Sidebar {{ background: rgba(12, 12, 18, 0.62); border-right: 1px solid rgba(255, 255, 255, 0.07); }}
#Brand {{ font-size: 21px; font-weight: 800; color: {TEXT}; padding: 4px 6px 18px 6px; }}
#NavButton {{
    text-align: left; padding: 10px 14px; border: none; border-radius: {RADIUS}px;
    background: transparent; color: {MUTED}; font-size: 14px; font-weight: 600;
}}
#NavButton:hover {{ background: rgba(255, 255, 255, 0.07); color: {TEXT}; }}
#NavButton:checked {{ background: rgba(255, 255, 255, 0.11); color: {TEXT}; border-left: 3px solid {ACCENT}; }}
/* My Library in the sidebar (2.0): your lists nest under Library */
#NavSub {{
    text-align: left; padding: 6px 10px 6px 42px; border: none; border-radius: {RADIUS}px;
    background: transparent; color: {MUTED}; font-size: 13px; font-weight: 600;
}}
#NavSub:hover {{ background: rgba(255, 255, 255, 0.06); color: {TEXT}; }}
#NavSub:checked {{ background: rgba(255, 255, 255, 0.10); color: {TEXT}; }}
#NavNew {{
    text-align: left; padding: 5px 10px 5px 42px; border: none; background: transparent;
    color: {FAINT}; font-size: 12px; font-weight: 600;
}}
#NavNew:hover {{ color: {TEXT}; }}
QToolButton#NavChevron {{ border: none; background: transparent; color: {FAINT}; font-size: 12px; }}
QToolButton#NavChevron:hover {{ color: {TEXT}; }}
#LibraryTitle {{ font-size: 26px; font-weight: 800; }}
#LibrarySub {{ color: {MUTED}; font-size: 13px; }}
QPushButton#TagFilter {{ padding: 6px 12px; font-size: 12px; border-radius: 14px; }}
QPushButton#TagFilter:checked {{ background: {ACCENT}; color: #FFFFFF; border-color: {ACCENT}; }}
QListView#Timeline {{ background: transparent; }}
QFrame#YoursPanel {{ background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; }}
#YoursTitle {{ font-size: 15px; font-weight: 800; }}
#YoursHint {{ color: {FAINT}; font-size: 12px; font-weight: 600; }}
QPushButton#TagChip {{ padding: 4px 10px; font-size: 12px; border-radius: 12px; background: rgba(255,255,255,0.10); border: none; }}
QPushButton#TagChip:hover {{ background: rgba(255,255,255,0.18); }}
QLineEdit#TagBox {{ padding: 5px 10px; font-size: 12px; border-radius: 12px; background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10); }}
QLineEdit#TagBox:focus {{ border-color: {ACCENT}; }}
QPlainTextEdit#NoteBox {{ background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
    padding: 6px 8px; font-size: 13px; color: {TEXT}; }}
QPlainTextEdit#NoteBox:focus {{ border-color: {ACCENT}; }}
/* Privacy (2.0) */
QFrame#NeverPanel {{ background: rgba(63, 174, 106, 0.10); border: 1px solid rgba(63, 174, 106, 0.35); border-radius: 14px; }}
#NeverLine {{ color: {TEXT}; font-size: 13px; }}
QFrame#DestCard {{ background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; }}
#DestName {{ font-size: 15px; font-weight: 800; }}
#DestLine {{ color: {MUTED}; font-size: 12px; }}
#DestHosts {{ color: {FAINT}; font-size: 11px; font-family: Menlo, monospace; }}
#LiveHost {{ color: {TEXT}; font-size: 12px; font-family: Menlo, monospace; }}
#LockTitle {{ font-size: 24px; font-weight: 800; }}
#LockSub {{ color: {MUTED}; font-size: 14px; }}
QPushButton#PrivatePill {{ background: rgba(140, 100, 255, 0.22); color: #E2D8FF; border: 1px solid rgba(160, 130, 255, 0.5);
    border-radius: 12px; padding: 5px 10px; font-size: 12px; font-weight: 700; text-align: left; }}
QPushButton#PrivatePill:hover {{ background: rgba(140, 100, 255, 0.34); }}
QListWidget#HomeRows {{ background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
    padding: 4px; font-size: 13px; }}
QListWidget#HomeRows::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget#HomeRows::item:hover {{ background: rgba(255,255,255,0.06); }}
QPushButton#WrapArrow {{ background: rgba(255,255,255,0.16); border: none; border-radius: 22px; min-width: 44px;
    min-height: 44px; font-size: 26px; font-weight: 700; color: #FFFFFF; }}
QPushButton#WrapArrow:hover {{ background: rgba(255,255,255,0.28); }}
QPushButton#WrapArrow:disabled {{ background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.3); }}
QPushButton#DrawerClose {{ background: rgba(255,255,255,0.08); border: none; border-radius: 15px; color: {MUTED};
    font-size: 13px; font-weight: 700; padding: 0; }}
QPushButton#DrawerClose:hover {{ background: rgba(255,255,255,0.18); color: {TEXT}; }}
#PlayerCard {{ background: {SURFACE_2}; border: 1.5px solid {BORDER}; border-radius: 12px; }}
#PlayerCard:hover {{ border-color: {SURFACE_3}; }}
#PlayerCard[selected="true"] {{ border: 1.5px solid {ACCENT}; }}
#PlayerRadio {{ border: 2px solid {FAINT}; border-radius: 8px; background: transparent; }}
#PlayerRadio[selected="true"] {{ border: 2px solid {ACCENT}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
    fx:0.5, fy:0.5, stop:0 {ACCENT}, stop:0.42 {ACCENT}, stop:0.5 transparent); }}
#PlayerName {{ font-size: 15px; font-weight: 800; }}
#PlayerTag {{ background: {SURFACE_3}; color: {MUTED}; border-radius: 5px; padding: 2px 6px; font-size: 10px;
    font-weight: 800; }}
#PlayerTag[light="true"] {{ background: rgba(61, 214, 140, 0.16); color: {GOOD}; }}
#PlayerValue {{ font-size: 14px; font-weight: 800; }}
#FeatYes {{ color: {GOOD}; font-weight: 900; }}
#FeatNo {{ color: {FAINT}; font-weight: 900; }}
#FeatText {{ font-size: 12px; }}
#FeatOff {{ font-size: 12px; color: {FAINT}; }}
#MeasureBox {{ background: {SURFACE_2}; border: 1px dashed {SURFACE_3}; border-radius: 10px; }}
#BatteryHint {{ background: rgba(18, 18, 26, 0.96); border: 1px solid #2C2C3A; border-radius: 12px; }}
#BatteryIcon {{ font-size: 20px; }}
#Greeting {{ color: rgba(255, 255, 255, 0.86); font-size: 15px; font-weight: 700; background: rgba(0, 0, 0, 0.28);
    border-radius: 12px; padding: 5px 12px; }}
#WelcomeTitle {{ font-size: 28px; font-weight: 800; }}
#WelcomeRow {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#WelcomeIcon {{ font-size: 22px; }}
#WelcomeKey {{ background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 6px; padding: 3px 8px;
    font-size: 12px; font-weight: 800; color: {TEXT}; }}
#WelcomeDot {{ background: {FAINT}; border-radius: 4px; }}
#WelcomeDot[on="true"] {{ background: {ACCENT}; }}
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
QPushButton#PageTab {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 11px; font-size: 12px; font-weight: 700; color: {MUTED};
}}
QPushButton#PageTab:hover {{ color: {TEXT}; border-color: {FAINT}; }}
QPushButton#PageTab:checked {{ background: {TEXT}; color: {BG}; border-color: {TEXT}; }}
QLineEdit#JumpBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 10px; font-size: 12px; selection-background-color: {ACCENT};
}}
QLineEdit#JumpBox:focus {{ border-color: {ACCENT}; }}
#JumpError {{ color: #FF8A80; font-size: 12px; }}
#FillerNote {{ color: #E9B44C; font-size: 13px; font-weight: 600; }}
QWidget#StickyBar {{ background: rgba(14, 14, 20, 0.90); border-bottom: 1px solid rgba(255, 255, 255, 0.07); }}
#StickyTitle {{ font-size: 15px; font-weight: 800; }}
#MatureBadge {{ background: {MATURE}; color: #FFFFFF; font-size: 11px; font-weight: 800; padding: 2px 7px; border-radius: 5px; }}
#ContentPill {{ background: {SURFACE_3}; color: #D6D6E0; font-size: 12px; padding: 3px 9px; border-radius: 6px; }}
#ContentLabel {{ color: {MUTED}; font-size: 13px; font-weight: 600; }}
#MatureTitle {{ font-size: 18px; font-weight: 800; }}
#MatureText {{ color: #C9C9D6; font-size: 13px; }}
#HiddenNote {{ color: {MUTED}; font-size: 13px; }}
QPushButton#InfoButton {{
    background: transparent; border: 1px solid {FAINT}; border-radius: 10px; color: {MUTED};
    min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; padding: 0;
    font-size: 12px; font-weight: 800;
}}
QPushButton#InfoButton:hover {{ color: {TEXT}; border-color: {MUTED}; }}
QPushButton#InfoButton:checked {{ background: {SURFACE_3}; color: {TEXT}; border-color: {MUTED}; }}
QFrame#Explainer {{ background: {SURFACE_2}; border: 1px solid {SURFACE_3}; border-radius: 10px; }}
#ExplainerTitle {{ font-size: 14px; font-weight: 800; }}
#ExplainerText {{ color: #C9C9D6; font-size: 13px; }}
#ScaleBox {{ background: {SURFACE_3}; color: #D6D6E0; font-size: 12px; padding: 6px 8px; border-radius: 6px; }}
QFrame#NoteCard {{ background: {SURFACE_2}; border: 1px solid #3A3A48; border-radius: 9px; }}
#NoteCardTitle {{ font-size: 13px; font-weight: 800; color: {TEXT}; }}
#NoteCardText {{ font-size: 12px; color: #C9C9D6; }}
#ContentPill:hover {{ background: #30303F; }}
QPushButton#ExtraPill {{ background: {SURFACE_2}; border: 1px solid {BORDER}; color: #D6D6E0; font-size: 12px;
    font-weight: 500; padding: 4px 11px; border-radius: 13px; }}
QPushButton#ExtraPill:hover {{ background: {SURFACE_3}; color: {TEXT}; }}
QFrame#UpNextCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#UpNextTitle {{ font-size: 15px; font-weight: 700; }}
QFrame#HolidayBanner {{ background: #12261C; border: 1px solid #1F3D2C; border-radius: 12px; }}
#HolidayTitle {{ font-size: 15px; font-weight: 700; }}
#HolidayText {{ color: #B9C9BE; }}
QPushButton#HolidayOn {{ background: #D93A3A; border: none; color: white; padding: 8px 16px; font-weight: 700; }}
QPushButton#HolidayOn:hover {{ background: #E8484A; }}
QPushButton#HolidayWait {{ background: rgba(255, 255, 255, 0.08); border: none; padding: 8px 16px; }}
QPushButton#HolidayWait:hover {{ background: rgba(255, 255, 255, 0.14); }}
QDialog#MatureDialog {{ background: {SURFACE}; }}
QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 8px 12px; font-weight: 700;
    combobox-popup: 0;   /* drop down below, MAX_ROWS tall, instead of macOS's over-the-item popup */
}}
QComboBox:hover {{ border-color: {FAINT}; }}
QComboBox::drop-down {{ border: none; width: 22px; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("__CHEVRON__"); width: 10px; height: 6px; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
    padding: 4px; outline: 0;
}}
QListView#ComboList::item {{ min-height: 28px; padding: 2px 10px; border-radius: 5px; color: {TEXT}; }}
QListView#ComboList::item:hover {{ background: {SURFACE_3}; }}
QListView#ComboList::item:selected {{ background: {ACCENT}; color: white; }}
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

/* Search filters */
QToolButton#FilterButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 6px 26px 6px 12px; font-size: 13px; font-weight: 600; color: {TEXT};
}}
QToolButton#FilterButton:hover {{ border-color: {SURFACE_3}; }}
QToolButton#FilterButton[active="true"] {{ border-color: {ACCENT}; }}
QToolButton#FilterButton::menu-indicator {{
    image: url("__CHEVRON__"); width: 10px; height: 6px; subcontrol-position: right center; right: 9px;
}}
QComboBox#FilterCombo {{ font-size: 13px; padding: 6px 10px; min-width: 96px; }}
QComboBox#FilterCombo:disabled {{ color: {FAINT}; background: {SURFACE}; }}

/* Stats */
#StatTile, #StatPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#StatLabel {{ color: {MUTED}; font-size: 12px; font-weight: 700; }}
#StatValue {{ font-size: 28px; font-weight: 800; }}
#StatNote {{ color: {FAINT}; font-size: 11px; }}
#PanelTitle {{ font-size: 15px; font-weight: 700; }}

/* Calendar */
#CalRange {{ font-size: 14px; font-weight: 700; min-width: 120px; qproperty-alignment: AlignCenter; }}
#CalDay {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#CalDay[today="true"] {{ border: 1px solid {ACCENT}; }}
#CalDayTitle {{ color: {MUTED}; font-size: 13px; font-weight: 800; padding: 0 2px 2px 2px; }}
#CalDay[today="true"] #CalDayTitle {{ color: {ACCENT}; }}
#CalDayTitle[holiday="true"] {{ color: #6FD39A; }}
#CalEntry {{ background: {SURFACE_2}; border: 1px solid transparent; border-radius: 10px; }}
#CalEntry:hover {{ border-color: {SURFACE_3}; }}
#CalTitle {{ font-size: 12px; font-weight: 700; }}
#CalMeta {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
#CalEp {{ font-size: 13px; font-weight: 800; }}
#CalBadge {{ color: {FAINT}; font-size: 10px; font-weight: 800; }}
#CalBadge[state="available"] {{ color: white; background: {ACCENT}; border-radius: 6px; padding: 1px 6px; }}
#CalBadge[state="pending"] {{ color: #F5B83D; }}
#CalEmpty {{ color: {FAINT}; padding: 4px; }}

/* Release signer */
#SignerDetails {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 12px; color: #C9C9D6; }}
#SignerProblem {{ color: #FFD6D6; background: #3A1717; border: 1px solid #6E2A2A; border-radius: 8px; padding: 8px 10px; }}

/* Update progress */
QProgressBar#UpdateBar {{ background: {SURFACE_2}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar#UpdateBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

/* Settings */
#SettingsNav {{
    background: {SIDEBAR}; border: none; border-right: 1px solid {BORDER}; padding: 18px 10px;
    font-size: 14px; font-weight: 600;
}}
#SettingsNav::item {{ color: {MUTED}; padding: 9px 12px; border-radius: {RADIUS}px; margin-bottom: 2px; }}
#SettingsNav::item:hover {{ background: {SURFACE}; color: {TEXT}; }}
#SettingsNav::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
#SettingsPage, #SettingsScroll {{ background: {BG}; }}
#SettingsGroup {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#SettingsDivider {{ color: {BORDER}; background: {BORDER}; max-height: 1px; border: none; margin: 0 16px; }}
#SettingTitle {{ font-size: 14px; font-weight: 700; }}
#SettingsNote {{ color: {FAINT}; font-size: 12px; padding: 0 4px; }}

/* What's New */
#ReleaseBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#ReleaseBox[highlight="true"] {{ border: 1px solid #6B3420; }}
#ReleaseVersion {{ font-size: 16px; font-weight: 800; }}
#ReleaseTag {{ background: {ACCENT}; color: white; border-radius: 8px; padding: 1px 8px; font-size: 11px; font-weight: 800; }}
#ReleaseItem {{ color: #C9C9D6; font-size: 13px; }}

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

/* -- the built-in player's page ------------------------------------------------------ */
#RailPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#EpisodeRail {{ background: transparent; border: none; }}
#RailFind {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px; color: {TEXT}; }}
#RailFind:focus {{ border-color: {FAINT}; }}
#RailTool {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 4px 9px;
             font-size: 11px; font-weight: 700; color: {MUTED}; }}
#RailTool:hover {{ color: {TEXT}; }}
#RailTool:checked {{ color: {TEXT}; border-color: {ACCENT}; }}
#ShowCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#ShowCardTitle {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
#TheaterTitle {{ font-size: 21px; font-weight: 800; color: {TEXT}; }}
#TheaterChip {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 10px;
               font-size: 12px; font-weight: 700; color: {TEXT}; }}
#TheaterChipGreen {{ background: #12261C; border: 1px solid #2E5A40; border-radius: 8px; padding: 5px 10px;
                    font-size: 12px; font-weight: 700; color: #BFE9CF; }}
#LinkButton {{ background: transparent; border: none; padding: 2px 0; color: {MUTED}; font-weight: 700; }}
#LinkButton:hover {{ color: {TEXT}; }}

/* -- the holidays ---------------------------------------------------------------- */
#Countdown {{
    color: #F4E7C8; background: #2A1416; border: 1px solid #5A2629; border-radius: 9px;
    padding: 7px 10px; font-size: 12px; font-weight: 700;
}}
#Countdown:hover {{ background: #3A1A1D; border-color: #8A3236; }}
#HolidaysTitle {{ font-size: 28px; font-weight: 800; }}
#HolidaysCountdown {{ color: #6FD39A; font-size: 14px; font-weight: 700; }}
#AdventDoor {{
    min-height: 54px; border-radius: 10px; font-size: 16px; font-weight: 800;
    background: #7E1D22; color: #FFE8C2; border: 1px solid #A8333A;
}}
#AdventDoor:hover {{ background: #942429; }}
#AdventDoor[state="today"] {{ background: #1F6B43; color: #FFFFFF; border: 2px solid #F5C64A; }}
#AdventDoor[state="today"]:hover {{ background: #26804F; }}
#AdventDoor[state="open"] {{ background: {SURFACE}; color: {MUTED}; border: 1px dashed {FAINT}; }}
#AdventDoor[state="locked"] {{ background: {SURFACE}; color: {FAINT}; border: 1px solid {BORDER}; }}
#AdventPickBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#AdventPick {{ color: {TEXT}; font-size: 14px; }}
#SurpriseButton {{ color: #F5C64A; }}
#ComingSoon {{ background: rgba(29, 29, 40, 240); border: 2px solid #A8333A; border-radius: 16px; }}
#ComingSoonIcon {{ font-size: 40px; }}
#ComingSoonTitle {{ font-size: 22px; font-weight: 800; color: {TEXT}; }}
#ComingSoonBody {{ font-size: 13px; color: {MUTED}; }}
#ComingSoonUnit {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; min-width: 52px; }}
#ComingSoonValue {{ font-size: 22px; font-weight: 800; color: {TEXT}; }}
#ComingSoonLabel {{ font-size: 11px; color: {MUTED}; }}
#ChristmasScrim {{ background: rgba(4, 6, 10, 150); }}
#ChristmasCard {{ background: {SURFACE_2}; border: 2px solid #A8333A; border-radius: 16px; }}
#ChristmasIcon {{ font-size: 44px; }}
#ChristmasTitle {{ font-size: 22px; font-weight: 800; color: {TEXT}; }}
#ChristmasBody {{ font-size: 14px; color: {MUTED}; }}
#SectionTitle[sweater="true"] {{ color: #FFFFFF; font-size: 22px; font-weight: 800; }}

#Toast {{
    background: {SURFACE_3}; color: {TEXT}; border: 1px solid #3A3A4C; border-radius: 10px;
    padding: 11px 18px; font-weight: 600;
}}
#Toast[kind="error"] {{ background: #3A1717; border-color: #6E2A2A; color: #FFD6D6; }}
#Toast[kind="holiday"] {{
    border: 2px solid qlineargradient(spread:repeat, x1:0, y1:0, x2:0.035, y2:0.12,
        stop:0 #E2364B, stop:0.5 #E2364B, stop:0.501 #FFFFFF, stop:1 #FFFFFF);
}}
"""


# The holiday theme swaps the orange accent for red, and the small kickers above titles for
# pine green. Painted widgets read theme.ACCENT when they paint, so changing these module
# values and repainting is enough; the stylesheet is rebuilt by apply_theme().
NORMAL_COLORS = {"ACCENT": "#FF6B3D", "ACCENT_HOVER": "#FF8559", "ACCENT_PRESSED": "#E85A2E", "KICKER": "#FF6B3D"}
HOLIDAY_COLORS = {"ACCENT": "#E0403C", "ACCENT_HOVER": "#EC5A55", "ACCENT_PRESSED": "#C13431", "KICKER": "#3FAE6A"}
HOLIDAY = False
KICKER = NORMAL_COLORS["KICKER"]


# Make it yours (2.0): your accent color. The holiday theme's red and green still win in December.
ACCENTS = (
    ("ember", "Ember", "#FF6B3D"),
    ("sakura", "Sakura", "#F0679A"),
    ("ocean", "Ocean", "#3D8DFF"),
    ("matcha", "Matcha", "#43B87A"),
    ("violet", "Violet", "#9B6BFF"),
    ("gold", "Gold", "#F2B23D"),
)
_USER_ACCENT = NORMAL_COLORS["ACCENT"]


def accent_hex(key: str) -> str:
    return next((hx for k, _n, hx in ACCENTS if k == key), NORMAL_COLORS["ACCENT"])


def _colors_for(hexcolor: str) -> dict[str, str]:
    c = QColor(hexcolor)
    if c.name().lower() == NORMAL_COLORS["ACCENT"].lower():
        return dict(NORMAL_COLORS)
    return {"ACCENT": c.name(), "ACCENT_HOVER": c.lighter(116).name(), "ACCENT_PRESSED": c.darker(112).name(),
            "KICKER": c.name()}


def set_accent(hexcolor: str) -> None:
    """Your accent (call apply_theme() after, and repaint)."""
    global _USER_ACCENT, ACCENT, ACCENT_HOVER, ACCENT_PRESSED, KICKER
    _USER_ACCENT = QColor(hexcolor).name() if QColor(hexcolor).isValid() else NORMAL_COLORS["ACCENT"]
    if not HOLIDAY:
        colors = _colors_for(_USER_ACCENT)
        ACCENT, ACCENT_HOVER, ACCENT_PRESSED, KICKER = (colors[k] for k in ("ACCENT", "ACCENT_HOVER", "ACCENT_PRESSED", "KICKER"))


def set_holiday(on: bool) -> None:
    """Switch the colors (call apply_theme() after, and repaint)."""
    global HOLIDAY, ACCENT, ACCENT_HOVER, ACCENT_PRESSED, KICKER
    colors = HOLIDAY_COLORS if on else _colors_for(_USER_ACCENT)
    HOLIDAY = on
    ACCENT, ACCENT_HOVER, ACCENT_PRESSED, KICKER = (colors[k] for k in ("ACCENT", "ACCENT_HOVER", "ACCENT_PRESSED", "KICKER"))


def stylesheet() -> str:
    sheet = STYLESHEET.replace("__CHEVRON__", _chevron_path()).replace("__CHECK__", _check_path())
    normal = NORMAL_COLORS
    sheet = sheet.replace(f"#Kicker {{ color: {normal['ACCENT']};", "#Kicker { color: __KICKER__;")
    for key in ("ACCENT_HOVER", "ACCENT_PRESSED", "ACCENT"):
        sheet = sheet.replace(normal[key], f"__{key}__")
    for key in ("ACCENT_HOVER", "ACCENT_PRESSED", "ACCENT", "KICKER"):
        sheet = sheet.replace(f"__{key}__", globals()[key])
    return sheet


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
    app.setStyleSheet(stylesheet())


def _asset_dir() -> Path:
    """Drawn images live in AniGUI's own cache folder, not the shared temp folder
    (where another account could plant a file under the same name)."""
    from core import paths

    path = paths.cache_dir() / "ui"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _check_path() -> str:
    path = _asset_dir() / "check-v1.png"
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
    path = _asset_dir() / "chevron-v1.png"
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

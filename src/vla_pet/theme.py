from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

CREAM = "#FFF6E6"
PAPER = "#FFFDF7"
TOMATO = "#B9362E"
TOMATO_HOVER = "#D04B40"
COCOA = "#4A3028"
MINT = "#9CC9AE"
GOLD = "#E3AA42"
SOFT_BORDER = "#E7CDB7"
MUTED = "#816B62"


def companion_stylesheet() -> str:
    return f"""
    QWidget {{
        color: {COCOA};
        font-family: 'Noto Sans', 'DejaVu Sans', sans-serif;
        font-size: 13px;
    }}
    QDialog, QWidget#CompanionPanel {{ background: {CREAM}; }}
    QLabel#HeroTitle {{ color: {TOMATO}; font-size: 25px; font-weight: 800; }}
    QLabel#SectionTitle {{ color: {COCOA}; font-size: 17px; font-weight: 700; }}
    QLabel#Muted {{ color: {MUTED}; }}
    QLabel#StatusPill {{
        background: #E4F2E8; color: #35634C; border: 1px solid {MINT};
        border-radius: 10px; padding: 4px 9px; font-weight: 600;
    }}
    QFrame#Card, QGroupBox {{
        background: {PAPER}; border: 1px solid {SOFT_BORDER}; border-radius: 14px;
        margin-top: 8px; padding: 10px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 5px; font-weight: 700; }}
    QPushButton {{
        background: {PAPER}; border: 1px solid {SOFT_BORDER}; border-radius: 10px;
        min-height: 30px; padding: 3px 12px; font-weight: 600;
    }}
    QPushButton:hover {{ border-color: {TOMATO}; background: #FFF0E6; }}
    QPushButton:pressed {{ background: #F7DDCF; }}
    QPushButton#Primary {{ background: {TOMATO}; color: white; border-color: {TOMATO}; }}
    QPushButton#Primary:hover {{ background: {TOMATO_HOVER}; }}
    QPushButton#Nav {{
        border: 0; border-radius: 11px; text-align: left; padding: 8px 12px;
        background: transparent; min-height: 34px;
    }}
    QPushButton#Nav:checked {{ color: white; background: {TOMATO}; }}
    QLineEdit, QTextEdit, QListWidget, QComboBox {{
        background: white; border: 1px solid {SOFT_BORDER}; border-radius: 9px;
        padding: 6px; selection-background-color: {TOMATO};
    }}
    QTabWidget::pane {{ border: 1px solid {SOFT_BORDER}; border-radius: 10px; background: {PAPER}; }}
    QTabBar::tab {{ padding: 7px 10px; margin: 1px; border-radius: 7px; }}
    QTabBar::tab:selected {{ background: #F3D9C8; color: {TOMATO}; font-weight: 700; }}
    QProgressBar {{
        border: 1px solid {SOFT_BORDER}; border-radius: 7px; background: white;
        text-align: center; min-height: 13px;
    }}
    QProgressBar::chunk {{ background: {MINT}; border-radius: 6px; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {SOFT_BORDER}; border-radius: 5px; min-height: 24px; }}
    """


def apply_companion_theme(widget: QWidget | QApplication) -> None:
    widget.setStyleSheet(companion_stylesheet())
    if isinstance(widget, QApplication):
        palette = QPalette(widget.palette())
        palette.setColor(QPalette.ColorRole.Window, QColor(CREAM))
        palette.setColor(QPalette.ColorRole.Base, QColor(PAPER))
        palette.setColor(QPalette.ColorRole.Text, QColor(COCOA))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(TOMATO))
        widget.setPalette(palette)

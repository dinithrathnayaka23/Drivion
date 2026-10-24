"""Colours and the application stylesheet, defined in one place.

Widgets refer to these names instead of hard-coding hex values, so the
look can be adjusted here without hunting through every file.
"""

from __future__ import annotations

from drivion.core.state import AppState

BACKGROUND = "#0a1428"
SURFACE = "#0f1e3a"
SURFACE_RAISED = "#13284a"
BORDER = "#1d3a66"
TEXT = "#cfe8ff"
TEXT_MUTED = "#6f8db3"
TEXT_DISABLED = "#4a5d7a"
ACCENT = "#4fd8ff"
WARNING = "#f2b544"
DANGER = "#ff5a6e"
SUCCESS = "#4be3a0"

STATE_COLORS: dict[AppState, str] = {
    AppState.STANDBY: "#3f6a9e",
    AppState.VERIFYING: WARNING,
    AppState.ACTIVE: ACCENT,
    AppState.SLEEPING: "#3f6a9e",
    AppState.ERROR: DANGER,
    AppState.SHUTTING_DOWN: "#55657d",
}

STYLESHEET = f"""
QMainWindow, QWidget#root, QScrollArea#scroll {{ background-color: {BACKGROUND}; border: none; }}
QLabel {{ color: {TEXT}; font-family: 'Segoe UI'; font-size: 13px; }}
QLabel#title {{ color: {ACCENT}; font-size: 22px; font-weight: 600; letter-spacing: 5px; }}
QLabel#subtitle {{ color: {TEXT_MUTED}; font-size: 11px; }}QLabel#state {{ font-size: 20px; font-weight: 600; letter-spacing: 2px; }}
QLabel#listening {{ color: {TEXT}; font-size: 13px; }}
QLabel#detail, QLabel#muted {{ color: {TEXT_MUTED}; font-size: 11px; }}
QLabel#cardTitle {{ color: {TEXT_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 2px; }}
QLabel#speaker {{ color: {TEXT_MUTED}; font-size: 11px; font-weight: 600; }}
QLabel#utterance {{ color: {TEXT}; font-size: 15px; }}
QLabel#reply {{ color: {ACCENT}; font-size: 15px; }}

QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}

QLabel#deviceChip {{
    padding: 5px 12px; border-radius: 12px; font-size: 12px;
    background-color: {SURFACE_RAISED}; color: {TEXT_MUTED}; border: 1px solid {BORDER};
}}
QLabel#deviceChip[deviceState="ACTIVE"] {{
    color: {BACKGROUND}; background-color: {ACCENT}; border-color: {ACCENT}; font-weight: 600;
}}
QLabel#deviceChip[deviceState="ERROR"] {{ color: {DANGER}; border-color: {DANGER}; }}

QListWidget {{
    background: transparent; border: none; color: {TEXT};
    font-family: 'Segoe UI'; font-size: 13px; outline: none;
}}
QListWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {SURFACE_RAISED}; }}
QListWidget::item:selected {{ background: {SURFACE_RAISED}; color: {TEXT}; }}

QPushButton {{
    color: {TEXT}; background-color: {SURFACE_RAISED}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 8px 18px; font-family: 'Segoe UI'; font-size: 13px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DISABLED}; border-color: {SURFACE_RAISED}; }}
QPushButton#exit:hover {{ border-color: {DANGER}; }}
QPushButton#small {{ padding: 3px 10px; font-size: 11px; }}

QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

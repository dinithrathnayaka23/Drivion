"""The settings screen: voice, wake word, privacy and AI provider.

Only opened while Drivion is unlocked (ACTIVE). Saving validates everything
first and writes ``config/settings.toml``; API keys go to ``.env`` and are
never shown or read back. Changes apply the next time Drivion starts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from drivion.config.settings import AppConfig, ConfigError
from drivion.config.store import check_env_values, save_settings, update_env
from drivion.ui import theme

log = logging.getLogger(__name__)

PROVIDERS = ("gemini", "groq", "openrouter")
ENV_NAMES = {name: f"DRIVION_{name.upper()}_API_KEY" for name in PROVIDERS}

STYLE = f"""
QDialog, QTabWidget::pane, QWidget#page {{ background: {theme.SURFACE}; border: none; }}
QTabBar::tab {{ background: {theme.BACKGROUND}; color: {theme.TEXT_MUTED}; padding: 8px 16px; }}
QTabBar::tab:selected {{ background: {theme.SURFACE}; color: {theme.ACCENT}; }}
QCheckBox {{ color: {theme.TEXT}; font-family: 'Segoe UI'; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget {{
    background: {theme.SURFACE_RAISED}; color: {theme.TEXT}; border: 1px solid {theme.BORDER};
    border-radius: 6px; padding: 4px 8px; font-family: 'Segoe UI';
}}
"""


def _spin(low: int, high: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    return box


def _dspin(low: float, high: float, step: float, value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setValue(value)
    return box


def _combo(options: tuple[str, ...], value: str) -> QComboBox:
    box = QComboBox()
    box.addItems(options)
    box.setCurrentText(value)
    return box


def _check(text: str, value: bool) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(value)
    return box


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        key_is_set: Callable[[str], bool],
        config_path: Path,
        env_path: Path,
        on_re_enroll: Callable[[], None] = lambda: None,
        on_delete_face: Callable[[], bool] = lambda: False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._config_path = config_path
        self._env_path = env_path
        self._on_re_enroll = on_re_enroll
        self._on_delete_face = on_delete_face
        self.setWindowTitle("Drivion settings")
        self.setStyleSheet(theme.STYLESHEET + STYLE)
        self.resize(560, 560)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._voice_page(), "Voice")
        self.tabs.addTab(self._wake_page(), "Wake word")
        self.tabs.addTab(self._privacy_page(), "Privacy")
        self.tabs.addTab(self._ai_page(key_is_set), "AI provider")

        self.message = QLabel(wordWrap=True, objectName="muted")
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.message, 1)
        buttons.addWidget(close)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(buttons)

    # ----- pages ----------------------------------------------------------------------

    @staticmethod
    def _page() -> tuple[QWidget, QFormLayout]:
        page = QWidget(objectName="page")
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        return page, form

    def _voice_page(self) -> QWidget:
        v = self._config.voice
        page, form = self._page()
        self.voice_enabled = _check("Listen for spoken commands while the dashboard is open", v.enabled)
        self.stt_model = _combo(("tiny.en", "base.en", "small.en"), v.stt_model)
        self.command_timeout = _dspin(3, 300, 5, v.command_timeout_s)
        self.tts_engine = _combo(("windows", "none"), v.tts_engine)
        self.tts_voice = QLineEdit(v.tts_voice or "", placeholderText="Default, or part of a name, e.g. Zira")
        self.tts_rate = _spin(-10, 10, v.tts_rate)
        self.tts_volume = _spin(0, 100, v.tts_volume)
        self.greeting = QLineEdit(v.greeting)
        form.addRow(self.voice_enabled)
        form.addRow("Speech model", self.stt_model)
        form.addRow("Silence before standby (s)", self.command_timeout)
        form.addRow("Spoken replies", self.tts_engine)
        form.addRow("Voice", self.tts_voice)
        form.addRow("Speed", self.tts_rate)
        form.addRow("Volume", self.tts_volume)
        form.addRow("Greeting", self.greeting)
        form.addRow(QLabel("A different speech model needs: drivion --download-models", objectName="muted"))
        return page

    def _wake_page(self) -> QWidget:
        w = self._config.wake_word
        page, form = self._page()
        self.wake_enabled = _check("Listen for the wake word in standby", w.enabled)
        self.wake_sensitivity = _dspin(0, 1, 0.05, w.sensitivity)
        self.wake_cooldown = _dspin(0.5, 10, 0.5, w.cooldown_s)
        form.addRow(self.wake_enabled)
        form.addRow("Sensitivity", self.wake_sensitivity)
        form.addRow("Ignore repeats for (s)", self.wake_cooldown)
        form.addRow(QLabel("Higher sensitivity wakes more easily, but with more false wakes.",
                           objectName="muted", wordWrap=True))
        return page

    def _privacy_page(self) -> QWidget:
        f, ui = self._config.face, self._config.ui
        page, form = self._page()
        self.liveness = _combo(("challenge", "none"), f.liveness_mode)
        self.challenges = _spin(1, 4, f.liveness_challenges)
        self.camera_mirrored = _check("My camera mirrors the picture", f.camera_mirrored)
        self.keep_crops = _check("Also keep encrypted face crops when enrolling", f.store_raw_images)
        self.cloud_ai = _check("Send requests Drivion can't handle offline to the AI provider",
                               self._config.llm.enabled)
        self.history_limit = _spin(10, 500, ui.history_limit)
        self.liveness_warning = QLabel(objectName="muted", wordWrap=True)
        self.liveness.currentTextChanged.connect(self._update_warning)
        self._update_warning(f.liveness_mode)
        form.addRow("Liveness check", self.liveness)
        form.addRow(self.liveness_warning)
        form.addRow("Head turns", self.challenges)
        form.addRow(self.camera_mirrored)
        form.addRow(self.keep_crops)
        form.addRow(self.cloud_ai)
        form.addRow("Commands kept in history", self.history_limit)
        re_enroll = QPushButton("Enroll my face again…")
        re_enroll.clicked.connect(self._on_re_enroll)
        self.delete_button = QPushButton("Delete my face data…", objectName="exit")
        self.delete_button.clicked.connect(self._delete_face)
        row = QHBoxLayout()
        row.addWidget(re_enroll)
        row.addWidget(self.delete_button)
        form.addRow(row)
        return page

    def _ai_page(self, key_is_set: Callable[[str], bool]) -> QWidget:
        llm = self._config.llm
        page, form = self._page()
        self.ai_enabled = _check("Use cloud AI for questions and free-form requests", llm.enabled)
        self.cloud_ai.toggled.connect(self.ai_enabled.setChecked)
        self.ai_enabled.toggled.connect(self.cloud_ai.setChecked)
        form.addRow(self.ai_enabled)

        self.provider_list = QListWidget()
        self.provider_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.provider_list.setFixedHeight(132)  # shows all three without scrolling
        for name in [*llm.providers, *(p for p in PROVIDERS if p not in llm.providers)]:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in llm.providers else Qt.CheckState.Unchecked)
            self.provider_list.addItem(item)
        form.addRow("Fallback order (drag)", self.provider_list)

        self.models: dict[str, QLineEdit] = {}
        self.keys: dict[str, QLineEdit] = {}
        for name in PROVIDERS:
            self.models[name] = QLineEdit(llm.model_for(name))
            form.addRow(f"{name} model", self.models[name])
            hint = "A key is set. Leave empty to keep it." if key_is_set(name) else "No key set"
            self.keys[name] = QLineEdit(placeholderText=hint, echoMode=QLineEdit.EchoMode.Password)
            self.keys[name].setAccessibleName(f"{name} API key")
            form.addRow(f"{name} key", self.keys[name])
        form.addRow(QLabel("Keys are saved only to your .env file, which is never committed.",
                           objectName="muted", wordWrap=True))
        return page

    # ----- behaviour ------------------------------------------------------------------

    def _update_warning(self, mode: str) -> None:
        self.liveness_warning.setText(
            "Off: a photo or video of you could unlock Drivion." if mode == "none"
            else "Random head turns after the face match.")

    def _delete_face(self) -> None:
        if self._on_delete_face():
            self.message.setText("Face data deleted. Enroll again before the next unlock.")

    def changes(self) -> dict:
        """Only what differs from the current config, so everything else stays as it was."""
        providers = [self.provider_list.item(i).text() for i in range(self.provider_list.count())
                     if self.provider_list.item(i).checkState() == Qt.CheckState.Checked]
        wanted = {
            "voice": {
                "enabled": self.voice_enabled.isChecked(), "stt_model": self.stt_model.currentText(),
                "command_timeout_s": self.command_timeout.value(), "tts_engine": self.tts_engine.currentText(),
                "tts_voice": self.tts_voice.text().strip() or None, "tts_rate": self.tts_rate.value(),
                "tts_volume": self.tts_volume.value(), "greeting": self.greeting.text(),
            },
            "wake_word": {
                "enabled": self.wake_enabled.isChecked(), "sensitivity": self.wake_sensitivity.value(),
                "cooldown_s": self.wake_cooldown.value(),
            },
            "face": {
                "liveness_mode": self.liveness.currentText(), "liveness_challenges": self.challenges.value(),
                "camera_mirrored": self.camera_mirrored.isChecked(),
                "store_raw_images": self.keep_crops.isChecked(),
            },
            "ui": {"history_limit": self.history_limit.value()},
            "llm": {
                "enabled": self.ai_enabled.isChecked(), "providers": providers,
                **{f"{name}_model": box.text().strip() for name, box in self.models.items()},
            },
        }
        current = self._config.model_dump()
        changed = {}
        for section, fields in wanted.items():
            different = {k: v for k, v in fields.items() if current[section][k] != v}
            if different:
                changed[section] = different
        return changed

    def save(self) -> bool:
        changes = self.changes()
        keys = {ENV_NAMES[name]: box.text().strip() for name, box in self.keys.items() if box.text().strip()}
        if not changes and not keys:
            self.message.setText("Nothing to save.")
            return False
        try:
            check_env_values(keys)  # first, so a bad key can't leave a half-finished save
            if changes:
                self._config = save_settings(self._config_path, changes)
            if keys:
                update_env(self._env_path, keys)
        except ConfigError as exc:
            self.message.setText(f"Not saved: {exc}")
            return False
        for box in self.keys.values():
            box.clear()
        log.info("Settings saved (sections: %s; keys updated: %d)", ", ".join(changes) or "none", len(keys))
        self.message.setText("Saved. Restart Drivion to apply the changes.")
        return True

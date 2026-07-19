from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vla_pet.memory import MemoryManager
from vla_pet.minigame import ReactionGameDialog
from vla_pet.permissions import Capability, PermissionLifetime
from vla_pet.persistence import StateRepository
from vla_pet.plugins import PluginHost
from vla_pet.progression import ProgressionEngine
from vla_pet.settings import CompanionSettings
from vla_pet.state import PetRuntimeState


class CompanionControlCenter(QDialog):
    settings_changed = Signal(object)
    privacy_changed = Signal(bool)
    activity_event = Signal(str, object)

    def __init__(
        self,
        settings: CompanionSettings,
        repository: StateRepository | None,
        memory: MemoryManager | None,
        plugins: PluginHost | None,
        state: PetRuntimeState | None = None,
    ) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.settings = settings
        self.repository = repository
        self.memory = memory
        self.plugins = plugins
        self.state = state
        self.progression = ProgressionEngine()
        self.game: ReactionGameDialog | None = None
        self.setWindowTitle("Momo companion controls")
        self.resize(620, 480)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._privacy_tab(), "Privacy")
        self.tabs.addTab(self._memory_tab(), "Memory")
        self.tabs.addTab(self._tasks_tab(), "Tasks")
        self.tabs.addTab(self._play_tab(), "Play")
        self.tabs.addTab(self._plugins_tab(), "Plugins")
        self.tabs.addTab(self._audit_tab(), "Activity")
        close = QPushButton("Close")
        close.clicked.connect(self.hide)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(close)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.ai_enabled = QCheckBox("Use local AI on the next launch")
        self.ai_enabled.setChecked(self.settings.ai_enabled)
        self.memory_enabled = QCheckBox("Remember explicit preferences, tasks, and shared events")
        self.memory_enabled.setChecked(self.settings.memory_enabled)
        self.persist_chat = QCheckBox("Persist conversation text")
        self.persist_chat.setChecked(self.settings.persist_conversation)
        self.voice_enabled = QCheckBox("Enable push-to-talk microphone")
        self.voice_enabled.setChecked(self.settings.voice_enabled)
        self.tts_enabled = QCheckBox("Read pet replies aloud")
        self.tts_enabled.setChecked(self.settings.tts_enabled)
        self.persona_name = QLineEdit(self.settings.persona_name)
        self.persona_name.setPlaceholderText("Use character default")
        self.persona_prompt = QTextEdit(self.settings.persona_prompt)
        self.persona_prompt.setPlaceholderText("Use character persona prompt")
        self.persona_prompt.setMaximumHeight(100)
        self.update_channel = QComboBox()
        self.update_channel.addItems(("stable", "beta", "nightly"))
        self.update_channel.setCurrentText(self.settings.update_channel)
        self.auto_update = QCheckBox("Check signed update manifests")
        self.auto_update.setChecked(self.settings.auto_update_enabled)
        self.update_manifest_url = QLineEdit(self.settings.update_manifest_url)
        self.update_manifest_url.setPlaceholderText("https://updates.example/update.json")
        self.update_public_key = QLineEdit(self.settings.update_public_key)
        self.update_public_key.setPlaceholderText("Base64 Ed25519 public key")
        self.update_key_id = QLineEdit(self.settings.update_key_id)
        save = QPushButton("Save general settings")
        save.clicked.connect(self._save_general)
        form.addRow(self.ai_enabled)
        form.addRow(self.memory_enabled)
        form.addRow(self.persist_chat)
        form.addRow(self.voice_enabled)
        form.addRow(self.tts_enabled)
        form.addRow("Persona name", self.persona_name)
        form.addRow("Persona prompt", self.persona_prompt)
        form.addRow("Update channel", self.update_channel)
        form.addRow(self.auto_update)
        form.addRow("Signed manifest URL", self.update_manifest_url)
        form.addRow("Release key id", self.update_key_id)
        form.addRow("Release public key", self.update_public_key)
        form.addRow(save)
        return page

    def _privacy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.privacy_mode = QCheckBox("Privacy mode: stop all optional observation")
        self.privacy_mode.setChecked(self.settings.privacy_mode)
        self.notifications = QCheckBox("Read desktop notifications during this session")
        self.notifications.setChecked(self.settings.notifications_enabled)
        self.active_window = QCheckBox("Read active application metadata")
        self.active_window.setChecked(self.settings.active_window_enabled)
        self.idle_detection = QCheckBox("Read user-idle duration")
        self.idle_detection.setChecked(self.settings.idle_detection_enabled)
        self.system_status = QCheckBox("Read battery and network state")
        self.system_status.setChecked(self.settings.system_status_enabled)
        self.coding_status = QCheckBox("Read an explicitly configured coding status marker")
        self.coding_status.setChecked(self.settings.coding_status_enabled)
        self.proactive = QCheckBox("Allow rate-limited proactive reactions with visible reasons")
        self.proactive.setChecked(self.settings.proactive_enabled)
        self.denied_apps = QLineEdit(", ".join(self.settings.denied_applications))
        self.denied_titles = QLineEdit(", ".join(self.settings.denied_title_fragments))
        save = QPushButton("Save privacy settings")
        save.clicked.connect(self._save_privacy)
        for widget in (
            self.privacy_mode,
            self.notifications,
            self.active_window,
            self.idle_detection,
            self.system_status,
            self.coding_status,
            self.proactive,
        ):
            layout.addWidget(widget)
        layout.addWidget(QLabel("Denied applications (comma separated)"))
        layout.addWidget(self.denied_apps)
        layout.addWidget(QLabel("Denied window-title fragments (comma separated)"))
        layout.addWidget(self.denied_titles)
        layout.addWidget(save)
        layout.addStretch(1)
        return page

    def _memory_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.memory_list = QListWidget()
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        delete = QPushButton("Delete selected")
        clear = QPushButton("Clear all memories")
        export = QPushButton("Export private data")
        refresh.clicked.connect(self.refresh_memory)
        delete.clicked.connect(self._delete_memory)
        clear.clicked.connect(self._clear_memory)
        export.clicked.connect(self._export)
        for button in (refresh, delete, clear, export):
            row.addWidget(button)
        layout.addWidget(QLabel("Only summaries are shown. Raw screenshots and audio are never stored."))
        layout.addWidget(self.memory_list)
        layout.addLayout(row)
        return page

    def _tasks_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.task_list = QListWidget()
        refresh = QPushButton("Refresh")
        complete = QPushButton("Complete selected")
        refresh.clicked.connect(self.refresh_tasks)
        complete.clicked.connect(self._complete_task)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addWidget(complete)
        layout.addWidget(self.task_list)
        layout.addLayout(row)
        return page

    def _plugins_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.plugin_list = QListWidget()
        self.plugin_list.itemChanged.connect(self._plugin_changed)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_plugins)
        layout.addWidget(
            QLabel("Third-party plugins require integrity, a trusted signature, declared permissions, and a sandbox.")
        )
        layout.addWidget(self.plugin_list)
        layout.addWidget(refresh)
        return page

    def _play_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.progress_label = QLabel()
        self.inventory_list = QListWidget()
        snack = QPushButton("Give snack")
        ball = QPushButton("Play with ball")
        daily = QPushButton("Daily activity")
        game = QPushButton("Play Catch the Star")
        snack.clicked.connect(lambda: self._use_item("snack"))
        ball.clicked.connect(lambda: self._use_item("ball"))
        daily.clicked.connect(self._daily)
        game.clicked.connect(self._open_game)
        row = QHBoxLayout()
        for button in (snack, ball, daily, game):
            row.addWidget(button)
        layout.addWidget(QLabel("Progress is positive-only: time away never removes items, XP, or affection."))
        layout.addWidget(self.progress_label)
        layout.addWidget(self.inventory_list)
        layout.addLayout(row)
        self.refresh_progression()
        return page

    def _audit_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.audit_list = QListWidget()
        refresh = QPushButton("Refresh redacted activity")
        refresh.clicked.connect(self.refresh_audit)
        layout.addWidget(QLabel("Activity contains decisions and metadata, never tool input or private content."))
        layout.addWidget(self.audit_list)
        layout.addWidget(refresh)
        return page

    def _save_general(self) -> None:
        if self.auto_update.isChecked() and not (
            self.update_manifest_url.text().strip() and self.update_public_key.text().strip()
        ):
            QMessageBox.warning(
                self,
                "Update source required",
                "Automatic checks need both a signed manifest URL and its Ed25519 public key.",
            )
            return
        self.settings.ai_enabled = self.ai_enabled.isChecked()
        self.settings.memory_enabled = self.memory_enabled.isChecked()
        self.settings.persist_conversation = self.persist_chat.isChecked()
        self.settings.voice_enabled = self.voice_enabled.isChecked()
        self.settings.tts_enabled = self.tts_enabled.isChecked()
        self.settings.persona_name = self.persona_name.text().strip()[:80]
        self.settings.persona_prompt = self.persona_prompt.toPlainText().strip()[:1200]
        self.settings.update_channel = self.update_channel.currentText()
        self.settings.auto_update_enabled = self.auto_update.isChecked()
        self.settings.update_manifest_url = self.update_manifest_url.text().strip()[:2048]
        self.settings.update_public_key = self.update_public_key.text().strip()[:512]
        self.settings.update_key_id = self.update_key_id.text().strip()[:120]
        self._commit()

    def _save_privacy(self) -> None:
        self.settings.privacy_mode = self.privacy_mode.isChecked()
        self.settings.notifications_enabled = self.notifications.isChecked()
        self.settings.active_window_enabled = self.active_window.isChecked()
        self.settings.idle_detection_enabled = self.idle_detection.isChecked()
        self.settings.system_status_enabled = self.system_status.isChecked()
        self.settings.coding_status_enabled = self.coding_status.isChecked()
        self.settings.proactive_enabled = self.proactive.isChecked()
        self.settings.denied_applications = self._csv(self.denied_apps.text())
        self.settings.denied_title_fragments = self._csv(self.denied_titles.text())
        self._commit()
        self.privacy_changed.emit(self.settings.privacy_mode)

    def _commit(self) -> None:
        self.settings.save(self.repository)
        self.settings_changed.emit(self.settings)
        QMessageBox.information(self, "Saved", "Companion settings were saved locally.")

    def refresh_all(self) -> None:
        self.refresh_memory()
        self.refresh_tasks()
        self.refresh_plugins()
        self.refresh_audit()
        self.refresh_progression()

    def refresh_progression(self) -> None:
        self.inventory_list.clear()
        if self.state is None:
            self.progress_label.setText("Progression is unavailable in safe mode.")
            return
        progress = self.state.progression
        self.progress_label.setText(
            f"Level {progress.level} • XP {progress.xp} • affection {progress.affection_points} • "
            f"achievements {len(progress.achievements)}"
        )
        for name, count in sorted(progress.inventory.items()):
            self.inventory_list.addItem(f"{name} × {count}")

    def _use_item(self, name: str) -> None:
        if self.state is None:
            return
        if self.progression.use_item(self.state, name):
            self.progression.award(self.state, 3, reason="item")
            if self.repository:
                self.repository.save_state(self.state)
            self.activity_event.emit("item.used", {"item": name})
        self.refresh_progression()

    def _daily(self) -> None:
        if self.state is not None:
            self.progression.daily_check_in(self.state)
            if self.repository:
                self.repository.save_state(self.state)
            self.activity_event.emit("daily.completed", {})
            self.refresh_progression()

    def _open_game(self) -> None:
        self.game = ReactionGameDialog()
        self.game.game_finished.connect(self._game_finished)
        self.game.show()

    def _game_finished(self, score: int) -> None:
        if self.state is not None:
            self.progression.award(self.state, max(1, score * 2), reason="minigame")
            if self.repository:
                self.repository.save_state(self.state)
            self.refresh_progression()

    def refresh_memory(self) -> None:
        self.memory_list.clear()
        if self.memory is None:
            self.memory_list.addItem("Memory is unavailable in safe mode.")
            return
        for row in self.memory.retrieve("", limit=200):
            item = QListWidgetItem(f"[{row['tier']}] {row['summary']}")
            item.setData(Qt.ItemDataRole.UserRole, row["memory_id"])
            self.memory_list.addItem(item)

    def _delete_memory(self) -> None:
        item = self.memory_list.currentItem()
        if item and self.repository:
            self.repository.delete_memory(str(item.data(Qt.ItemDataRole.UserRole)))
            self.refresh_memory()

    def _clear_memory(self) -> None:
        if self.repository and QMessageBox.question(
            self, "Clear memories", "Delete all companion memories?"
        ) is QMessageBox.StandardButton.Yes:
            self.repository.clear_memories()
            self.refresh_memory()

    def refresh_tasks(self) -> None:
        self.task_list.clear()
        if not self.repository:
            return
        for row in self.repository.list_tasks(limit=200):
            item = QListWidgetItem(f"[{row['status']}] {row['kind']}: {row['title']}")
            item.setData(Qt.ItemDataRole.UserRole, row["task_id"])
            self.task_list.addItem(item)

    def _complete_task(self) -> None:
        item = self.task_list.currentItem()
        if item and self.repository:
            self.repository.update_task_status(str(item.data(Qt.ItemDataRole.UserRole)), "done")
            self.refresh_tasks()

    def refresh_plugins(self) -> None:
        self.plugin_list.blockSignals(True)
        try:
            self.plugin_list.clear()
            if not self.plugins:
                return
            for manifest in self.plugins.manifests():
                item = QListWidgetItem(
                    f"{manifest.display_name} {manifest.version} — {manifest.license}"
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if self.plugins.enabled(manifest.name)
                    else Qt.CheckState.Unchecked
                )
                item.setData(Qt.ItemDataRole.UserRole, manifest.name)
                self.plugin_list.addItem(item)
        finally:
            self.plugin_list.blockSignals(False)

    def _plugin_changed(self, item: QListWidgetItem) -> None:
        if not self.plugins:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        enabled = item.checkState() is Qt.CheckState.Checked
        manifest = next(value for value in self.plugins.manifests() if value.name == name)
        subject = f"plugin.{name}"
        if enabled:
            capabilities = ", ".join(permission.capability.value for permission in manifest.permissions)
            detail = capabilities or "no additional data capabilities"
            accepted = QMessageBox.question(
                self,
                "Enable plugin?",
                f"Enable {manifest.display_name}?\n\nDeclared access: {detail}",
            ) is QMessageBox.StandardButton.Yes
            if not accepted:
                self.plugin_list.blockSignals(True)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.plugin_list.blockSignals(False)
                return
            self.plugins.broker.grant(
                Capability.PLUGIN_EXECUTE,
                lifetime=PermissionLifetime.SESSION,
                subject=subject,
                reason="enabled in plugin manager",
            )
            for permission in manifest.permissions:
                self.plugins.broker.grant(
                    permission.capability,
                    lifetime=PermissionLifetime.SESSION,
                    subject=subject,
                    scope=dict(permission.scope),
                    reason=f"declared by {name}",
                )
        else:
            self.plugins.broker.revoke(Capability.PLUGIN_EXECUTE, subject=subject)
            for permission in manifest.permissions:
                self.plugins.broker.revoke(permission.capability, subject=subject)
        self.plugins.set_enabled(name, enabled)

    def refresh_audit(self) -> None:
        self.audit_list.clear()
        if not self.repository:
            return
        for row in self.repository.recent_tool_audit(200):
            self.audit_list.addItem(
                f"{row['created_at']} • {row['tool_name']} • {row['decision']}/{row['status']} • {row['error_code']}"
            )

    def _export(self) -> None:
        if not self.repository:
            return
        destination, _filter = QFileDialog.getSaveFileName(
            self, "Export private companion data", str(Path.home() / "vla-pet-export.json"), "JSON (*.json)"
        )
        if destination:
            self.repository.export(Path(destination))

    def show_and_refresh(self) -> None:
        self.refresh_all()
        self.show()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _csv(value: str) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.hide()
        event.ignore()

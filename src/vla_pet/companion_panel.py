from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vla_pet.chat_dialog import PetChatDialog
from vla_pet.control_center import CompanionControlCenter
from vla_pet.growth import stage_definition, stage_progress
from vla_pet.settings import CompanionSettings
from vla_pet.state import PetRuntimeState
from vla_pet.theme import apply_companion_theme


class CompanionPanel(QDialog):
    """Friendly one-window home for chat, play, and advanced companion controls."""

    habitat_action_requested = Signal(str)
    settings_changed = Signal(object)

    PAGE_NAMES = ("home", "chat", "status", "play", "settings")

    def __init__(
        self,
        settings: CompanionSettings,
        state: PetRuntimeState,
        chat: PetChatDialog,
        advanced: CompanionControlCenter,
    ) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.settings = settings
        self.state = state
        self.chat = chat
        self.advanced = advanced
        self.setObjectName("CompanionPanel")
        self.setWindowTitle("Momo's cozy corner")
        self.resize(780, 560)

        shell = QHBoxLayout(self)
        shell.setContentsMargins(14, 14, 14, 14)
        shell.setSpacing(14)
        nav = QFrame()
        nav.setObjectName("Card")
        nav.setFixedWidth(154)
        nav_layout = QVBoxLayout(nav)
        title = QLabel("Momo")
        title.setObjectName("HeroTitle")
        subtitle = QLabel("your tiny desktop pal")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        nav_layout.addWidget(title)
        nav_layout.addWidget(subtitle)
        nav_layout.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for index, (name, label) in enumerate(
            (
                ("home", "⌂  Home"),
                ("chat", "♡  Chat"),
                ("status", "✦  Status"),
                ("play", "★  Play"),
                ("settings", "⚙  Settings"),
            )
        ):
            button = QPushButton(label)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, page=index: self.set_page(page))
            self.nav_group.addButton(button, index)
            self.nav_buttons[name] = button
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        privacy = QLabel("● Local-first\nNo screen capture for habitat play")
        privacy.setObjectName("Muted")
        privacy.setWordWrap(True)
        nav_layout.addWidget(privacy)
        shell.addWidget(nav)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._home_page())
        self.pages.addWidget(self._chat_page())
        self.pages.addWidget(self._status_page())
        self.pages.addWidget(self._play_page())
        self.pages.addWidget(self._settings_page())
        shell.addWidget(self.pages, 1)
        apply_companion_theme(self)
        self.set_page(self.PAGE_NAMES.index(settings.last_panel_page))

    def _page_header(self, title: str, detail: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title)
        heading.setObjectName("HeroTitle")
        text = QLabel(detail)
        text.setObjectName("Muted")
        text.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(text)
        return page, layout

    def _home_page(self) -> QWidget:
        page, layout = self._page_header("Welcome home", "Momo's day at a glance.")
        self.coachmark = QFrame()
        self.coachmark.setObjectName("Card")
        coach_layout = QHBoxLayout(self.coachmark)
        coach = QLabel("New: open the paw nook to give Momo a snack, toss the ball, or make a nap spot.")
        coach.setWordWrap(True)
        dismiss = QPushButton("Got it")
        dismiss.clicked.connect(self._dismiss_coachmark)
        coach_layout.addWidget(coach, 1)
        coach_layout.addWidget(dismiss)
        self.coachmark.setVisible(not self.settings.habitat_coachmark_seen)
        layout.addWidget(self.coachmark)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        top = QHBoxLayout()
        self.mood_label = QLabel()
        self.mood_label.setObjectName("SectionTitle")
        self.activity_label = QLabel()
        self.activity_label.setObjectName("StatusPill")
        top.addWidget(self.mood_label)
        top.addStretch(1)
        top.addWidget(self.activity_label)
        card_layout.addLayout(top)
        self.energy = QProgressBar()
        self.energy.setFormat("Energy  %p%")
        self.affection = QProgressBar()
        self.affection.setFormat("Affection  %p%")
        card_layout.addWidget(self.energy)
        card_layout.addWidget(self.affection)
        self.level_label = QLabel()
        self.level_label.setObjectName("Muted")
        card_layout.addWidget(self.level_label)
        layout.addWidget(card)

        actions = QHBoxLayout()
        for label, action in (("Chat with Momo", "chat"), ("Give snack", "snack"), ("Toss ball", "ball"), ("Open nook", "home")):
            button = QPushButton(label)
            if action == "chat":
                button.setObjectName("Primary")
            button.clicked.connect(lambda _checked=False, value=action: self._quick_action(value))
            actions.addWidget(button)
        layout.addLayout(actions)
        privacy = QLabel()
        privacy.setObjectName("Muted")
        self.privacy_label = privacy
        layout.addWidget(privacy)
        layout.addStretch(1)
        return page

    def _chat_page(self) -> QWidget:
        page, layout = self._page_header("Chit-chat", "One local language model handles Momo's words and direct habitat requests.")
        self.chat.setParent(page)
        self.chat.setWindowFlags(Qt.WindowType.Widget)
        self.chat.setSizeGripEnabled(False)
        layout.addWidget(self.chat, 1)
        suggestions = QHBoxLayout()
        for text in ("How are you?", "Tell me a tiny joke", "Go play with the ball"):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, value=text: self._suggest(value))
            suggestions.addWidget(button)
        layout.addLayout(suggestions)
        return page

    def _play_page(self) -> QWidget:
        page, layout = self._page_header("Play together", "Objects stay deterministic, tactile, and safe inside Momo's own nook.")
        self.progress_label = QLabel()
        self.progress_label.setObjectName("SectionTitle")
        self.inventory_label = QLabel()
        self.inventory_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.inventory_label)
        row = QHBoxLayout()
        for label, action in (("☆ Spawn snack", "snack"), ("● Toss ball", "ball"), ("▱ Rest on cushion", "sleep"), ("□ Peek in box", "box")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=action: self.habitat_action_requested.emit(value))
            row.addWidget(button)
        layout.addLayout(row)
        positive = QLabel("Nothing decays while you're away. Rewards are positive-only and granted after an interaction completes.")
        positive.setObjectName("Muted")
        positive.setWordWrap(True)
        layout.addWidget(positive)
        daily = QPushButton("Claim today's cozy check-in")
        daily.clicked.connect(self._daily)
        game = QPushButton("Play Catch the Star")
        game.clicked.connect(self.advanced._open_game)
        layout.addWidget(daily)
        layout.addWidget(game)
        layout.addStretch(1)
        return page

    def _status_page(self) -> QWidget:
        page, layout = self._page_header(
            "Momo's status",
            "Every completed activity grows Momo. Time away never removes growth or stats.",
        )
        stage_card = QFrame()
        stage_card.setObjectName("Card")
        stage_layout = QVBoxLayout(stage_card)
        self.stage_label = QLabel()
        self.stage_label.setObjectName("SectionTitle")
        self.stage_progress = QProgressBar()
        self.next_stage_label = QLabel()
        self.next_stage_label.setObjectName("Muted")
        self.next_stage_label.setWordWrap(True)
        stage_layout.addWidget(self.stage_label)
        stage_layout.addWidget(self.stage_progress)
        stage_layout.addWidget(self.next_stage_label)
        layout.addWidget(stage_card)

        stat_card = QFrame()
        stat_card.setObjectName("Card")
        stat_layout = QVBoxLayout(stat_card)
        self.stat_bars: dict[str, QProgressBar] = {}
        for name in ("health", "stamina", "intelligence"):
            bar = QProgressBar()
            bar.setRange(1, 99)
            self.stat_bars[name] = bar
            stat_layout.addWidget(bar)
        layout.addWidget(stat_card)
        guide = QLabel(
            "Health grows from rest, snacks, and check-ins. Stamina grows through ball play "
            "and games. Intelligence grows through chat, focus, and exploring the box."
        )
        guide.setObjectName("Muted")
        guide.setWordWrap(True)
        layout.addWidget(guide)
        layout.addStretch(1)
        return page

    def _settings_page(self) -> QWidget:
        page, layout = self._page_header("Make it yours", "The everyday choices are here; technical controls stay tucked under Advanced.")
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        self.habitat_enabled = QCheckBox("Show Momo's desktop nook")
        self.habitat_enabled.setChecked(self.settings.habitat_enabled)
        self.reduced_motion = QCheckBox("Use reduced motion")
        self.reduced_motion.setChecked(self.settings.reduced_motion)
        self.sound_enabled = QCheckBox("Play soft interaction sounds")
        self.sound_enabled.setChecked(self.settings.sound_enabled)
        self.sound_volume = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume.setRange(0, 100)
        self.sound_volume.setValue(round(self.settings.sound_volume * 100))
        save = QPushButton("Save appearance and habitat")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_simple_settings)
        for widget in (self.habitat_enabled, self.reduced_motion, self.sound_enabled, QLabel("Sound volume"), self.sound_volume, save):
            card_layout.addWidget(widget)
        layout.addWidget(card)
        advanced_group = QGroupBox("Advanced: AI, memory, voice, privacy, updates, plugins, data")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout(advanced_group)
        self.advanced.setParent(advanced_group)
        self.advanced.setWindowFlags(Qt.WindowType.Widget)
        advanced_layout.addWidget(self.advanced)
        self.advanced.setVisible(False)
        advanced_group.toggled.connect(self._toggle_advanced)
        layout.addWidget(advanced_group, 1)
        return page

    def set_page(self, page: int | str) -> None:
        index = self.PAGE_NAMES.index(page) if isinstance(page, str) else int(page)
        index = min(len(self.PAGE_NAMES) - 1, max(0, index))
        self.pages.setCurrentIndex(index)
        self.nav_buttons[self.PAGE_NAMES[index]].setChecked(True)
        self.settings.last_panel_page = self.PAGE_NAMES[index]
        self.refresh()

    def refresh(self) -> None:
        self.mood_label.setText(f"Momo feels {self.state.emotion.tag} ♡")
        self.activity_label.setText(self.state.active_intention.replace("_", " ").title())
        self.energy.setValue(round(self.state.needs.energy * 100))
        affection = min(100, self.state.progression.affection_points)
        self.affection.setValue(affection)
        progress = self.state.progression
        stage = stage_definition(self.state.growth.stage)
        self.level_label.setText(
            f"{stage.display_name} Momo  •  Level {progress.level}  •  "
            f"{progress.xp} XP  •  {self.state.interaction_count} hellos"
        )
        self.progress_label.setText(f"Level {progress.level} companion • {len(progress.achievements)} achievements")
        inventory = "   ".join(f"{name.title()} × {count}" for name, count in sorted(progress.inventory.items()))
        self.inventory_label.setText(inventory or "The basket is empty for now.")
        self.privacy_label.setText(
            "Privacy mode is on — optional sensors are quiet."
            if self.settings.privacy_mode
            else "Habitat play uses internal object state only. Desktop capture still requires your explicit request."
        )
        growth = stage_progress(progress.xp, self.state.growth.stage)
        self.stage_label.setText(f"{stage.display_name} Momo  •  Level {progress.level}")
        self.stage_progress.setRange(0, growth.required)
        self.stage_progress.setValue(growth.earned)
        if growth.next_stage is None:
            self.stage_progress.setFormat("Teen form reached  •  %p%")
            self.next_stage_label.setText(
                "Teen is the current final form. Stats and friendship can still keep growing."
            )
        else:
            next_name = stage_definition(growth.next_stage).display_name
            remaining = growth.required - growth.earned
            self.stage_progress.setFormat(f"Toward {next_name}  •  %v / %m growth XP")
            self.next_stage_label.setText(
                f"{remaining} more XP until {next_name} Momo. Growth comes only from positive activities."
            )
        stat_labels = {
            "health": "HP",
            "stamina": "STA",
            "intelligence": "INT",
        }
        for name, bar in self.stat_bars.items():
            value = int(getattr(self.state.stats, name))
            experience = int(getattr(self.state.stats, f"{name}_xp"))
            bar.setValue(value)
            bar.setFormat(f"{stat_labels[name]}  {value} / 99  •  training {experience}")

    def _quick_action(self, action: str) -> None:
        if action == "chat":
            self.set_page("chat")
            self.chat.input.setFocus()
        else:
            self.habitat_action_requested.emit(action)

    def _suggest(self, text: str) -> None:
        if self.chat.input.isEnabled():
            self.chat.input.setText(text)
            self.chat._submit()

    def _daily(self) -> None:
        self.advanced._daily()
        self.refresh()

    def _dismiss_coachmark(self) -> None:
        self.settings.habitat_coachmark_seen = True
        self.settings.save(self.advanced.repository)
        self.coachmark.hide()

    def _save_simple_settings(self) -> None:
        self.settings.habitat_enabled = self.habitat_enabled.isChecked()
        self.settings.reduced_motion = self.reduced_motion.isChecked()
        self.settings.sound_enabled = self.sound_enabled.isChecked()
        self.settings.sound_volume = self.sound_volume.value() / 100.0
        self.settings.save(self.advanced.repository)
        self.settings_changed.emit(self.settings)

    def _toggle_advanced(self, enabled: bool) -> None:
        self.advanced.setVisible(enabled)
        self.resize(840, 760 if enabled else 560)

    def show_page(self, page: str = "home") -> None:
        self.set_page(page)
        self.show()
        self.raise_()
        self.activateWindow()
        if page == "chat":
            self.chat.input.setFocus()

    def show_and_refresh(self) -> None:
        self.advanced.refresh_all()
        self.show_page("home")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.settings.save(self.advanced.repository)
        self.hide()
        event.ignore()

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout


@dataclass(slots=True)
class ReactionGame:
    rounds: int = 10
    seed: int = 17
    current_round: int = 0
    score: int = 0
    target: int = 0
    complete: bool = False

    def start(self) -> int:
        self.current_round = 0
        self.score = 0
        self.complete = False
        self.target = self._next_target()
        return self.target

    def choose(self, index: int) -> bool:
        if self.complete:
            return False
        correct = int(index) == self.target
        if correct:
            self.score += 1
        self.current_round += 1
        if self.current_round >= max(1, self.rounds):
            self.complete = True
        else:
            self.target = self._next_target()
        return correct

    def _next_target(self) -> int:
        self.seed = (1103515245 * self.seed + 12345) & 0x7FFFFFFF
        return self.seed % 9


class ReactionGameDialog(QDialog):
    game_finished = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Catch Momo's star")
        self.game = ReactionGame()
        self.status = QLabel()
        grid = QGridLayout()
        self.buttons: list[QPushButton] = []
        for index in range(9):
            button = QPushButton("·")
            button.setFixedSize(72, 72)
            button.clicked.connect(lambda _checked=False, value=index: self._choose(value))
            self.buttons.append(button)
            grid.addWidget(button, index // 3, index % 3)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Catch the star. Ten rounds, no penalties."))
        layout.addWidget(self.status)
        layout.addLayout(grid)
        self.restart()

    def restart(self) -> None:
        self.game.start()
        self._render()

    def _choose(self, index: int) -> None:
        self.game.choose(index)
        if self.game.complete:
            self.status.setText(f"Finished: {self.game.score}/{self.game.rounds}")
            for button in self.buttons:
                button.setEnabled(False)
            self.game_finished.emit(self.game.score)
            return
        self._render()

    def _render(self) -> None:
        self.status.setText(
            f"Round {self.game.current_round + 1}/{self.game.rounds} • score {self.game.score}"
        )
        for index, button in enumerate(self.buttons):
            button.setEnabled(True)
            button.setText("★" if index == self.game.target else "·")

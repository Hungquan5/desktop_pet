from __future__ import annotations

import shutil
import subprocess

import numpy as np
from PySide6.QtCore import QObject, QProcess, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QScreen

from vla_pet.notifications import decode_dbus_string, notification_from_strings
from vla_pet.screen_capture import PortalScreenshot


class NotificationMonitor(QObject):
    """Qt adapter for the opt-in desktop notification stream."""

    notification = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._line_buffer = ""
        self._strings: list[str] = []
        self._delivered = False

    @property
    def active(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def start(self) -> bool:
        if self.active:
            return True
        process = QProcess(self)
        process.setProgram("dbus-monitor")
        process.setArguments(
            [
                "--session",
                "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
            ]
        )
        process.readyReadStandardOutput.connect(self._read_output)
        process.errorOccurred.connect(lambda _error: self.failed.emit(process.errorString()))
        process.start()
        self._process = process
        return True

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        process.terminate()
        if not process.waitForFinished(500):
            process.kill()
            process.waitForFinished(250)
        process.deleteLater()

    def _read_output(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self._line_buffer += chunk
        lines = self._line_buffer.split("\n")
        self._line_buffer = lines.pop()
        for line in lines:
            if line.startswith("method call"):
                self._strings = []
                self._delivered = False
                continue
            value = decode_dbus_string(line)
            if value is None or self._delivered:
                continue
            self._strings.append(value)
            notification = notification_from_strings(self._strings)
            if notification is not None:
                self._delivered = True
                self.notification.emit(notification.context)


class ScreenCaptureAdapter(QObject):
    """One-shot screen acquisition with Wayland portal mediation."""

    finished = Signal(object, str)

    def __init__(self, screen: QScreen, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.screen = screen
        self._portal = PortalScreenshot(self)
        self._portal.finished.connect(self._portal_finished)

    @property
    def active(self) -> bool:
        return self._portal.active

    def request(self) -> bool:
        if self.active:
            return False
        platform = QGuiApplication.platformName().lower()
        if "wayland" in platform:
            return self._portal.request()
        pixmap = self.screen.grabWindow(0)
        if pixmap.isNull():
            return self._portal.request()
        self.finished.emit(self.image_to_rgb(pixmap.toImage()), "")
        return True

    def _portal_finished(self, image: QImage | None, error: str) -> None:
        if error or image is None:
            self.finished.emit(None, error or "The authorized screenshot could not be read")
            return
        self.finished.emit(self.image_to_rgb(image), "")

    @staticmethod
    def image_to_rgb(image: QImage) -> np.ndarray:
        image = image.scaled(
            QSize(768, 768),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        converted = image.convertToFormat(QImage.Format.Format_RGB888)
        width, height = converted.width(), converted.height()
        bytes_per_line = converted.bytesPerLine()
        raw = np.frombuffer(converted.bits(), dtype=np.uint8, count=height * bytes_per_line)
        return raw.reshape(height, bytes_per_line)[:, : width * 3].reshape(height, width, 3).copy()


def open_allowed_application(name: str) -> bool:
    """Open one known application without a shell or user-controlled arguments."""
    aliases = {
        "browser": ("firefox", "google-chrome", "chromium"),
        "files": ("nautilus", "dolphin", "thunar"),
        "terminal": ("gnome-terminal", "konsole", "xfce4-terminal"),
        "editor": ("code", "codium", "gedit"),
        "calculator": ("gnome-calculator", "kcalc"),
    }
    key = name.strip().casefold()
    candidates = aliases.get(key, ())
    executable = next((shutil.which(candidate) for candidate in candidates if shutil.which(candidate)), None)
    if executable is None:
        return False
    try:
        subprocess.Popen(
            [executable],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True

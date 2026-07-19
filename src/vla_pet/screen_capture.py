from __future__ import annotations

import os
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtDBus import (
    QDBusAbstractInterface,
    QDBusArgument,
    QDBusConnection,
    QDBusInterface,
    QDBusMessage,
    QDBusReply,
    QDBusVariant,
)
from PySide6.QtGui import QImage


class _PortalRequest(QDBusAbstractInterface):
    # QDBusAbstractInterface can deliver the complete signal message, including
    # nested a{sv} data that PySide does not reliably convert to a Python dict.
    Response = Signal(QDBusMessage)

    def __init__(self, path: str, connection: QDBusConnection, parent: QObject) -> None:
        super().__init__(
            "org.freedesktop.portal.Desktop",
            path,
            "org.freedesktop.portal.Request",
            connection,
            parent,
        )


class PortalScreenshot(QObject):
    """Request a user-authorized screenshot through XDG Desktop Portal."""

    finished = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = QDBusConnection.sessionBus()
        self._active = False
        self._request: _PortalRequest | None = None
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(lambda: self._finish(None, "Screenshot permission timed out"))

    @property
    def active(self) -> bool:
        return self._active

    def request(self) -> bool:
        if self._active:
            return False
        if not self._bus.isConnected():
            self.finished.emit(None, "The desktop portal is unavailable")
            return False

        token = f"vla_pet_{uuid.uuid4().hex}"
        sender = self._bus.baseService().lstrip(":").replace(".", "_")
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        self._request = _PortalRequest(request_path, self._bus, self)
        self._request.Response.connect(self._on_response)

        portal = QDBusInterface(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            self._bus,
            self,
        )
        if not portal.isValid():
            self.finished.emit(None, "The Screenshot portal is unavailable")
            return False

        self._active = True
        self._timeout.start(60_000)
        message = portal.call(
            "Screenshot",
            "",
            {"handle_token": token, "interactive": False},
        )
        reply = QDBusReply(message)
        if not reply.isValid():
            self._finish(None, reply.error().message() or "Screenshot portal call failed")
            return False
        return True

    def _on_response(self, message: QDBusMessage) -> None:
        arguments = message.arguments()
        if not arguments:
            self._finish(None, "Screenshot portal returned an empty response")
            return
        response = int(arguments[0])
        if response != 0:
            self._finish(None, "Screenshot permission was cancelled")
            return
        uri = self._extract_uri(arguments[1] if len(arguments) > 1 else None)
        local_path = QUrl(uri).toLocalFile() if uri else ""
        image = QImage(local_path)
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:
                pass
        if image.isNull():
            self._finish(None, "The authorized screenshot could not be read")
            return
        self._finish(image, "")

    @staticmethod
    def _extract_uri(payload: object) -> str:
        if isinstance(payload, dict):
            value = payload.get("uri", "")
            return str(value.variant() if isinstance(value, QDBusVariant) else value)
        if not isinstance(payload, QDBusArgument):
            return ""
        payload.beginArray()
        while not payload.atEnd():
            payload.beginMap()
            while not payload.atEnd():
                key = payload.asVariant()
                value = payload.asVariant()
                if key == "uri":
                    return str(value.variant() if isinstance(value, QDBusVariant) else value)
            payload.endMap()
        payload.endArray()
        return ""

    def _finish(self, image: QImage | None, error: str) -> None:
        self._timeout.stop()
        if self._request:
            self._request.deleteLater()
            self._request = None
        self._active = False
        self.finished.emit(image, error)

"""Request one screenshot through the desktop portal and print only its dimensions."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from vla_pet.screen_capture import PortalScreenshot


app = QApplication([])
capture = PortalScreenshot()


def complete(image, error: str) -> None:
    if error:
        print(f"Portal screenshot failed: {error}")
        app.exit(1)
    else:
        print(f"Portal screenshot authorized: {image.width()}x{image.height()}")
        app.quit()


capture.finished.connect(complete)
QTimer.singleShot(0, capture.request)
raise SystemExit(app.exec())

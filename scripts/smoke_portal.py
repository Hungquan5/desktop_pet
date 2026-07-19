"""Request one screenshot through the desktop portal and print only its dimensions."""

import argparse
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from vla_pet.screen_capture import PortalScreenshot

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, help="explicitly save the authorized image")
args = parser.parse_args()

app = QApplication([])
capture = PortalScreenshot()


def complete(image, error: str) -> None:
    if error:
        print(f"Portal screenshot failed: {error}")
        app.exit(1)
    else:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(args.output)):
                print(f"Could not save authorized screenshot to {args.output}")
                app.exit(1)
                return
        print(f"Portal screenshot authorized: {image.width()}x{image.height()}")
        app.quit()


capture.finished.connect(complete)
QTimer.singleShot(0, capture.request)
raise SystemExit(app.exec())

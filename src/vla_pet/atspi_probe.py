from __future__ import annotations

import json


def main() -> int:
    try:
        import pyatspi

        desktop = pyatspi.Registry.getDesktop(0)
        for application in desktop:
            for window in application:
                try:
                    active = window.getState().contains(pyatspi.STATE_ACTIVE)
                except Exception:
                    continue
                if active:
                    print(
                        json.dumps(
                            {
                                "application": str(getattr(application, "name", ""))[:200],
                                "title": str(getattr(window, "name", ""))[:500],
                            }
                        )
                    )
                    return 0
    except Exception:
        pass
    print('{"application":"","title":""}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

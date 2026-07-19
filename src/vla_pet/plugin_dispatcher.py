from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from vla_pet.permissions import PermissionBroker
from vla_pet.persistence import StateRepository
from vla_pet.plugins import PluginHost, PluginManifest


class AsyncPluginDispatcher(QObject):
    """Deliver bounded plugin hooks outside the renderer/UI thread."""

    finished = Signal(str, object)

    def __init__(
        self,
        database: Path,
        broker: PermissionBroker,
        manifests: tuple[PluginManifest, ...],
    ) -> None:
        super().__init__()
        self.database = database
        self.broker = broker
        self.manifests = manifests
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vla-pet-plugin")
        self._queued = 0
        self._closed = False
        self._repository: StateRepository | None = None
        self._host: PluginHost | None = None

    @property
    def queued(self) -> int:
        return self._queued

    def dispatch(self, hook: str, payload: dict[str, Any] | None = None) -> bool:
        if self._closed or self._queued >= 32:
            return False
        self._queued += 1
        future = self._pool.submit(self._dispatch, hook, payload or {})
        future.add_done_callback(lambda completed: self._complete(hook, completed))
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        future = self._pool.submit(self._close_worker)
        try:
            future.result(timeout=2.0)
        except Exception:
            pass
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _dispatch(self, hook: str, payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        host = self._ensure_host()
        results: list[dict[str, Any]] = []
        for manifest in self.manifests:
            if hook not in manifest.hooks or not host.enabled(manifest.name):
                continue
            try:
                results.append(host.invoke(manifest.name, {"hook": hook, **payload}))
            except Exception as exc:
                results.append(
                    {"ok": False, "plugin": manifest.name, "error": type(exc).__name__}
                )
        return tuple(results)

    def _ensure_host(self) -> PluginHost:
        if self._host is None:
            self._repository = StateRepository(self.database)
            self._host = PluginHost(self.broker, self._repository)
            for manifest in self.manifests:
                self._host.add(manifest)
        return self._host

    def _complete(self, hook: str, future: Future[tuple[dict[str, Any], ...]]) -> None:
        self._queued = max(0, self._queued - 1)
        if self._closed or future.cancelled():
            return
        try:
            self.finished.emit(hook, future.result())
        except Exception as exc:  # pragma: no cover - last-resort thread boundary
            self.finished.emit(hook, ({"ok": False, "error": type(exc).__name__},))

    def _close_worker(self) -> None:
        if self._repository is not None:
            self._repository.close()
        self._repository = None
        self._host = None

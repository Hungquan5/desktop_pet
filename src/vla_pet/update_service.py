from __future__ import annotations

import base64
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from vla_pet.permissions import PermissionBroker
from vla_pet.signing import TrustStore
from vla_pet.updater import SignedUpdateClient, UpdateArtifact, version_tuple


class AsyncUpdateChecker(QObject):
    """Check an opt-in signed release channel without blocking the overlay."""

    finished = Signal(object, str)

    def __init__(self, broker: PermissionBroker, current_version: str) -> None:
        super().__init__()
        self.broker = broker
        self.current_version = current_version
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vla-pet-update")
        self._pending = False
        self._closed = False

    @property
    def pending(self) -> bool:
        return self._pending

    def check(
        self,
        manifest_url: str,
        public_key_base64: str,
        *,
        key_id: str,
        channel: str,
    ) -> bool:
        if self._closed or self._pending:
            return False
        self._pending = True
        future = self._pool.submit(
            self._check,
            manifest_url,
            public_key_base64,
            key_id,
            channel,
        )
        future.add_done_callback(self._complete)
        return True

    def close(self) -> None:
        self._closed = True
        self._pending = False
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _check(
        self,
        manifest_url: str,
        public_key_base64: str,
        key_id: str,
        channel: str,
    ) -> UpdateArtifact | None:
        public_key = base64.b64decode(public_key_base64, validate=True)
        client = SignedUpdateClient(self.broker, TrustStore({key_id: public_key}))
        artifact = client.check(manifest_url, channel=channel)
        return artifact if version_tuple(artifact.version) > version_tuple(self.current_version) else None

    def _complete(self, future: Future[UpdateArtifact | None]) -> None:
        self._pending = False
        if self._closed or future.cancelled():
            return
        try:
            self.finished.emit(future.result(), "")
        except Exception as exc:
            self.finished.emit(None, f"{type(exc).__name__}: {exc}"[:300])

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from vla_pet.builtin_tools import CoreToolServices, register_core_tools
from vla_pet.permissions import PermissionBroker
from vla_pet.persistence import StateRepository
from vla_pet.platform_adapters import open_allowed_application
from vla_pet.tool_runtime import ToolHost, ToolInvocation, ToolRegistry, ToolResult


class AsyncToolExecutor(QObject):
    """Run brokered core tools away from Qt's input and paint thread."""

    finished = Signal(object, object)

    def __init__(self, database: Path, broker: PermissionBroker) -> None:
        super().__init__()
        self.database = database
        self.broker = broker
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vla-pet-tool")
        self._pending: set[str] = set()
        self._closed = False

    @property
    def pending(self) -> tuple[str, ...]:
        return tuple(self._pending)

    def submit(self, invocation: ToolInvocation, *, clipboard_text: str = "") -> bool:
        if self._closed or invocation.invocation_id in self._pending:
            return False
        self._pending.add(invocation.invocation_id)
        future = self._pool.submit(self._invoke, invocation, clipboard_text)
        future.add_done_callback(lambda completed: self._complete(invocation, completed))
        return True

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _invoke(self, invocation: ToolInvocation, clipboard_text: str) -> ToolResult:
        with StateRepository(self.database) as repository:
            registry = ToolRegistry()
            register_core_tools(
                registry,
                CoreToolServices(
                    repository,
                    clipboard_reader=lambda: clipboard_text,
                    application_opener=open_allowed_application,
                ),
            )
            return ToolHost(registry, self.broker, repository=repository).invoke(invocation)

    def _complete(self, invocation: ToolInvocation, future: Future[ToolResult]) -> None:
        self._pending.discard(invocation.invocation_id)
        if self._closed or future.cancelled():
            return
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - last-resort thread boundary
            result = ToolResult(
                invocation.invocation_id,
                invocation.name,
                False,
                "The tool could not finish.",
                error_code=f"tool.executor.{type(exc).__name__.lower()}",
            )
        self.finished.emit(invocation, result)

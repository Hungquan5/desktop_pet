from __future__ import annotations

from typing import Any

from vla_pet.events import AIEvent, EventBus
from vla_pet.worker import AIWorkerClient, InlineMockWorkerClient, WorkerConfig


class AIOrchestrator:
    """UI-facing AI boundary with single-flight routing and lifecycle recovery."""

    def __init__(self, config: WorkerConfig, bus: EventBus) -> None:
        self.config = config
        self.bus = bus
        self._client = (
            InlineMockWorkerClient(config) if config.mock_policy else AIWorkerClient(config)
        )

    def start(self) -> None:
        self._client.start()

    def submit(self, kind: str, payload: Any) -> int | None:
        if kind in self._client.pending_kinds:
            return None
        request_id = self._client.submit(kind, payload)
        self.bus.publish(
            AIEvent(name="request_submitted", data={"kind": kind, "request_id": request_id})
        )
        return request_id

    def poll(self):
        responses = self._client.poll()
        for response in responses:
            self.bus.publish(
                AIEvent(
                    name="response_received",
                    data={
                        "kind": response.kind,
                        "request_id": response.request_id,
                        "ok": response.ok,
                        "latency_s": response.latency_s,
                    },
                )
            )
        return responses

    def timed_out(self) -> bool:
        return self._client.timed_out()

    def cancel(self, kind: str) -> int:
        cancelled = self._client.cancel(kind)
        if cancelled:
            self.bus.publish(
                AIEvent(name="request_cancelled", data={"kind": kind, "count": cancelled})
            )
        return cancelled

    def restart(self) -> None:
        self._client.stop()
        self._client = (
            InlineMockWorkerClient(self.config)
            if self.config.mock_policy
            else AIWorkerClient(self.config)
        )
        self._client.start()
        self.bus.publish(AIEvent(name="worker_restarted"))

    def stop(self) -> None:
        self._client.stop()

    @property
    def pending_kinds(self) -> tuple[str, ...]:
        return self._client.pending_kinds

    @property
    def process_id(self) -> int | None:
        return self._client.process_id

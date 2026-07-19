"""Live smoke test for the one-worker SmolVLM + SmolLM cooperation path."""

from __future__ import annotations

import time
from dataclasses import replace

import numpy as np

from vla_pet.contracts import ChatRequest, SandboxObservation
from vla_pet.worker import AIWorkerClient, WorkerConfig


def wait_for(client: AIWorkerClient, timeout: float = 180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        responses = client.poll()
        if responses:
            return responses[0]
        time.sleep(0.02)
    raise TimeoutError("Cooperative worker did not respond")


def main() -> None:
    image = np.zeros((3, 256, 256), dtype=np.float32)
    observation = SandboxObservation(
        sequence_id=1,
        images={"observation.image": image},
        state=(0.0, 1.0, 0.0, 0.0, 1.0, -1.0),
        task="Choose a safe desktop-pet action.",
    )
    client = AIWorkerClient(
        WorkerConfig(
            offline=True,
            quantization="int8",
            language_quantization="none",
        )
    )
    client.start()
    first_pid = client.process_id
    client.start()
    assert first_pid is not None and client.process_id == first_pid
    print(f"one worker pid={first_pid}", flush=True)
    try:
        started = time.monotonic()
        client.submit("decide", observation)
        action = wait_for(client)
        print(f"VLM action {time.monotonic() - started:.2f}s: {action.payload.as_dict()}", flush=True)

        started = time.monotonic()
        client.submit("chat", ChatRequest("Can you jump?"))
        chat = wait_for(client)
        print(
            f"SmolLM chat {time.monotonic() - started:.2f}s: "
            f"{chat.payload.reply} intent={chat.payload.requested_action}",
            flush=True,
        )
        assert chat.payload.requested_action is not None

        started = time.monotonic()
        directed = replace(
            observation,
            sequence_id=2,
            requested_action=chat.payload.requested_action,
        )
        client.submit("decide", directed)
        commanded = wait_for(client)
        print(
            f"VLM commanded action {time.monotonic() - started:.2f}s: "
            f"{commanded.payload.as_dict()}",
            flush=True,
        )
        assert client.process_id == first_pid
    finally:
        client.stop()


if __name__ == "__main__":
    main()

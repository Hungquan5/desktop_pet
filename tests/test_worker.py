import time

import numpy as np

from vla_pet.contracts import ChatRequest, ChatResult, NotificationRequest, SandboxObservation
from vla_pet.worker import AIWorkerClient, WorkerConfig


def test_mock_worker_returns_without_blocking_main_process() -> None:
    image = np.zeros((3, 256, 256), dtype=np.float32)
    observation = SandboxObservation(
        sequence_id=7,
        images={
            "observation.image": image,
            "observation.image2": image.copy(),
            "observation.image3": image.copy(),
        },
        state=(0.0, 0.0, 0.0, 0.0, 1.0, -1.0),
        task="Explore safely.",
    )
    client = AIWorkerClient(WorkerConfig(mock_policy=True, timeout_s=5))
    client.start()
    try:
        first_pid = client.process_id
        client.start()
        assert first_pid is not None
        assert client.process_id == first_pid
        request_id = client.submit("decide", observation)
        deadline = time.monotonic() + 5
        responses = []
        while time.monotonic() < deadline and not responses:
            responses = client.poll()
            time.sleep(0.01)
        assert responses
        assert responses[0].request_id == request_id
        assert responses[0].ok
        assert responses[0].metadata["sequence_id"] == 7
    finally:
        client.stop()


def test_mock_worker_supports_chat() -> None:
    client = AIWorkerClient(WorkerConfig(mock_policy=True, timeout_s=5))
    client.start()
    try:
        client.submit("chat", ChatRequest("Hello!"))
        deadline = time.monotonic() + 5
        responses = []
        while not responses and time.monotonic() < deadline:
            responses = client.poll()
            time.sleep(0.01)
        assert responses[0].kind == "chat"
        assert responses[0].ok
        assert isinstance(responses[0].payload, ChatResult)

        client.submit("notify", NotificationRequest("App: Mail. Title: New message"))
        responses = []
        deadline = time.monotonic() + 5
        while not responses and time.monotonic() < deadline:
            responses = client.poll()
            time.sleep(0.01)
        assert responses[0].kind == "notify"
        assert responses[0].ok
        assert "notification" in responses[0].payload.lower()
    finally:
        client.stop()

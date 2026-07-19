from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

from vla_pet.persistence import StateRepository


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vla-pet-memory-") as temporary:
        with StateRepository(Path(temporary) / "pet.db") as repository:
            for index in range(10_000):
                repository.upsert_memory(
                    tier="episodic" if index % 2 else "profile",
                    kind="benchmark",
                    summary=f"Synthetic memory {index} about topic {index % 100}",
                    dedupe_key=f"benchmark-{index}",
                    salience=(index % 10) / 10,
                    tags=(f"topic-{index % 100}", "synthetic"),
                )
            latencies: list[float] = []
            for index in range(100):
                started = time.perf_counter()
                rows = repository.search_memories(f"topic {index % 100}", limit=8)
                latencies.append((time.perf_counter() - started) * 1000.0)
                if not rows:
                    raise SystemExit("Memory benchmark retrieval returned no rows")
    p95 = statistics.quantiles(latencies, n=20)[18]
    print(f"memory_items=10000 p95_ms={p95:.2f} max_ms={max(latencies):.2f}")
    if p95 >= 50.0:
        raise SystemExit(f"Memory p95 {p95:.2f} ms exceeds 50 ms budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

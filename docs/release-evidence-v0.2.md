# v0.2 release evidence

Recorded on 2026-07-19 on Ubuntu GNOME Wayland, Python 3.10.12, PySide6
6.11.1, torch 2.10.0 CPU, and transformers 4.57.6.

## Deterministic gates

- Ruff, Python compilation, and all 55 pytest tests pass with 86% statement
  coverage.
- The test suite includes a 30-minute simulated life-engine soak, blocked-AI UI
  heartbeat, mouse drag/drop and Ctrl-click regression, permission denial,
  event idempotency, redaction, retention, persistence restart, and packaging
  contracts.
- Safe/mock mode uses no model weights, no network, and no child process.
- The five-minute headless idle measurement used 7.10 CPU-seconds over 300.45
  wall-seconds: 2.36% of one core, below the 3% release budget.
- `scripts/verify_project.py` builds the wheel, verifies required contents,
  launches the headless overlay, installs into a temporary prefix, exercises an
  atomic upgrade and rollback, launches the installed command, and uninstalls.

## Cached model gate

`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/smoke_coop.py` passed
with one real worker PID. Observed representative timings:

| Path | Result |
|---|---|
| Cold SmolVLM action | 5.88 s, then 2.07 s warm |
| SmolLM jump confirmation | 1.28 s, structured `JUMP` intent |
| SmolLM joke follow-up | 3.57 s, non-repeating answer |
| SmolLM repetition follow-up | 2.58 s, distinct concise answer |
| SmolVLM evidence + SmolLM wording | 3.22 s, nonempty answer |

The synthetic red/white image was described as red/green by the pretrained tiny
VLM. The end-to-end contract is working, but this is a recorded pretrained-model
accuracy limitation rather than hidden as an orchestration success. Fine-tuning
remains deferred as requested.

## Live Wayland gate

- The GNOME screenshot portal authorized a 1920×1080 one-shot capture.
- Host-context diagnostics report `ok: true`, all XDG locations writable, the
  built-in `momo` pack valid, and both cached model runtimes available.
- A second monitor-0 launch was rejected immediately with exit code 2 while the
  final overlay remained alive.
- The real overlay log recorded multiple mouse pick-up/drop sequences followed
  by slow falls and `land` events without remaining in idle.
- The updated deterministic routine log records walk/walk/idle phases and
  extended sleep pauses instead of uninterrupted walking. In the final run, a
  persisted `sleep` intention recovered autonomously to `play` and executed a
  jump, proving the former permanent-idle failure is fixed.
- Warm autonomous VLM decisions complete around 1.87–1.96 seconds while local
  animation and physics continue.
- Operational logs contain redacted text lengths and metadata, not chat,
  notification bodies, or screen pixels.

## Deployment and publication boundary

The local Linux wheel and user-prefix deployment are accepted. Public binary
publication remains blocked until the original source and redistribution rights
for the six existing PNG character assets are recorded in `ATTRIBUTION.md`.
Model weights are not included in the artifact.

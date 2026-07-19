# v1.0 release evidence

Acceptance date: 2026-07-19  
Reference host: Ubuntu Linux 6.8, GNOME Wayland, Python 3.10, CPU-only inference

## Disposition

`v1.0.0` passes local Linux technical acceptance as an installed desktop
companion. Windows and macOS pass domain and packaging contracts only; no live
hardware claim is made for those platforms. Public binary redistribution remains
blocked by the prototype PNG provenance described in `ATTRIBUTION.md`; the CC0
Orbit sample is the redistributable character alternative.

## Automated release pipeline

`python scripts/verify_project.py` passed the following gates together:

- Ruff and bytecode compilation.
- 94 tests with 76.76% statement coverage, above the 70% release floor.
- sdist/wheel build, wheel-content inspection, and isolated import.
- Linux, Windows, macOS, Flatpak, and AppImage packaging contracts.
- Safe-mode Qt overlay smoke with traceback rejection.
- Private-data backup/restore and schema validation.
- Clean temporary-prefix install, atomic upgrade, rollback, and uninstall.
- 10,000-item FTS memory retrieval at 18.38 ms p95 against a 50 ms budget.

The five-minute safe/mock renderer gate measured 2.90% of one CPU core
(8.71 CPU seconds over 300.50 wall seconds) with one application process,
inside the 3% budget.

## Installed CPU model stack

The Linux installer created an isolated release environment and `pip check`
reported no broken requirements. It installed official CPU builds of Torch
2.13.0 and torchvision 0.28.0; CUDA was unavailable by design. The final cached,
offline smoke used the installed package from `site-packages`, not the source
checkout, and observed one shared AI worker:

- SmolVLM autonomous action: 5.88 s cold path, `WALK_LEFT`.
- SmolLM command reply: 1.01 s, with a confirmed `JUMP` intent.
- SmolLM joke: 4.00 s, clean and non-repeating.
- SmolLM correction: 2.02 s, clean and distinct from history.
- SmolVLM commanded action: 1.71 s, `JUMP`.
- SmolVLM evidence plus SmolLM screen answer: 2.67 s, grounded in the test image.
- Whisper-tiny synthetic 16 kHz WAV transcription: 2.95 s.

## Security, migration, and live desktop

A newly generated Ed25519 key signed the exact wheel manifest. The installed CLI
accepted the documented bare local manifest path, verified its key id, schema,
channel, size, and SHA-256, staged an identical artifact, and wrote the private
key and staged wheel with mode `0600`.

The installed app launched on the GNOME Wayland session as an always-on-top Qt
overlay. It migrated the existing database from schema 1 to schema 2, retained a
mode-`0600` `pet.db.pre-v2-from-v1.bak`, and passed post-migration diagnostics.
The live redacted session log contained successful SmolVLM decisions around
1.76–1.92 seconds, a walk-to-happy transition, successful SmolLM narration, and
no traceback or provider fallback. Drag/drop, Ctrl-click chat, input routing,
action recovery after falling, and click-through behavior also pass the Qt
interaction regression suite.

Screen capture still requires an explicit desktop-portal action, microphone
capture remains push-to-talk, sensors remain opt-in, and safe mode disables AI,
voice capture, sensors, tools, updates, plugins, proactivity, and persistence
writes.

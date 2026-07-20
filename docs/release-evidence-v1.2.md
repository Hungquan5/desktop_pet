# Momo Chan v1.2 release evidence

Acceptance date: 2026-07-20. Reference host: Ubuntu GNOME on Wayland, Python
3.10, CPU-only local inference. Artifact:
`smolvla_pet_sandbox-1.2.1-py3-none-any.whl`.

## Automated and package gates

- `scripts/verify_project.py` passed lint, compilation, 114 tests, 79.55% line
  coverage, the three-second safe-mode overlay, backup/restore, a temporary
  install, atomic upgrade, rollback, and clean uninstall.
- The 10,000-item memory retrieval benchmark measured 18.55 ms p95 and
  19.63 ms maximum latency.
- Linux, Windows, and macOS packaging contracts passed. Windows and macOS are
  contract-only; this release makes no live-hardware claim for them.
- The wheel contains all application modules, both public launchers, schema-v4
  character metadata, and exactly 52 transparent runtime frames: 16 Baby,
  16 Child, 16 Teen, and 4 evolution frames.
- Raw generation atlases, the retired Momo v2 runtime pack, and unresolved
  prototype assets are absent from the wheel. Momo v3 provenance is included.

## Growth, character, and UI evidence

- State schema 1 and 2 snapshots migrate to schema 3 with positive-only stage
  reconciliation. Threshold, multi-stage, persistence, no-regression, stat
  specialization, and durable-item tests pass.
- Every Baby, Child, and Teen form resolves the fixed 17 animation roles before
  rendering. The overlay test proves that evolution changes the active frame
  set and scale, enters the bounded evolution pose, refreshes the panel, and
  persists once.
- The former Teen artwork is retained as Child. Teen now has taller proportions,
  longer styled hair, and a distinct layered coat-dress, cape, waistcoat, boots,
  and gold detailing. Each of the 52 runtime frames has an isolated pose and a
  transparent safety margin, verified by an asset regression test.
- Walking sprites are authored facing screen-right. Direction tests now require
  rightward movement to preserve the source image and leftward movement to flip
  it, correcting the previous opposite-facing walk.
- Offscreen Qt tests cover five-page navigation, full affection, form progress,
  and HP/STA/INT values. The rendered Status page was visually inspected at
  790×720 with no clipping or unreadable controls.
- The feature audit records eleven corrected defects covering affection,
  inventory, streaks, duplicate hooks, play counts, state compatibility,
  character scaling, language status context, and the installed desktop icon.

## Sustained performance

Both measurements sampled the complete safe-mode process tree after a ten-second
warm-up:

| Habitat mode | Duration | CPU use | Limit | Result |
|---|---:|---:|---:|---|
| Expanded | 300.48 s | 3.79% of one core | 5% | Pass |
| Collapsed | 300.49 s | 2.92% of one core | 3% | Pass |

## Local-model cooperation

The cached offline smoke used one worker process. SmolVLM selected an autonomous
walk in 8.35 s. SmolLM produced a requested jump in 2.40 s and three distinct
follow-up replies without phrase repetition. The requested jump completed the
SmolLM→SmolVLM action path in 2.08 s. A visual evidence request was answered
correctly in 3.53 s. No second model worker or duplicate inference path appeared.

## Installed GNOME Wayland acceptance

- The atomic user-prefix installer upgraded the existing installation to
  `momo-chan 1.2.1` with CPU Torch 2.13.0 and Transformers 4.57.6 while retaining
  the previous release as its rollback snapshot.
- Installed diagnostics reported `ok: true`, database schema 3, a valid Momo
  character pack, both bundled plugins, SQLite FTS5, bubblewrap, writable XDG
  directories, and the existing local model cache.
- The installed always-on-top desktop overlay ran a 15-second live GNOME
  Wayland smoke and exited normally. The only console output was an upstream
  PyTorch notice that legacy quantized tensor constructors will be removed in a
  future release; it did not affect inference or rendering.

## Declared limits

Teen is the final v1.2 form; Adult and branching forms remain future schema
work. Model weights are cached or downloaded separately and are not bundled.
HP is a positive training attribute, not a damage or death system. Screenshot,
voice, notification, memory, awareness, tools, and updates remain opt-in and
permission bounded.

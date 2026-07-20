# Momo Chan v1.2 feature audit

Audit date: 2026-07-20. Baseline: v1.1.0 at 104 passing tests and 78.6% line
coverage. The v1.2 implementation adds dedicated growth regression tests and
must pass the same package, recovery, performance, and live-overlay gates.

## Current feature inventory

| Area | Present behavior | Audit result |
|---|---|---|
| Desktop embodiment | Transparent always-on-top overlay, click-through mask, drag/drop gravity, multi-monitor bounds | Covered by overlay routing and render tests; keep GNOME Wayland as the live reference |
| Habitat | Movable/collapsible nook with cushion, snack, ball, box, typed physics, idempotent rewards | Deterministic tests pass; synthetic habitat vision contains no desktop pixels |
| Language and vision | One sequential worker for SmolLM, SmolVLM, and optional Whisper; cancellable chat and bounded intents | Provider, worker, repetition, stale-request, and fallback tests pass |
| Privacy | Sensors off by default, explicit screenshot action, capability broker, redacted logs, privacy mode | Permission-denial and redaction tests pass |
| Memory and tools | Opt-in memory, timers, focus, todos, reminders, notes, clipboard/file/app tools | Persistence, permission-scope, audit, backup, and restore tests pass |
| Voice and awareness | Push-to-talk, local STT option, interruptible TTS, opt-in desktop metadata and notifications | Deterministic provider/fallback tests pass; live hardware remains platform-dependent |
| Extensibility | Character manifests, signed/sandboxed plugins, optional bounded MCP bridge | Manifest, signature, permission, quota, and dispatcher tests pass |
| Deployment | Wheel, Linux atomic install/rollback, safe mode, diagnostics, Windows/macOS packaging contracts | Automated package gates pass; Windows/macOS do not have a live hardware claim |
| Play and progression | Positive-only XP, affection, inventory, daily claim, achievements, mini-game | Functional, but v1.1 had no form evolution or RPG attributes |
| Character animation | Momo v2 supported 16 semantic roles | Several roles reused one pose and no stable growth-form contract existed |

## Bugs found and resolved

| ID | Finding | Resolution |
|---|---|---|
| GROW-001 | Affection used modulo 100, so exactly 100 displayed as 0 | Clamp the bar at 100 |
| GROW-002 | Playing with the reusable ball removed it from inventory | Ball/toy are durable; consumables still decrement |
| GROW-003 | A daily streak increased even after skipped days | Increment only on consecutive dates; otherwise reset to one |
| GROW-004 | Re-clicking an already claimed daily reward emitted another completion hook | Emit the hook only when XP is actually awarded |
| GROW-005 | Petting, chat opening, and dropping all increased `play_count` | Count only explicit play/ball/fetch/mini-game activities |
| GROW-006 | Unknown future nested state fields could reset the entire restored pet | Nested snapshots now ignore unknown fields and preserve recognized data |
| GROW-007 | Character `default_scale` was not applied or bounded | Validate it and combine it with growth-stage scale |
| GROW-008 | SmolLM could not truthfully answer questions about the pet's live form or stats | Supply a short trusted runtime-only companion context |
| GROW-009 | The Linux desktop entry referenced `happy.png`, but the wheel installed `frame_09.png` | Point the installer at the packaged icon and verify it exists after install |
| GROW-010 | The walk atlas faces right, but the overlay declared its native direction as left | Correct the native-facing contract and mirror only for leftward movement |
| GROW-011 | Child and Teen silhouettes were too similar, and equal-grid crops retained neighboring grid artifacts | Promote the former Teen to Child; add a taller fashion-led Teen redesign and safe-area crops |

## v1.2 additions

- Positive-only Baby → Child at 300 XP → Teen at 1000 XP progression.
- Persistent HP, STA, and INT attributes capped at 99, with separate training XP.
- Activity specialization: rest/snacks/check-ins train HP, play/games train STA,
  and chat/focus/exploration train INT.
- Form changes select matching sprite sets, scale gradually, play a bounded
  `evolve` animation, persist immediately, and never regress.
- A five-page companion panel with a dedicated Status page, next-form progress,
  stat bars, training guidance, and live refresh.
- Schema-v4 character packs with a fixed 17-role contract across all forms.

## Deliberate non-goals and final acceptance

- Teen is the current final form; Adult and branching evolutions are future
  schema work.
- HP is a positive RPG attribute, not a damage/death mechanic. Time away never
  harms Momo.
- Existing schema-v1–v3 custom characters remain valid but use one visual form.
- Generated source atlases are excluded from distributable artifacts; cropped
  transparent frames and provenance are shipped.
- The umbrella verifier, wheel inspection, five-minute expanded and collapsed
  CPU gates, installed upgrade/rollback, cached one-worker model smoke, and live
  GNOME Wayland check passed. Exact measurements are recorded in
  `release-evidence-v1.2.md`.

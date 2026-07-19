# SmolVLM2 + SmolLM2 Desktop Pet

A transparent, always-on-top desktop pet that walks across the real screen,
receives discrete actions and visual evidence from SmolVLM2-256M, while
SmolLM2-360M handles conversation and expressive narration. Both models run
inside one worker process and share one sequential request queue.

The overlay only receives mouse input over the visible pet; clicks everywhere
else pass through to the normal desktop. SmolVLM2 can only choose from the app's
bounded walk, jump, throw, happy, sad, and idle actions. It never moves or clicks
the real pointer.

## Quick start

Python 3.10 or newer is required. Start with the lightweight deterministic mode:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
vla-pet --mock-policy
```

Install and run the real local models:

```bash
python -m pip install -e ".[models,dev]"
vla-pet --device cpu --debug
```

The first real run downloads `HuggingFaceTB/SmolVLM2-256M-Video-Instruct` and
`HuggingFaceTB/SmolLM2-360M-Instruct`. Later runs use the local cache; pass
`--offline` to prohibit downloads.

On CPU, `--quantization auto` dynamically quantizes SmolVLM's linear layers to
INT8. Image splitting is disabled for the synthetic 256px pet scene, reducing
preprocessing from 17 vision tiles to one. The local six-thread INT8 action
benchmark takes about 2 seconds. Use `--quantization none` to force the
original FP32 model. A per-monitor lock prevents accidentally running two model
copies on the same screen.

SmolLM defaults to FP32 because dynamic INT8 caused severe generation-quality
loss on this small language checkpoint. `--language-quantization int8` remains
available when memory matters more than answer quality.

The default command launches the transparent overlay on monitor `0`. Stop it
with `Ctrl+C` in the terminal. To run the earlier room-style application instead:

```bash
vla-pet --sandbox-window --offline --debug
```

Mouse controls:

- Left-click the pet to make it react.
- Left-drag the pet in any direction to pick it up. Release it anywhere and it
  falls gently back to the bottom of the monitor.
- Ctrl+left-click opens a persistent SmolLM chat window. Conversation history
  stays in memory while the app is running and message text is not written to
  the session log. Direct commands such as “jump,” “walk left,” “be happy,” or
  “stop” are confirmed by SmolLM and passed to SmolVLM for a visually grounded
  action decision.
- Right-click the pet, enter a question, and SmolVLM will capture that monitor
  once and answer from the screenshot. Screen pixels are processed locally and
  are not written to the session log.

To let the pet react to desktop notifications as they arrive, opt in explicitly:

```bash
vla-pet --offline --watch-notifications
```

Notification titles and bodies are read from the current user's session bus,
passed locally to SmolVLM as context, and not included verbatim in logs. Support
depends on the desktop notification service allowing session-bus monitoring.

Useful command-line options:

```text
--mock-policy             deterministic actions and template narration
--policy vlm              direct SmolVLM2 discrete actions (default)
--language-model-id ID    SmolLM checkpoint for chat and narration
--language-quantization   none (default) or int8
--quantization auto       dynamic INT8 on CPU (default); use none for FP32
--policy vla              legacy SmolVLA experiment
--offline                 use cached model files only
--decision-timeout 180    restart a stuck background worker
--screen-index 0           select the monitor used by the overlay
--pet-size 128             set the pet height in pixels
--interaction-padding 64   enlarge or shrink the grab area around the pet
--sandbox-window           use the old room-style window
--headless                use an offscreen display for smoke tests
--max-seconds N           exit automatically after N seconds
--no-log                  disable logs/session-*.jsonl
--watch-notifications     read and explain new desktop notifications (opt-in)
```

## Runtime design

```text
Qt overlay ── one request queue ── one worker process
                                      ├─ SmolVLM: action choice + screen evidence
                                      └─ SmolLM:  chat + narration + final wording

screen question: one capture → SmolVLM evidence → SmolLM answer
```

The Qt renderer is a frameless, per-pixel transparent, always-on-top overlay.
Its Wayland mask includes the visible pet plus configurable interaction padding;
the rest of the desktop remains clickable. During movement the renderer briefly
unions the old and new regions, clears them synchronously, then shrinks back to
the current hitbox. This avoids stale boxes and fast-motion trails without using
a separately positioned Wayland surface. One spawned worker lazily loads one
SmolVLM and one SmolLM checkpoint. It processes all requests sequentially, so
the two models never compete for CPU and neither is duplicated in another
process.

SmolVLM handles action labels and extracts evidence from authorized screenshots.
SmolLM handles chat and action narration. A screen question deliberately uses
both in sequence: SmolVLM extracts visible facts, then SmolLM writes the answer.
For chat commands, SmolLM's reply must confirm the same direct action requested
by the user; the intent is then attached to the next pet observation. SmolVLM
chooses whether to execute it or remain idle, and the local scheduler applies
grounding and cooldown rules. Ordinary conversation performs no extra visual
inference.

At each decision boundary the overlay supplies SmolVLM2 with a synthetic
256×256 view of the pet plus its position and motion state. It only captures the
real desktop after a right-click question or an opted-in notification event. The
VLM replies to autonomous decisions with one label: `WALK_LEFT`, `WALK_RIGHT`,
`JUMP`, `THROW`, `HAPPY`, `SAD`, or `IDLE`. A cooldown-aware scheduler validates
the choice, and the pet automatically reverses at monitor edges.

Behavior conditions:

- Walk is the fallback for invalid or rate-limited model output.
- Jump has a 12-second cooldown.
- Throw is allowed only near the screen center and has a 20-second cooldown.
- Happy can also trigger after an edge reversal.
- Sad and idle are accepted directly from SmolVLM2.
- Any two special actions are separated by at least six seconds.

Expressive actions send their structured event to SmolLM for one short
speech-bubble sentence; the image is not reprocessed. Routine walking does not
trigger another generation. Model failures visibly fall back to idle actions
and fixed template narration.

## Verification

```bash
pytest
vla-pet --mock-policy --headless --max-seconds 3 --no-log
python scripts/smoke_vlm.py
python scripts/smoke_coop.py  # verifies both models share one worker PID
python scripts/smoke_portal.py  # opens the desktop screenshot consent dialog
```

The older robotics experiment remains available with:

```bash
python -m pip install -e ".[vla]"
vla-pet --policy vla --offline
```

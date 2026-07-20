# Momo: local SmolVLM + SmolLM desktop companion

Momo is a transparent, always-on-top desktop pet for CPU-first computers. It
walks on the real desktop, can be picked up and dropped, chats through SmolLM,
and uses SmolVLM only for bounded pet actions and explicitly authorized screen
questions. A deterministic life engine keeps the pet animated when every model
is off, loading, or unavailable.

Version 1.2 adds Baby→Child→Teen evolution, persistent HP/STA/INT training,
original Momo v3 growth sprites, a fixed animation contract, and a dedicated
Status page. Version 1.2.1 gives Teen Momo a taller, more fashionable design,
cleans every sprite cut, and fixes walk-facing direction. Version 1.1 added the
cozy habitat, unified panel, quick actions,
and tactile cushion, snack, ball, and box play. Version 1.0 added private memory, push-to-talk voice, useful permission-gated
tools, desktop context, positive-only progression, a mini-game, character and
plugin manifests, onboarding, signed updates, backup/restore, and deployment
rollback. SmolLM, SmolVLM, and optional Whisper run sequentially inside one AI
worker; they are never duplicated into separate model processes.

## Start it

Python 3.10–3.12 is supported. Deterministic pet-only mode needs no model files:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
momo-chan --mock-policy
```

For local SmolLM, SmolVLM, and Whisper:

```bash
python -m pip install -e ".[models,dev]"
momo-chan --device cpu
```

The first launch explains every optional feature before enabling it. Model
checkpoints are downloaded only when local AI is selected; later runs can be
forced to use cached files with `--offline`. Recovery mode starts immediately,
spawns no AI process, reads no sensors, runs no tools or plugins, and writes no
persistent state:

```bash
momo-chan --safe-mode
```

## Interact with the pet

- Left-click pets the character.
- Left-drag picks it up; release anywhere for a slow gravity-based fall.
- Hover for 350 ms, or hold briefly, for Chat, Snack, Ball, Home, and More.
- Drag habitat objects; toss the ball, move the cushion/box, or place a snack.
- Drag the nook's header along the bottom edge; use its corner button to collapse it.
- Ctrl+left-click opens the always-on-top chat.
- Right-click asks one question about one authorized screen capture.
- Ctrl+right-click opens settings, privacy, memory, tasks, play, plugins, and
  redacted activity.
- The tray menu opens Home/chat/growth/settings, toggles privacy mode, or quits.

Chat is cancellable and replies appear incrementally. Direct requests such as
“jump” or “walk left” flow from SmolLM intent to SmolVLM visual action choice,
then through deterministic physics and cooldown safety. Ordinary conversation
does not invoke vision. Direct “go home”, “have a snack”, “play with the ball”,
“sleep”, and “hide in the box” requests become safe habitat intents. Autonomous
habitat vision sees only a synthetic internal 256×256 scene, never the desktop.

The conservative local tool parser recognizes commands such as:

```text
set a timer for 10 minutes
start focus for 25 minutes
add todo finish the release notes
list todos
note: remember the test result
remind me to stretch in 30 minutes
summarize clipboard
read file /an/approved/note.md
search files in /an/approved/folder for report
open app calculator
```

Timers, todos, reminders, and notes are local. Clipboard, file, and application
tools show a one-shot scope confirmation. Tool work executes off the Qt thread,
and audit rows contain identities, scope, timing, and result category—not tool
arguments or private output.

## Voice, memory, and awareness

Voice is push-to-talk and off by default. Linux capture uses an ephemeral
0600-mode WAV that is deleted immediately. The default local provider lazily
loads `openai/whisper-tiny` in the existing AI worker; Qt speech playback is
interruptible and has a self-echo guard. Missing capture, STT, or TTS components
degrade visibly to text chat.

Memory is also off by default. When enabled, explicit preferences, tasks, shared
events, relationship facts, and procedures are deduplicated in SQLite and
retrieved through local FTS5. Secrets are rejected, common identifiers are
redacted, and screenshots/audio are never memories. Every memory can be viewed,
deleted, exported, backed up, or removed with all application data.

Active-application metadata, idle time, battery/network state, notifications,
coding markers, and proactive reactions are individually opt-in. Deny lists,
quiet hours, cooldowns, rate limits, visible reasons, and one-click privacy mode
apply before context reaches companion logic. Awareness never takes an implicit
screenshot.

## Characters, play, plugins, and MCP

The companion has positive-only XP, affection, inventory, daily rewards, focus
milestones, achievements, snacks, toys, and the ten-round Catch the Star game.
Time away never removes progress. `--sandbox-window` remains the bounded room
mode.

Momo begins in Baby form, becomes Child Momo at 300 XP, and Teen Momo at 1000
XP. Rest, snacks, and daily check-ins train HP; ball play and games train STA;
chat, focus, and box exploration train INT. Stats cap at 99 and never decay.
Open **Status** in the companion panel to see the next form and training progress,
or ask Momo “what are your stats?” in chat.

Character packs are source-free data directories selected with `--assets`.
Schema v2 declares contained animation frames, hitbox, persona, voice, emotion
mapping, license, and attribution. `characters/orbit` is the included original
CC0 sample pack.

Two bundled plugins demonstrate focus and companion-care hooks. Plugin state is
namespaced and quota-bound; code plugins require file hashes, a trusted Ed25519
signature, declared capabilities, explicit enablement, and Linux bubblewrap
isolation with no network by default. The optional MCP stdio bridge accepts only
an absolute executable, requires a per-server grant, uses bounded JSON-RPC, and
enforces a timeout. Arbitrary shell and desktop automation are not stable tools.

Specifications:

- [Architecture](docs/architecture.md)
- [Privacy model](docs/privacy-model.md)
- [Character pack v2](docs/character-pack-spec-v2.md)
- [Character pack v3](docs/character-pack-spec-v3.md)
- [Character pack v4 growth forms](docs/character-pack-spec-v4.md)
- [v1.2 feature audit](docs/feature-audit-v1.2.md)
- [v1.2 release evidence](docs/release-evidence-v1.2.md)
- [Plugin API v1](docs/plugin-spec-v1.md)
- [Tool and permission API v1](docs/tool-permission-spec-v1.md)
- [Signed update manifest v1](docs/update-spec-v1.md)
- [v1.0 release evidence](docs/release-evidence-v1.0.md)

## Private data and recovery

Linux data follows XDG directories. Windows uses roaming/local AppData and macOS
uses the appropriate `Library` directories. Useful recovery commands:

```bash
momo-chan --diagnostics
momo-chan --export-data ~/momo-chan-export.json
momo-chan --backup-data ~/momo-chan-backup.db
momo-chan --restore-data ~/momo-chan-backup.db
momo-chan --clear-conversations
momo-chan --reset-pet-state
momo-chan --reset-onboarding
momo-chan --delete-all-data
```

Automatic release checks are disabled until a user supplies a signed manifest
URL, channel, key id, and Ed25519 public key in Settings. Checks run in the
background and only announce a newer verified version. The CLI can verify and
stage the signed artifact explicitly; installation remains visible and
rollback-capable:

```bash
momo-chan --check-update update.json \
  --update-public-key release-key.pub \
  --download-update verified.whl
```

The operator creates manifests with `scripts/sign_update_manifest.py`. Private
release keys, public-store certificates, notarization credentials, and update
hosting are intentionally not stored in this repository.

## Build, verify, and install

```bash
python scripts/verify_project.py
python scripts/verify_project.py --with-models --with-voice-model
python scripts/verify_project.py --with-performance
python -m build --no-isolation
python scripts/verify_release.py --artifact "dist/*-1.2.1-*.whl"
python scripts/install_linux.py \
  --wheel dist/smolvla_pet_sandbox-1.2.1-py3-none-any.whl --models
python scripts/install_linux.py --rollback
python scripts/install_linux.py --uninstall
```

The umbrella verifier runs lint, compile, coverage, build/wheel inspection,
10,000-item memory performance, packaging contracts, safe-mode UI smoke,
backup/restore, isolated install, upgrade, rollback, and uninstall. Optional
flags add cached-model, voice-model, and five-minute CPU gates.

Linux GNOME Wayland is the v1.2 live reference platform. Windows and macOS have
CI/domain and packaging contracts, but no live hardware claim is made here.
Model weights are not bundled. The older SmolVLA robotics experiment remains
available through `.[vla]` and `--policy vla`; SmolVLM is the desktop default.

The public command is `momo-chan`. The former `vla-pet` command remains as a
compatibility alias for existing scripts and installations.

The v1.2 artifact bundles only the provenance-documented Momo v3 growth pack and the
original CC0 Orbit sample. Unresolved prototype PNGs remain in source history
but are explicitly excluded from wheel and source distributions; see
[ATTRIBUTION.md](ATTRIBUTION.md).

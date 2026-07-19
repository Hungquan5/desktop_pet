# Architecture

The transparent PySide6 overlay is an adapter around deterministic `PetWorld`,
animation, and `RuntimeController` state. Paint and pointer handlers perform no
model inference, sensor polling, plugin subprocess, update request, or long tool
work. A bounded typed event bus carries immutable traceable events; the life
engine owns needs, emotion, routines, relationship, and positive progression.

```text
Qt input/platform adapters ─▶ EventBus ─▶ RuntimeController ─▶ SQLite v2
          │                                    │
          ├─ renderer/physics/life (local)     ├─ memory + tasks
          ├─ permission broker                 └─ progression
          ├─ async tools/plugins/updates
          └─ AIOrchestrator ─▶ one sequential worker
                                  ├─ SmolLM language
                                  ├─ SmolVLM visual evidence/actions
                                  └─ lazy Whisper STT
```

The worker owns a lazy provider registry. SmolLM handles wording and language
intent; SmolVLM handles bounded visual decisions/evidence; deterministic code
owns motion, cooldowns, scopes, and safety. The queue prevents CPU contention and
duplicate model copies. Mock, pet-only, onboarding, and safe modes use the same
contracts inline and spawn no model process. Provider failure becomes a typed
fallback and does not terminate the overlay.

`StateRepository` owns transactional SQLite migrations, v1-to-v2 backup,
settings, memories/FTS, tasks, progression snapshots, plugin namespaces, and
redacted tool audit. Operational JSONL logging is a separate centrally redacted
channel. Model cache, database, config, and logs use platform user directories.

Every optional I/O path crosses `PermissionBroker`. It supports named
capabilities, subject identity, exact scopes, one-shot/session/always lifetimes,
revocation, persistent denial, and safe-mode denial. Screen capture is direct
user action only. Awareness metadata is sampled through a platform probe and
filtered before policy evaluation; it never implicitly invokes vision.

Core tools and plugin hooks run on bounded background executors with independent
database connections. Plugins additionally require manifest integrity,
signature trust for third-party code, declared capabilities, quotas, output
bounds, and a Linux sandbox. MCP is an optional separately granted stdio bridge.
Signed updates verify on a background executor and never install silently.

The UI is a composition root, not a policy authority: models, plugins, or MCP
cannot import a privileged handler to bypass permission checks. Safe mode omits
all optional executors and persistence while retaining the deterministic pet.

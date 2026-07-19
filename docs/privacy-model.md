# Privacy model

The stable profile is local-first and optional capabilities are off by default.
SmolLM, SmolVLM, and Whisper use local Transformers in one worker. An explicitly
configured OpenAI-compatible language endpoint is the only remote model path;
plain HTTP is restricted to localhost and the endpoint choice is user supplied.

- Screenshots require a direct right-click question and compositor/portal
  approval where applicable. Pixels are ephemeral and never stored.
- Push-to-talk requires a microphone grant. Its 0600 WAV is deleted after the
  turn; raw audio and transcripts are absent from operational logs.
- Notifications, active app/title metadata, idle time, battery/network, coding
  markers, proactive reactions, voice, memory, chat persistence, plugins, and
  update checks are independently opt-in.
- Privacy mode suppresses optional context and notification reactions. Deny
  lists remove matching application/title metadata before companion policy.
- Memory extracts explicit preferences/tasks/shared events only, rejects common
  secret patterns, redacts email-like identifiers, and never stores pixels or
  audio. Users can inspect/delete each item or clear all memory.
- Tool permission is checked before handler/subprocess work. Audit stores
  identity, scope, decision, timing, and error category—not raw arguments,
  clipboard, file contents, chat, notification bodies, pixels, or audio.
- Third-party plugins require trust, declared scope, user enablement, quotas,
  namespaced storage, and sandboxing. Network is absent unless declared and
  granted. Stable v1 refuses plugin filesystem writes.
- Signed update checks are off until a manifest source and public key are
  supplied. Verification never sends telemetry and never silently installs.
- `--safe-mode` denies AI, sensors, capture, voice, tools, proactivity, plugins,
  updates, custom packs, and persistence writes.

Private state can be exported, backed up, restored, cleared by category, or
deleted completely. Backup restore validates SQLite integrity/schema before an
atomic replacement. Operational diagnostics contain platform/package/capability
availability and schema health, not user content.

# Character pack schema 3

Schema 3 extends the v2 persona/voice manifest without breaking v1 or v2 packs.

Required fields remain `schema_version`, `id`, `canvas_size`, and the six core
`animations`: `idle`, `walk`, `jump`, `throw`, `happy`, and `sad`. Schema 3 also
declares a pack `version` and may provide the expressive roles `fall`, `held`,
`landing`, `eat`, `play`, `sleep`, `box`, `think`, `listen`, and `talk`.

Optional schema-3 metadata:

- `ui.accent`: character-specific UI accent color.
- `sound_attribution`: file-to-attribution mapping for bundled sounds.
- `emotion_map`: runtime emotion tag to animation-role mapping.

Every frame path is resolved beneath the pack directory; absolute paths and
parent traversal are rejected. v1/v2 packs load unchanged. Missing expressive
roles fall back to a semantically safe core animation.

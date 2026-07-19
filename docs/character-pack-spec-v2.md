# Character pack specification v2

A character pack is a directory containing `character.json` and all referenced
assets. Load it with `vla-pet --assets PATH`. No Python change is required.

Required top-level fields are `schema_version: 2`, a safe alphanumeric/hyphen
`id`, `display_name`, positive two-value `canvas_size`, `license`, `animations`,
`persona`, `voice`, `hitbox`, `emotion_map`, and `attribution`.

Every `ActionKind` (`walk`, `jump`, `throw`, `happy`, `sad`, and `idle`) must
have an animation object:

```json
{
  "frames": ["walk-*.png"],
  "fps": 8,
  "loop": true,
  "priority": 10
}
```

Frame paths and glob matches must remain inside the pack root. Absolute paths,
`..`, empty matches, invalid images, and FPS outside 0.1–120 are rejected. The
runtime caches scaled frames and uses manifest priority/timing without filesystem
work in paint callbacks.

`persona` requires `name` and `system_prompt`; optional fields are `greeting` and
`traits`. `voice` declares `provider`, `voice_id`, `rate`, and `pitch`. Rate and
pitch are clamped to -1..1. `hitbox.padding` is 0..160 and
`hitbox.alpha_threshold` is 0..255. Emotion-map values name existing animation
labels.

Every distributable pack must state its asset license, author/source attribution,
and any separate voice/font/sound terms. Invalid custom packs fall back to the
built-in safe character with a stable diagnostic code.

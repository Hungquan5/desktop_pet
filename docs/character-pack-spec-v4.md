# Character pack specification v4

Schema v4 adds deterministic growth forms to the schema-v3 persona, voice,
expressive-animation, attribution, UI-accent, and sound metadata. Older schema
v1–v3 packs still load as single-form characters.

## Fixed animation contract

Every growth form must provide these roles:

```text
idle walk jump throw happy sad fall held landing
eat play sleep box think listen talk evolve
```

Roles may contain one or more relative frame paths. Each animation declares
`fps`, `loop`, and `priority`. Paths must remain within the pack, FPS must be
0.1–120, and every referenced file must exist. The renderer may safely reuse a
pose across roles, but the role itself cannot be omitted.

## Growth stages

`growth_stages` must contain exactly `baby`, `child`, and `teen`:

| Stage | Minimum XP | Default scale |
|---|---:|---:|
| Baby | 0 | 0.90 |
| Child | 300 | 1.00 |
| Teen | 1000 | 1.18 |

The Baby stage may inherit the top-level `animations` object. Child and Teen
must explicitly provide the complete fixed role set so a missing later form is
rejected during pack loading rather than during rendering. `scale` is bounded
to 0.5–1.5. The pack's overall `default_scale` remains bounded to 0.5–2.0.

Example shape:

```json
{
  "schema_version": 4,
  "animations": {"idle": {}, "walk": {}, "evolve": {}},
  "growth_stages": {
    "baby": {"display_name": "Baby", "minimum_xp": 0, "scale": 0.9, "animations": {}},
    "child": {"display_name": "Child", "minimum_xp": 300, "scale": 1.0, "animations": {}},
    "teen": {"display_name": "Teen", "minimum_xp": 1000, "scale": 1.18, "animations": {}}
  }
}
```

The abbreviated animation objects above show structure only; real Child and
Teen objects must contain all 17 roles. Evolution thresholds are application
rules, not user-configurable pack behavior, so every pack evolves consistently.

## Compatibility and safety

- Schema v1–v3 packs render their base animation at every application stage.
- Growth and RPG stats live in private pet state, not in character assets.
- A malformed custom pack falls back to the bundled Momo pack with a stable
  diagnostic code.
- Source atlases, generation prompts, and editing files are provenance material
  and are excluded from release packages; only runtime frames are shipped.

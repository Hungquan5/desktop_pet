# Momo v3 growth asset provenance

- Generated: 2026-07-20
- Tool path: OpenAI built-in image generation, followed by the imagegen skill's
  local chroma-key removal helper and deterministic atlas cropping.
- License: CC-BY-4.0 for the project-bound derived sprite assets.
- Identity references: the original Momo v2 atlas and the prior Momo v3 Child
  and Teen atlases. In pack 3.1, the former Teen design becomes Child Momo and
  Teen Momo receives a new, visibly older design.
- Generated source atlases:
  - `source/child_atlas_chroma.png`
  - `source/teen_atlas_chroma.png`
  - `source/evolution_atlas_chroma.png`
- Runtime output: 16 transparent 128×128 frames for Child Momo, 16 for Teen
  Momo, the 16 existing Baby Momo frames, and four shared evolution frames.

Final prompt summary: preserve Momo's cream hair, brown eyes, cocoa horns/ears,
cow tail, tomato red, gold, mint, and brown identity while giving Teen Momo a
clearly taller adolescent silhouette, gold-banded horns, half-up flowing hair,
braided crown, elegant high-low coat-dress, mint waistcoat, layered skirt,
opaque leggings, and detailed knee-high boots. The design remains wholesome,
age-appropriate, and non-sexualized. Each growth atlas uses the fixed 4×4 role
order with one complete pose inside a protected cell safe area; the 2×2 atlas
shows Baby→Child→Teen evolution. Sources were generated on a flat green chroma
background with no text, logos, watermark, or franchise identity. Chroma-key
removal and cell-aware crops produced the runtime frames.

The runtime never loads files under `source/`; release packages include only
the transparent cropped frames, this provenance record, and `character.json`.

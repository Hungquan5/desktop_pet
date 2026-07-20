# Attribution and asset review

The v1.1 release character is the original Momo v2 pixel-chibi atlas under
`animations/momo_v2/`. Its source prompt, generation mode, deterministic
post-processing, frame list, and license are recorded in
`animations/momo_v2/PROVENANCE.md`. The release wheel includes this pack under
CC BY 4.0 and does not include the six unresolved prototype PNG files retained
at the root of `animations/` for source-history review.

`assets/sounds/momo_pop.wav` is an original synthesized soft interaction tone
created for this repository and dedicated to the public domain under CC0-1.0.

`characters/orbit/orbit.svg` is an original geometric sample created for this
repository in 2026 and dedicated to the public domain under CC0-1.0, as declared
in its character manifest. It can be used for redistributable technical builds
without the prototype PNG files.

Model weights are not bundled. Their licenses and usage conditions are governed
by their respective Hugging Face repositories.

Optional model dependencies are installed as separate upstream distributions;
their package metadata and license files remain intact. In particular,
SmolVLM's processor uses `torchvision` (BSD-3-Clause) and `num2words` (LGPL-2.1
or later). Neither project is copied into this repository or bundled in its
application wheel.

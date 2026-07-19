# Attribution and asset review

The application source is developed in this repository. The six PNG files in
`animations/` predate the v0.2 packaging work and currently have no independently
verified redistribution license. They are marked accordingly in
`animations/character.json`.

Do not publish a binary release containing those images until their author,
source, and redistribution terms are recorded here. Every future character pack
must declare its own license and attribution in `character.json`.

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

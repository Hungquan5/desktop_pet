# Signed update manifest `pet.update/v1`

Release checking is off by default. The user/operator configures an HTTPS (or
local test file) manifest, channel, key id, and base64 Ed25519 public key.
Background checks have a domain-scoped `update_check` grant and never install
silently.

The signed JSON object contains:

```json
{
  "schema": "pet.update/v1",
  "version": "1.0.1",
  "channel": "stable",
  "minimum_database_schema": 2,
  "release_notes": "...",
  "artifact": {
    "url": "https://updates.example/vla-pet.whl",
    "sha256": "64 lowercase hexadecimal characters",
    "size_bytes": 12345
  },
  "signature": {
    "algorithm": "ed25519",
    "key_id": "vla-pet-release",
    "value": "base64 signature"
  }
}
```

The signature covers canonical UTF-8 JSON after removing `signature`. The client
rejects an unknown schema/key/algorithm, invalid signature, wrong channel,
non-semantic version, non-HTTPS artifact, invalid hash, and size outside 1 byte
through 2 GiB. Downloads are private mode 0600 and must match both signed size
and SHA-256 before they can be staged.

Use `scripts/sign_update_manifest.py` to generate/sign a manifest and export the
public key. Keep the raw private key outside the repository. Platform installers
own the visible atomic switch and rollback; the update checker never executes a
downloaded artifact.

# Plugin API `pet.dev/v1`

`plugin.json` uses `apiVersion: pet.dev/v1` and `kind: ToolPlugin`. Metadata
requires a safe name, semantic version, display name, author, license, and the
`builtin` marker. The spec declares one runtime (`builtin`,
`python-subprocess`, or `mcp-stdio`), argv-style relative entrypoint, hook names,
permissions, quotas, and storage limit.

Each permission contains a `Capability`, exact scope object, and default
decision. Enabling a plugin is an explicit user action. Runtime calls still
require `plugin_execute` plus every declared scoped capability; enablement alone
cannot bypass the broker.

`integrity` maps every shipped plugin file to `sha256:...`. Repository-bundled
plugins under the trusted built-in root may omit a signature. Every third-party
manifest must include an Ed25519 signature over canonical JSON without the
`signature` field, and the key must already be trusted by the host.

Python subprocess plugins receive one JSON object on stdin and must return one
JSON object on stdout. Input/output are limited to 64 KiB. Timeout, invocation
rate, address-space, CPU, open-file, and namespaced-storage quotas are enforced.
On Linux, third-party Python runs in bubblewrap with a read-only runtime and
plugin root, private `/tmp`, no network by default, and only declared read-only
path binds. Stable v1 refuses third-party filesystem-write requests.

Hooks are bounded best-effort events. A queue overflow drops the new hook rather
than slowing the renderer. Plugin failures are logged by identity and category,
never with raw hook payloads.

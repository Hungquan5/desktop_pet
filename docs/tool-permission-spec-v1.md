# Tool and permission API v1

Every tool has a dotted name, description, JSON-object input schema, risk class,
named capability, timeout, subject, and visible-indicator policy. A tool call has
unique invocation/trace identifiers, arguments, explicit-user-action marker,
and a short reason.

The execution order is fixed:

1. Resolve the registered manifest.
2. Validate input keys, required fields, and primitive types.
3. Build the exact path/domain/application scope.
4. Deny safe mode or an absent/scopeless grant before calling the handler.
5. Execute away from the Qt input/paint thread.
6. Bound and JSON-validate output to 64 KiB.
7. Consume one-shot permission and record a redacted audit result.

Capabilities support `once`, `session`, and `always-until-revoked` lifetimes,
subject identity, revocation, denial, and contained filesystem or allowlisted
domain/application scopes. Runtime grants remain process-local. One-shot screen
capture additionally requires a direct user action each time.

Audit rows include invocation/trace id, tool, subject, capability, scope, risk,
decision, status, duration, error code, reason length, and input key names. They
exclude reason text, argument values, clipboard/file content, chat, pixels,
notifications, and audio. A denied invocation starts zero handler or subprocess
work.

Stable v1 exposes bounded timers, focus, todos, reminders, notes, clipboard
summary, approved text-file read/name search, and allowlisted application open.
It exposes no arbitrary shell, unrestricted browser control, or desktop
automation.

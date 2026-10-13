# Compare a costly interface choice

Use this for an interface change with substantial compatibility, ownership, or
migration cost. Compare alternatives locally unless the user explicitly requested
independent agents and the environment supports them.

Frame the same problem for each design: current callers, accepted behavior,
external dependencies, lifecycle, cancellation, failure, and persisted data.
Compare distinct approaches, not cosmetic method names:

- Minimum caller knowledge using an existing owner.
- A dedicated owner when real behavior otherwise scatters across callers.
- Composition of current contracts when platform or external effects must stay separate.

For each approach, show the interface, a real caller example, the hidden complexity,
dependencies, migration path, and validating tests. Consider latency, resource
cleanup, and maintainability. Prefer the simplest design that satisfies the actual
requirements; a flexible extension point needs a present use.

Examples in Clarify:

- A provider adapter owns payload shape while `provider_http.py` owns retries;
  adding a workflow-specific HTTP wrapper would duplicate policy.
- `QtRecordingSession` owns the production capture file; a local inference adapter owns its
  process and cancellation. Merging them can make cleanup wait on the wrong owner.
- A QML bridge can be thin because it isolates Qt thread/state interaction from
  the UI-independent application service.

Keep a behavior-to-test map when replacing old tests. Remove redundant coverage
only after each old invariant, migration, and platform contract is accounted for.
Preserve tests for behavior that still exists behind a different internal shape.

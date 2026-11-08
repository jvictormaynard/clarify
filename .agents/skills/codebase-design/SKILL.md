---
name: codebase-design
description: "Design module interfaces, ownership, dependencies, and test boundaries for a feature or refactor."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Design Clarify modules

Read `CONTRIBUTING.md` and `docs/architecture.md`. Trace the real callers, adapters, state, and tests before choosing a design.

A deep module hides meaningful complexity behind a small interface. Judge depth by what callers need to know, not file length. An interface includes types, errors, ownership, ordering, cancellation, and observable effects. A seam is where a dependency can be substituted. Use the repository's existing terms, including service, gateway, adapter, repository, and boundary.

Prefer existing owners:
- `workflows.py` owns workflow commands, operation identity, state, cancellation, and publication.
- `provider_registry.py` and typed provider contracts own provider routing; `provider_http.py` owns transport policy.
- `QtRecordingSession` and `QtRecordingAudioGateway` in
  `clarify/desktop/qml_runtime.py` own production capture lifecycle and temporary
  audio through the workflow contracts. Preserve the separate legacy
  `RecordingSession` in `app.py` while its compatibility callers still exist.
- `repositories.py` and `secret_store.py` own configuration transactions and credentials.
- Production Qt adapters live in `clarify/desktop/`; Settings live in `desktop/`.

Use source discovery if a filename or responsibility has moved.

For a proposed change, explain:
1. Which owner changes and what callers observe.
2. What complexity the interface hides, and what each dependency owns.
3. How cancellation, errors, retries, resources, and compatibility behave.
4. Which existing contract tests prove those behaviors.

A deletion thought experiment can expose a pass-through, but a thin adapter can still earn its place through a real platform, typing, lifecycle, or security contract. A single production implementation can justify a protocol when it isolates Windows, Qt, a provider, or another external effect.

For a costly interface decision, read [design alternatives](references/design-alternatives.md). Keep safe internal refactoring within the authorized task. Propose a broader redesign when evidence shows it is needed; do not move product behavior into `app.py` or `spikes/`.

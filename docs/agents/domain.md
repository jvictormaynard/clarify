# Clarify domain language and decisions

Use this small glossary for stable product terms. The implementation and owned
contracts remain in [Architecture](../architecture.md). Update a term only when
the current task clarifies or changes its meaning; do not copy the architecture
manual or create a second root glossary.

| Term | Meaning |
| --- | --- |
| Dictation | Capture speech, transcribe it, optionally refine it, then publish the accepted result |
| Rewrite | Transform selected text through the configured text workflow |
| Translation | Translate selected text or recorded speech into an explicit target language |
| Workflow | The application command/state lifecycle for an operation, including cancellation and publication |
| Operation ID | The monotonic session identity used to reject a stale worker result |
| Publication | The claimed external result effect; usage is accounted once for an accepted publication |
| Provider route | The explicitly selected provider/model/endpoint and capabilities for a workflow |
| BYOK | Cloud use with the user's own provider credential; it does not describe keyless local ASR |
| Local Whisper | Optional local ASR with separately installed verified runtime/model assets and no implicit cloud fallback |
| Recording session | The owner of capture lifecycle and its temporary audio, separate from provider inference |
| Settings draft | Edits that become persisted configuration only through the shared validated apply transaction |
| SecretStore | The provider-keyed credential boundary; Windows uses current-user DPAPI |
| Pill | The production Qt/QML workflow surface, separate from React/Tauri Settings |
| Community release | The unsigned portable track with its explicit assets and limits |
| Signed release | The publisher-verified installer/update track gated by the distribution contract |

Use ordinary architecture terms that match the source: module, interface, service,
gateway, adapter, repository, and boundary. A module's depth means useful behavior
behind a simple contract. It does not mean a large file or the removal of every
small adapter.

Create an ADR under `docs/adr/` only for a new accepted decision that is costly to
reverse, has real alternatives, and needs a durable explanation. Create the directory
when the first such record is needed. Reference existing architecture and release
decisions instead of retroactively inventing approval or duplicate ADRs.

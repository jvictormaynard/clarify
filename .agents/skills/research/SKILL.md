---
name: research
description: "Verify uncertain library, platform, provider, or licensing facts against primary sources."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Research a Clarify question

Define the question, its decision, and the time sensitivity. Inspect the project's pinned versions and local source first. For external facts, use official documentation, original source code, specifications, or first-party release and license records.

Separate verified facts, source-based inference, and unknowns. Cite the exact source URL or file and the version or date where it matters. Compare relevant alternatives against Clarify's architecture, runtime size, Windows support, tests, and licensing.

Write a concise note under `docs/agents/research/` only when the result will be reused; otherwise include the evidence in the current answer or PR. Keep credentials, transcripts, recordings, and personal paths out of notes.

Research runs locally by default. Delegate only when the user explicitly requested agents and the environment permits them. A research result is not permission to add a dependency, provision a service, or perform publication.

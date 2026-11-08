---
name: improve-codebase-architecture
description: "Audit architectural friction and rank refactor candidates when an architecture review is requested."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Audit Clarify architecture

Read `CONTRIBUTING.md`, `docs/architecture.md`, and the sibling `codebase-design` skill. Use the requested area; for a whole-repository audit, inspect recent change hotspots and also the major ownership boundaries.

Compare architecture, functionality, organization, user experience, testing, and delivery constraints. Trace current callers, state, dependencies, failure paths, and tests. Account for intentional thin Qt/Tauri adapters, compatibility code, and platform-specific seams.

For each supported candidate, give:
- Files and current responsibilities.
- A concrete change or defect that is costly today.
- A proposed owner and interface, with before/after responsibility.
- Expected benefit, migration cost, risk, and validating tests.
- Evidence strength: confirmed, worth investigating, or speculative.

Rank by demonstrated recurring cost and risk reduction. Reject generic file-length rules and abstractions for hypothetical use cases. Preserve ownership for recording cleanup, provider HTTP, configuration transactions, DPAPI, and workflow publication.

Use diagrams or a local HTML report when they help compare candidates. Reports should work offline; do not require CDN scripts or automatically open a browser. A text report is enough for a small audit.

An audit request authorizes analysis. Implement only candidates within an implementation request; present broader candidates for a product or scope decision. Explore costly interfaces with the design-alternatives reference. Do not require subagents.

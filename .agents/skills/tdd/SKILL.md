---
name: tdd
description: "Implement behavior changes with useful regression tests through isolated red, green, and refactor cycles."
---

# Test changed Clarify behavior

Apply [tests worth retaining](../../../docs/agents/workflow.md#tests-worth-retaining)
before choosing TDD. Inspect the real contract and existing tests. Name the
regression risk, choose the lowest useful boundary, and extend an existing case
or table where it fits. Test-boundary choices do not require user approval.

For each distinct risk:

1. Add an independent expected result that can detect the actual symptom.
2. Run it before the fix. Confirm failure comes from behavior, not the environment.
3. Make the smallest coherent implementation and confirm the test passes.
4. Refactor when useful, then rerun affected checks. Do not repeat the final suite
   without a new change, failure, or unresolved concern.

Use the existing unittest, Vitest, and Playwright/Python fixtures under the
[shared test boundaries](../../../docs/ci-delivery.md#ownership-and-commands).
Keep external effects fake and profiles temporary. Internal assertions and call
counts are useful when they protect an actual platform, security, concurrency,
or once-only effect contract.

Pure cosmetic/copy edits and one-time smoke checks can use direct validation
without new retained tests. Do not discard distinct existing coverage.
Read [test examples](references/test-examples.md) only when a boundary is unclear.

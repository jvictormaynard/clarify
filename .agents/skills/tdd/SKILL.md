---
name: tdd
description: "Implement changed behavior or regressions through isolated red, green, and refactor cycles."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Test changed Clarify behavior

Choose the public contract from the code and the acceptance criteria. Prefer existing tests and fixtures. Explain the selected boundary briefly; technical test choices do not require a new user approval.

For each useful behavior:
1. Write a focused test with an independent expected result.
2. Run it and confirm it fails for the target behavior, not an import or environment error.
3. Make the smallest coherent implementation.
4. Run the test again.
5. Refactor when it improves the design, then rerun the affected tests.

Use `unittest` for Python, Vitest for headless Settings units, and the existing
Playwright/Python fixture for browser, bridge and production boot checks. Follow
the [test boundaries](../../../docs/ci-delivery.md#ownership-and-commands).
Use fake HTTP, clocks, schedulers, clipboard gateways, secret stores, and
temporary profiles. Keep real provider keys, microphones, and personal audio
outside tests.

Assert observable contracts. Internal tests are appropriate when a private synchronization or platform contract is the only way to prove a real invariant; explain that choice. Call order and counts matter when they prove once-only publication, retry bounds, or ownership.

Cover the cases that can change the outcome: success, failure, cancellation, stale operation, and compatibility where relevant. Do not write a test for each implementation line. Documentation-only and reversible cosmetic changes usually need validation, not new product tests.

Preserve old tests until their behavioral coverage is replaced and any platform, migration, or security evidence is accounted for. A passing unit test does not prove native Windows interaction.

Read [Clarify test examples](references/test-examples.md) if the contract or fixture choice is unclear.

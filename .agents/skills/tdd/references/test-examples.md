# Choose a Clarify test boundary

Read the existing fixture and test module before creating another one.

| Behavior | Useful boundary and evidence |
| --- | --- |
| Cancelled or stale workflow | `WorkflowService` with controlled gateways/scheduler; assert no clipboard/statistics publication |
| Publication ownership | A blocking clipboard gateway and controlled concurrency; verify an accepted effect completes once before readiness |
| Configuration apply | A temporary `LocalConfigRepository` and fake SecretStore; read back persisted state and rollback after failure |
| Provider request/response | `ProviderRegistry` with fake HTTP; verify typed outcomes, capability rejection, and cancellation |
| Recording or local-ASR cleanup | Existing session/backend fixtures; observe owned resource cleanup and process state |
| Settings draft/save | Existing Playwright fixture plus the Python controller; observe UI state and persistence |
| Native focus/hotkey/DPI | Relevant QML smoke checks plus the real packaged Windows interaction where required |

A literal expected value or worked example must come from the contract. Do not
calculate the expected result with the same algorithm as the implementation.

Mock external effects and unstable inputs; keep domain logic real where practical.
Multiple assertions can describe one invariant. A once-only gateway count is useful
when the actual contract is once-only publication; a call-count test of a trivial
helper is usually coupled to its implementation.

Red evidence must reach the reported path. A failed import, missing browser, or
unavailable dependency does not demonstrate a product regression. Correct the
environment or state the limitation before evaluating the fix.

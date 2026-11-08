---
name: diagnosing-bugs
description: "Diagnose crashes, failed workflows, intermittent defects, or measured performance regressions."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Diagnose a Clarify defect

Capture the exact symptom, affected version, platform, and trigger. Inspect the relevant path to build the smallest useful reproduction. Use a failing test, isolated fixture, QML smoke harness, Settings browser test, or packaged Windows observation that can detect the reported symptom.

Run the reproduction before claiming a cause. Preserve original and reduced scenarios. If the live symptom cannot be reproduced, distinguish confirmed source facts from hypotheses and continue useful source investigation; do not claim the defect is fixed.

Rank plausible causes by the evidence. Use as many hypotheses as the problem needs. For each, name a distinguishing prediction and change one factor at a time. Use temporary, tagged instrumentation with sanitized output. For timing defects, use controlled schedulers, barriers, or repeated measured runs rather than arbitrary sleep-based assertions.

For performance work, capture a baseline and comparable inputs before the change. Report observed latency and variance; do not estimate a speedup from source inspection.

Trace Qt command/state and focus paths, provider routing and transport, configuration-to-rendering paths, or recording/sidecar lifecycles as applicable. Choose proof under [tests worth retaining](../../../docs/agents/workflow.md#tests-worth-retaining). For a logic or state bug, extend a regression at the boundary that reaches the actual pattern. For a purely visual defect, use before/after captures. Fix the cause and rerun the relevant proof and original scenario.

Remove temporary instrumentation. Report the cause, the changed owner, the evidence, and any unavailable Windows acceptance. Ask for additional evidence only when it blocks a required conclusion.

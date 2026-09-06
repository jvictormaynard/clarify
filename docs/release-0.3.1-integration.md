# Local change integration for 0.3.1

The complete working tree was preserved as local commit `09b56b4` before
integration. It was based on `37b3459`, while the published 0.3.0 release uses
`7d498d6`. The candidate merges that snapshot into the published source history.

The 0.3.0 release already includes the rename, provider/model settings, local
Base/Small/Medium profiles, CPU/CUDA setup, latency measurements, pause processing,
dictionary context, HTTP changes, and most local tests and packaging changes.
Those features remain included. Later published improvements also remain:
same-audio retry, cancellation undo, focus handling, model-file reuse, unified
installation, translated feedback and the current compact settings components.

New in this integration: explicit refinement-failure metadata, exact original
text on fallback, cancellation verification, a temporary warning, partial
history records, recovery regression tests and the comparative analysis.
The published runtime already had a basic refinement fallback; this patch
completes its visible feedback, preservation and history behavior.

The snapshot's `ModelSettings.qml`, `ProviderSettings.qml` and
`SettingsComboBox.qml` were superseded by the published settings composition,
including `WorkflowModelForm.qml` and `SearchSelect.qml`. Adding unused old
components would not restore a feature. They remain preserved in the snapshot,
while the release retains the newer active implementation.

The release uses `main`, the live default branch, and the existing community
portable workflow. It does not change signing infrastructure or enable MSI updates.

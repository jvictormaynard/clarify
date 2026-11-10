import Foundation

// Direct TextComposer service. No editor or system presentation is created.
@MainActor
enum ApplePrivateRewrite {
  static func report(_ source: String, preferences: OutputPreferences,
    operationID: String) async throws -> AppleRewriteReport {
    let started = ContinuousClock.now
    try Task.checkCancellation()
    guard !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      source.utf8.count <= AppleRewriteEngine.maxInputBytes else {
      return AppleRewriteReport(result: "", error: "Use a shorter text for the Apple Intelligence prototype.",
        code: "private_input_limit", stage: "private_service", candidate: "", rewritten: "", elapsedMS: 0)
    }
    let reply: [String: Any] = await withTaskCancellationHandler(operation: {
      try Task.checkCancellation()
      return await withCheckedContinuation { continuation in
        ClarifyPrivateWritingToolsBridge.rewrite(source, style: preferences.style.rawValue,
          operationID: operationID) { value in continuation.resume(returning: value) }
        if Task.isCancelled { ClarifyPrivateWritingToolsBridge.cancelOperation(operationID) }
      }
    }, onCancel: { Task { @MainActor in ClarifyPrivateWritingToolsBridge.cancelOperation(operationID) } })
    try Task.checkCancellation()
    let duration = started.duration(to: .now).components
    var report = AppleRewriteReport(result: reply["text"] as? String ?? "",
      error: reply["error"] as? String ?? "The private Apple rewrite route is unavailable.",
      code: reply["code"] as? String ?? "private_unavailable", stage: "private_service",
      candidate: "", rewritten: "",
      elapsedMS: Int(duration.seconds * 1_000 + duration.attoseconds / 1_000_000_000_000_000))
    let metadata = reply["diagnostics"] as? String ?? ""
    report.diagnostics = String(decoding: metadata.utf8.prefix(AppleRewriteEngine.maxOutputBytes - 3), as: UTF8.self)
    report.route = "private_textcomposer"
    return report
  }
}

import Foundation

// Read-only TextComposer contract probe. This build does not invoke its model.
@MainActor
enum ApplePrivateRewrite {
  static func report(_ source: String, preferences: OutputPreferences,
    operationID: String) async throws -> AppleRewriteReport {
    let started = ContinuousClock.now
    try Task.checkCancellation()
    guard !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      source.utf8.count <= AppleRewriteEngine.maxInputBytes else {
      return AppleRewriteReport(result: "", error: "Use a shorter text for the Apple Intelligence prototype.",
        code: "private_input_limit", stage: "private_probe", candidate: "", rewritten: "", elapsedMS: 0)
    }
    let reply: [String: Any] = await withCheckedContinuation { continuation in
      ClarifyPrivateWritingToolsBridge.rewrite(source, style: preferences.style.rawValue,
        operationID: operationID) { value in continuation.resume(returning: value) }
    }
    try Task.checkCancellation()
    let duration = started.duration(to: .now).components
    var report = AppleRewriteReport(result: "",
      error: reply["error"] as? String ?? "The private Apple rewrite route is unavailable.",
      code: reply["code"] as? String ?? "private_unavailable", stage: "private_probe",
      candidate: "", rewritten: "",
      elapsedMS: Int(duration.seconds * 1_000 + duration.attoseconds / 1_000_000_000_000_000))
    let metadata = reply["diagnostics"] as? String ?? ""
    report.diagnostics = String(decoding: metadata.utf8.prefix(AppleRewriteEngine.maxOutputBytes - 3), as: UTF8.self)
    report.route = "private_textcomposer_probe"
    return report
  }
}

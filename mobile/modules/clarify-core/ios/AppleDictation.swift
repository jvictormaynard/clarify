import UIKit
import NaturalLanguage

// App-only preference. Transcription identity and output preferences are frozen
// by AudioSession; this setting never grants processing or account authority.
enum AppleDictationPreference {
  static let key = "clarify.dictation.appleReview"
  static var enabled: Bool { UserDefaults.standard.bool(forKey: key) }
  static func canApplyTone(policy: DictationPolicy, capabilities: ProcessingCapabilities) -> Bool {
    enabled && [.legacy, .natural, .clarity].contains(policy.mode) &&
      capabilities.explicitPolicy && capabilities.supports("cleanup_levels", "preserve")
  }

}
@MainActor enum AppleDictation {
  static var available: Bool {
    if #available(iOS 26.0, *) { return UIWritingToolsCoordinator.isWritingToolsAvailable }
    return false
  }
  static func snapshot() -> [String: Any] {
    ["enabled": AppleDictationPreference.enabled, "available": available,
      "message": L(available ? "Apple rewrites dictation automatically. No Apple editor is shown." :
        "Apple rewriting requires iOS 26 and available Apple Intelligence Writing Tools.")]
  }
  static func setEnabled(_ value: Bool) throws -> [String: Any] {
    guard !ClarifyAudioSession.shared.state.phase.busy, !busy, (!value || !ClarifyPrivateWritingToolsBridge.isBusy()) else {
      throw ClarifyError(L("Wait for the operation to finish before changing Apple rewriting."))
    }
    if value {
      let destination = ProcessingDestination.shared
      try validate(preferences: SharedState()?.outputPreferences() ?? OutputPreferences(),
        policy: DictationPolicyStore().read(scope: destination.historyScope ?? ""))
    }
    UserDefaults.standard.set(value, forKey: AppleDictationPreference.key)
    if !value, ClarifyAudioSession.shared.state.errorCode == "apple_dictation_foreground" {
      ClarifyAudioSession.shared.clearResult()
    }
    return snapshot()
  }
  static func validate(preferences: OutputPreferences, policy: DictationPolicy) throws {
    guard available else { throw ClarifyError(L("Apple rewriting requires iOS 26 and available Apple Intelligence Writing Tools.")) }
    guard [.default, .natural, .formal, .casual].contains(preferences.style) else {
      throw ClarifyError(L("Choose Default, Formal or Casual in Output settings for Apple rewriting."))
    }
    guard [.legacy, .natural, .clarity, .preserve, .light].contains(policy.mode) else {
      throw ClarifyError(L("Choose Improve clarity in Output settings for Apple rewriting."))
    }
    let capabilities = ProcessingDestination.shared.processingCapabilities
    guard capabilities.explicitPolicy, capabilities.supports("cleanup_levels", "preserve") else {
      throw ClarifyError(L("Refresh the transcription destination. Apple rewriting requires transcription without server rewriting."))
    }
  }

  private struct Pending {
    let id: String
    let task: Task<String, Error>
  }
  private static var pending: Pending?
  static var busy: Bool { pending != nil }

  static func rewrite(_ source: String, preferences: OutputPreferences, operationID: String) async throws -> String {
    try Task.checkCancellation()
    guard !busy else { throw ClarifyError(L("Wait for the operation to finish before changing Apple rewriting.")) }
    let task = Task { @MainActor () throws -> String in
      let report = try await ApplePrivateRewrite.report(source, preferences: preferences, operationID: operationID)
      try Task.checkCancellation()
      guard report.code == "ok", report.error.isEmpty else {
        throw ClarifyError(L(report.error) + " [" + report.code + "]", code: "apple_direct_" + report.code)
      }
      let text = report.result.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !text.isEmpty, text.utf8.count <= AppleRewriteEngine.maxOutputBytes else {
        throw ClarifyError(L("The result is empty or too long. The transcript was preserved."))
      }
      let sourceLanguage = NLLanguageRecognizer.dominantLanguage(for: source)?.rawValue
      let rewrittenLanguage = NLLanguageRecognizer.dominantLanguage(for: text)?.rawValue
      if let sourceLanguage, let rewrittenLanguage, sourceLanguage != rewrittenLanguage {
        throw ClarifyError(L("Apple changed the source language during rewriting. The transcript was preserved."))
      }
      guard preferences.language.rawValue != "auto", preferences.language.rawValue != rewrittenLanguage else { return text }
      guard let rewrittenLanguage else {
        throw ClarifyError(L("The source language could not be identified. The transcript was preserved."))
      }
      let translated = try await AppleRewriteEngine.translateInstalled(text, sourceLanguage: rewrittenLanguage,
        targetLanguage: preferences.language.rawValue)
      try Task.checkCancellation()
      guard !translated.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        translated.utf8.count <= AppleRewriteEngine.maxOutputBytes else {
        throw ClarifyError(L("The result is empty or too long. The transcript was preserved."))
      }
      return translated
    }
    pending = Pending(id: operationID, task: task)
    defer { if pending?.id == operationID { pending = nil } }
    return try await withTaskCancellationHandler(operation: {
      do { return try await task.value }
      catch is CancellationError {
        try Task.checkCancellation()
        throw ClarifyError(L("Apple processing was interrupted. The transcript was preserved."))
      }
    }, onCancel: { task.cancel() })
  }
  static func cancel(_ id: String?) {
    guard let owner = pending, id == nil || owner.id == id else { return }
    owner.task.cancel()
  }
  static func stopForAudioInterruption(_ id: String?) -> Bool {
    guard let owner = pending, owner.id == id else { return false }
    owner.task.cancel()
    return true
  }
}

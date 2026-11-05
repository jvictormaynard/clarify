import Foundation
#if canImport(NaturalLanguage)
import NaturalLanguage
#endif
#if canImport(FoundationModels)
import FoundationModels
#endif

// Admission and publication checks can run without loading a model.
struct AppleRewriteRuntime {
  var available: () -> Bool
  var supportsLanguage: (String) -> Bool
  var detectedLanguages: (String) -> [String]
  var generate: (_ instructions: String, _ source: String) async throws -> String
}

enum AppleRewriteEngine {
  // Prototype limits are byte bounds, not token estimates. Context exhaustion
  // still fails explicitly. No source is truncated or divided into chunks.
  static let maxInputBytes = 2_000
  static let maxOutputBytes = 8_000

  static func availability() -> [String: Any] {
    var snapshot: [String: Any] = ["available": false, "reason": "system_version",
      "message": L("Apple Intelligence requires iOS 26 or later and a compatible device."),
      "supportedLanguages": [String](), "maxInputBytes": maxInputBytes]
    #if canImport(FoundationModels)
    if #available(iOS 26.0, macOS 26.0, *) {
      let model = SystemLanguageModel.default
      let available = isAvailable(model)
      snapshot["available"] = available
      snapshot["reason"] = available ? "available" : "model_unavailable"
      snapshot["message"] = available ? L("Apple Intelligence is ready for a local rewrite.") :
        L("Enable Apple Intelligence in Settings and wait for its model download to finish.")
      if case .unavailable(.deviceNotEligible) = model.availability {
        snapshot["reason"] = "device_not_eligible"
        snapshot["message"] = L("This device does not support Apple Intelligence.")
      }
      snapshot["supportedLanguages"] = OutputLanguage.allCases.filter {
        $0 != .auto && model.supportsLocale(Locale(identifier: $0.rawValue))
      }.map(\.rawValue)
    }
    #endif
    return snapshot
  }

  static func rewrite(_ source: String, preferences: OutputPreferences,
    runtime: AppleRewriteRuntime? = nil) async throws -> String {
    try Task.checkCancellation()
    guard !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      throw failure("Enter text to rewrite.", "empty_input")
    }
    guard source.utf8.count <= maxInputBytes else {
      throw failure("Use a shorter text for the Apple Intelligence prototype.", "input_too_long")
    }
    guard let runtime = runtime ?? systemRuntime(), runtime.available() else {
      throw failure("Apple Intelligence is not available on this device.", "unavailable")
    }
    let detected = runtime.detectedLanguages(source)
    guard !detected.isEmpty else {
      throw failure("The source language could not be identified. Use a longer sample.", "language_undetermined")
    }
    // English is also the language of the canonical editorial instructions.
    let required = detected + ["en"] + (preferences.language == .auto ? [] : [preferences.language.rawValue])
    guard required.allSatisfy(runtime.supportsLanguage) else {
      throw failure("Apple Intelligence does not support a language in this request.", "unsupported_language")
    }
    let output = try await runtime.generate(RewritePrompt.instructions(preferences), RewritePrompt.source(source))
    try Task.checkCancellation()
    let result = output.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !result.isEmpty, result.utf8.count <= maxOutputBytes else {
      throw failure("Apple Intelligence did not return a complete rewrite. The source was preserved.", "invalid_result")
    }
    func normalized(_ value: String) -> String {
      value.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }
    let sourceSize = normalized(source).count
    if sourceSize >= 240, normalized(result).count * 4 < sourceSize {
      let sentences = source.replacingOccurrences(of: #"(?<=[.!?。！？])\s+"#,
        with: "\n", options: .regularExpression).components(separatedBy: "\n").map(normalized).filter { !$0.isEmpty }
      var seen = Set<String>()
      let unique = sentences.filter { seen.insert($0).inserted }
      guard unique.count < sentences.count, normalized(result) == unique.joined(separator: " ") else {
        throw failure("The rewrite removed too much text. The source was preserved.", "invalid_result")
      }
    }
    return result
  }

  private static func failure(_ message: String, _ code: String) -> ClarifyError {
    ClarifyError(message, code: "apple_rewrite_" + code)
  }

  private static func systemRuntime() -> AppleRewriteRuntime? {
    #if canImport(FoundationModels)
    if #available(iOS 26.0, macOS 26.0, *) {
      let model = SystemLanguageModel.default
      return AppleRewriteRuntime(available: { isAvailable(model) },
        supportsLanguage: { model.supportsLocale(Locale(identifier: $0)) },
        detectedLanguages: sourceLanguages,
        generate: { instructions, source in
          try Task.checkCancellation()
          // No tools or conversation history. A failed editorial instruction
          // cannot trigger an external action.
          let session = LanguageModelSession(model: model, instructions: instructions)
          do {
            let response = try await session.respond(to: source)
            try Task.checkCancellation()
            return response.content
          } catch is CancellationError { throw CancellationError() }
          catch let error as LanguageModelSession.GenerationError {
            switch error {
            case .exceededContextWindowSize:
              throw failure("The text exceeds the Apple Intelligence context limit. The source was preserved.", "context_limit")
            case .unsupportedLanguageOrLocale:
              throw failure("Apple Intelligence does not support a language in this request.", "unsupported_language")
            case .guardrailViolation, .refusal:
              throw failure("Apple Intelligence declined this text. The source was preserved.", "refused")
            case .assetsUnavailable:
              throw failure("Apple Intelligence is not available on this device.", "unavailable")
            case .rateLimited, .concurrentRequests:
              throw failure("Apple Intelligence is busy. Try again later.", "busy")
            default:
              throw failure("Apple Intelligence could not rewrite this text. The source was preserved.", "failed")
            }
          } catch {
            // Error bodies can contain the source. Return only bounded app copy.
            try Task.checkCancellation()
            throw failure("Apple Intelligence could not rewrite this text. The source was preserved.", "failed")
          }
        })
    }
    #endif
    return nil
  }

  #if canImport(FoundationModels)
  @available(iOS 26.0, macOS 26.0, *)
  private static func isAvailable(_ model: SystemLanguageModel) -> Bool {
    if case .available = model.availability { return true }
    return false
  }
  #endif

  private static func sourceLanguages(_ source: String) -> [String] {
    #if canImport(NaturalLanguage)
    var languages = Set<String>()
    func detect(_ value: String) {
      if let language = NLLanguageRecognizer.dominantLanguage(for: value) { languages.insert(language.rawValue) }
    }
    detect(source)
    // Sentence checks catch common mixed-language passages. Short fragments
    // remain heuristic; the framework can also reject them during generation.
    source.enumerateSubstrings(in: source.startIndex..<source.endIndex, options: .bySentences) { value, _, _, _ in
      if let value, value.unicodeScalars.filter({ CharacterSet.letters.contains($0) }).count >= 12 { detect(value) }
    }
    return languages.sorted()
    #else
    return []
    #endif
  }
}

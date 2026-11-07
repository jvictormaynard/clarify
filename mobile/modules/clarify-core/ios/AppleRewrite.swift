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
  var contextSize: Int = 4_096
  var countTokens: ((String) async throws -> Int)? = nil
  var responseTokenLimit: Int? = nil
  var waitForDeadline: (UInt64) async throws -> Void = { try await Task.sleep(nanoseconds: $0) }
}

enum AppleRewriteEngine {
  // Prototype limits are byte bounds, not token estimates. Context exhaustion
  // still fails explicitly. No source is truncated or divided into chunks.
  static let maxInputBytes = 2_000
  static let maxOutputBytes = 8_000
  // Same budgets as OpenWhispr localReasoning.ts / cleanupTranscript.ts.
  static let maxResponseTokens = 900
  static let maxSourceTokens = 720
  static let contextSafetyTokens = 300

  private static func exactTokens(_ text: String, runtime: AppleRewriteRuntime) async throws -> Int? {
    try Task.checkCancellation()
    if let count = runtime.countTokens {
      do {
        let value = try await count(text)
        try Task.checkCancellation()
        if value >= 0 { return value }
      } catch is CancellationError { throw CancellationError() }
      catch { /* Match the reference's estimate fallback when token counting fails. */ }
    }
    try Task.checkCancellation()
    return nil
  }

  private static func tokens(_ text: String, runtime: AppleRewriteRuntime) async throws -> Int {
    if let exact = try await exactTokens(text, runtime: runtime) { return exact }
    return Int(ceil(Double(text.utf16.count) / 3.5))
  }

  private static func response(instructions: String, prompt: String, timeoutMS: Int,
    runtime: AppleRewriteRuntime) async throws -> String {
    try await withThrowingTaskGroup(of: String.self) { group in
      group.addTask {
        let result = try await runtime.generate(instructions, prompt)
        try Task.checkCancellation()
        return result
      }
      group.addTask {
        try await runtime.waitForDeadline(UInt64(timeoutMS) * 1_000_000)
        try Task.checkCancellation()
        throw failure("Apple Intelligence took too long. The source was preserved.", "timeout")
      }
      defer { group.cancelAll() }
      guard let result = try await group.next() else { throw CancellationError() }
      return result
    }
  }

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
    let instructions = AppleRewritePrompt.instructions(preferences)
    let prompt = AppleRewritePrompt.source(source)
    let sourceTokens = try await tokens(source, runtime: runtime)
    let instructionTokens = try await tokens(instructions, runtime: runtime)
    let promptTokens = try await tokens(prompt, runtime: runtime)
    let inputBudget = max(256, runtime.contextSize - maxResponseTokens - contextSafetyTokens)
    guard sourceTokens <= maxSourceTokens, instructionTokens + promptTokens < inputBudget else {
      throw failure("The text exceeds the Apple Intelligence context limit. The source was preserved.", "context_limit")
    }
    try Task.checkCancellation()
    let timeoutMS = max(12_000, 5_000 + Int(ceil(Double(sourceTokens) / 25 * 1_000)))
    let output = try await response(instructions: instructions, prompt: prompt,
      timeoutMS: timeoutMS, runtime: runtime)
    try Task.checkCancellation()
    let result = output.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !result.isEmpty, result.utf8.count <= maxOutputBytes else {
      throw failure("Apple Intelligence did not return a complete rewrite. The source was preserved.", "invalid_result")
    }
    if let limit = runtime.responseTokenLimit {
      // Count the untrimmed response. An estimate cannot establish that a capped
      // generation completed; if exact counting fails, preserve the source.
      guard let responseTokens = try await exactTokens(output, runtime: runtime), responseTokens < limit else {
        throw failure("Apple Intelligence did not return a complete rewrite. The source was preserved.", "invalid_result")
      }
    }
    let leakedMarkers = ["BEGIN_SOURCE_TRANSCRIPT", "END_SOURCE_TRANSCRIPT", "<transcript>", "</transcript>"].contains { marker in
      result.range(of: marker, options: .caseInsensitive) != nil &&
        source.range(of: marker, options: .caseInsensitive) == nil
    }
    guard !leakedMarkers else {
      // Do not strip markers and silently present a contaminated answer as valid.
      throw failure("Apple Intelligence did not return a complete rewrite. The source was preserved.", "invalid_result")
    }
    func normalized(_ value: String) -> String {
      value.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }
    // An identical passage is not a translation when its detected language is
    // different. Limit this check to prose; names and identifiers may stay exact.
    if preferences.language != .auto, !detected.contains(preferences.language.rawValue),
      source.split(whereSeparator: { $0.isWhitespace }).count >= 8,
      normalized(source) == normalized(result) {
      throw failure("Apple Intelligence did not translate the text into the selected language. The source was preserved.", "untranslated_result")
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
      // Match the public OpenWhispr adapter: default model and default sampling.
      let model = SystemLanguageModel.default
      let responseTokenLimit: Int?
      if #available(iOS 26.4, macOS 26.4, *) { responseTokenLimit = maxResponseTokens }
      else { responseTokenLimit = nil }
      var runtime = AppleRewriteRuntime(available: { isAvailable(model) },
        supportsLanguage: { model.supportsLocale(Locale(identifier: $0)) },
        detectedLanguages: sourceLanguages,
        generate: { instructions, source in
          try Task.checkCancellation()
          // No tools or conversation history. A failed editorial instruction
          // cannot trigger an external action.
          let session = LanguageModelSession(model: model, instructions: instructions)
          do {
            let response = try await session.respond(to: source,
              options: GenerationOptions(maximumResponseTokens: responseTokenLimit))
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
        }, contextSize: model.contextSize, responseTokenLimit: responseTokenLimit)
      if #available(iOS 26.4, macOS 26.4, *) {
        runtime.countTokens = { text in try await model.tokenCount(for: text) }
      }
      return runtime
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

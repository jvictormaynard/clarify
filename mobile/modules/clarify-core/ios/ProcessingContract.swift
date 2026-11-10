import Foundation

extension ClarifyError {
  var recovery: String? { code.flatMap { (ProcessingContractData.value["errors"] as? [String: String])?[$0] } }
}

struct ProcessingCapabilities {
  let value: [String: Any]
  static let unavailable = Self(value: [:])
  init(value: [String: Any]) { self.value = value }
  init(_ raw: Any?) throws {
    guard let raw else { self = .unavailable; return }
    guard let value = raw as? [String: Any], ComputerJSON.integer(value["schema_version"]) == 1 else {
      throw ComputerFailure.invalidResponse
    }
    let known = ProcessingContractData.value
    for key in ["output_languages", "writing_styles", "cleanup_levels"] {
      guard let values = value[key] as? [String], let allowed = known[key] as? [String],
        values.count <= allowed.count, Set(values).count == values.count,
        values.allSatisfy({ allowed.contains($0) }) else { throw ComputerFailure.invalidResponse }
    }
    for key in ["dictation_actions", "explicit_dictation_policy"] {
      guard ComputerJSON.boolean(value[key]) != nil else { throw ComputerFailure.invalidResponse }
    }
    if let rawEditing = value["dictation_editing"] {
      guard let editing = rawEditing as? [String: Any], Set(editing.keys) == Set(["legacy", "natural", "clarity", "action", "legacy_translated", "natural_translated"]),
        editing.values.allSatisfy({ ComputerJSON.boolean($0) != nil }) else { throw ComputerFailure.invalidResponse }
    }
    for key in ["text_input_bytes", "text_output_bytes"] {
      guard let bound = ComputerJSON.integer(value[key]), bound > 0, bound <= 64_000 else { throw ComputerFailure.invalidResponse }
    }
    self.value = value
  }
  var available: Bool { !value.isEmpty }
  func supports(_ key: String, _ option: String) -> Bool { (value[key] as? [String])?.contains(option) == true }
  var dictationActions: Bool { ComputerJSON.boolean(value["dictation_actions"]) == true }
  var explicitPolicy: Bool { ComputerJSON.boolean(value["explicit_dictation_policy"]) == true }
  func validate(_ preferences: OutputPreferences) throws {
    guard !available || (supports("output_languages", preferences.language.rawValue) &&
      (preferences.style == .default || supports("writing_styles", preferences.style.rawValue))) else {
      throw ClarifyError(L("Atualize o serviço para usar estas preferências de saída."), code: "output_preferences_unsupported")
    }
  }

}

enum DictationMode: String, Codable { case legacy, natural, preserve, light, clarity, action }

// App-only settings. The keyboard never receives account authority or action prompts.
struct DictationPolicy: Codable, Equatable {
  var mode: DictationMode = .legacy
  var actionID = ""
  var actionRevision = ""
  var language: OutputLanguage = .auto
  static let legacy = Self(mode: .legacy)
  var snapshot: [String: String] {
    ["mode": mode.rawValue, "actionID": actionID, "actionRevision": actionRevision, "language": language.rawValue]
  }
  func fields(capabilities: ProcessingCapabilities, catalog: TextActionCatalog, computer: Bool) throws -> [String: Any] {
    if mode == .legacy { return [:] }
    guard capabilities.explicitPolicy else {
      // Older account services already use their standard hosted policy.
      if mode == .natural && !computer { return [:] }
      throw ClarifyError(L("Atualize o serviço para usar estas preferências de saída."), code: "output_preferences_unsupported")
    }
    if mode == .natural { return computer ? ["dictation_policy": "natural"] : [:] }
    if mode != .action {
      guard capabilities.supports("cleanup_levels", mode.rawValue) else { throw ComputerFailure.notReady }
      return ["cleanup_level": mode.rawValue]
    }
    guard capabilities.dictationActions, let revision = TextActionDescriptor.wireRevision(actionRevision),
      let action = catalog.actions.first(where: { $0.id == actionID && $0.revision == actionRevision }),
      action.enabled, action.ready, action.kind != "translation" || language != .auto else {
      throw ClarifyError(L("A ação mudou. Atualize as ações."), code: "text_action_stale")
    }
    return ["text_action_id": actionID, "text_action_revision": revision, "text_action_language": language.rawValue]
  }
  func canApplyTone(capabilities: ProcessingCapabilities, catalog: TextActionCatalog, computer: Bool, outputLanguage: OutputLanguage = .auto) -> Bool {
    guard ![.preserve, .light].contains(mode), capabilities.supports("cleanup_levels", "clarity") else { return false }
    let editing = capabilities.value["dictation_editing"] as? [String: Any]
    if computer && editing == nil { return false }
    let readiness = outputLanguage != .auto && [.legacy, .natural].contains(mode) ? mode.rawValue + "_translated" : mode.rawValue
    if let editing, ComputerJSON.boolean(editing[readiness]) != true { return false }
    if mode == .action {
      return catalog.actions.contains { $0.id == actionID && $0.revision == actionRevision && $0.enabled && $0.ready }
    }
    return true
  }
  static func selectableModes(capabilities: ProcessingCapabilities) -> [String] {
    var modes = ["clarity", "preserve"].filter {
      capabilities.explicitPolicy && capabilities.supports("cleanup_levels", $0)
    }
    if capabilities.dictationActions { modes.append("action") }
    return modes
  }
  func frozenPreferences(_ saved: OutputPreferences, capabilities: ProcessingCapabilities,
    catalog: TextActionCatalog, computer: Bool) -> OutputPreferences {
    if [.preserve, .light].contains(mode) { return OutputPreferences() }
    // Services without the optional readiness map keep their existing request behavior.
    guard capabilities.value["dictation_editing"] != nil else { return saved }
    return canApplyTone(capabilities: capabilities, catalog: catalog, computer: computer, outputLanguage: saved.language)
      ? saved : OutputPreferences(language: saved.language)
  }
  func accepts(_ raw: [String: Any]) -> Bool {
    if mode == .action {
      return raw["text_action_id"] as? String == actionID &&
        ComputerJSON.integer(raw["text_action_revision"]).map({ String($0) }) == actionRevision
    }
    guard [.preserve, .light, .clarity].contains(mode) else { return true }
    guard raw["cleanup_level_requested"] as? String == mode.rawValue,
      let applied = raw["cleanup_level_applied"] as? String else { return false }
    return applied == mode.rawValue || (applied == "preserve" && (mode == .clarity || raw["rewritten"] as? Bool == false))
  }
}

final class DictationPolicyStore {
  private let defaults: UserDefaults
  init(defaults: UserDefaults = .standard) { self.defaults = defaults }
  private func key(_ scope: String) -> String { "clarify.dictation.policy|" + scope }
  func read(scope: String) -> DictationPolicy {
    guard let data = defaults.data(forKey: key(scope)), data.count <= 2048,
      let policy = try? JSONDecoder().decode(DictationPolicy.self, from: data) else {
      if defaults.object(forKey: key(scope)) == nil, defaults.bool(forKey: "clarify.textUX.fresh") {
        return DictationPolicy(mode: .clarity)
      }
      return .legacy
    }
    return policy
  }
  func save(_ policy: DictationPolicy, scope: String) throws {
    defaults.set(try JSONEncoder().encode(policy), forKey: key(scope))
  }
}

// Extreme-loss guard, not semantic validation. Count characters across scripts.
enum TextRetention {
  static func accepts(source: String, output: String) -> Bool {
    func normalize(_ value: String) -> String {
      value.folding(options: [.caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
        .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }
    let original = normalize(source), result = normalize(output)
    guard !result.isEmpty else { return false }
    guard original.unicodeScalars.count >= 240, result.unicodeScalars.count * 4 < original.unicodeScalars.count else { return true }
    // Same sentence boundaries as the shared Python preservation policy.
    let sentences = source.replacingOccurrences(of: #"(?<=[.!?。！？])\s+|\n+"#,
      with: "\n", options: .regularExpression).components(separatedBy: "\n")
      .map(normalize).filter { !$0.isEmpty }
    var seen = Set<String>()
    let unique = sentences.filter { seen.insert($0).inserted }
    return unique.count < sentences.count && unique.joined(separator: " ") == result
  }
}

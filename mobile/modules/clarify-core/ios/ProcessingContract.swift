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
      let policy = try? JSONDecoder().decode(DictationPolicy.self, from: data) else { return DictationPolicy() }
    return policy
  }
  func save(_ policy: DictationPolicy, scope: String) throws {
    defaults.set(try JSONEncoder().encode(policy), forKey: key(scope))
  }
}

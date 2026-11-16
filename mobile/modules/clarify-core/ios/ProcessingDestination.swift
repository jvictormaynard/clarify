import Foundation

struct ProcessingCapture: Equatable {
  let scope: String?
  let context: String
}
struct ProcessingDictation {
  let transcript: String
  let text: String
  let rewritten: Bool
  let successful: Bool
  var outputPreferenceFailed = false
}
struct ProcessingText {
  let text: String
  let successful: Bool
  var outputPreferenceFailed = false
  var rewritten: Bool { successful }
}

struct PreparedTextOperation {
  let owner: ProcessingCapture
  let action: String
  let language: String
  let savedAction: TextActionDescriptor?
  let preferences: OutputPreferences
  var accountIdentity: TextAccountIdentity? = nil
}

// Explicit routing for the containing app. CloudAccount owns account authentication and sync. ComputerConnection owns only the computer protocol.
final class ProcessingDestination {
  static let shared = ProcessingDestination()
  private let defaults: UserDefaults
  private let computer: ComputerConnection
  private let account: CloudAccount
  private var revision = UUID().uuidString
  private(set) var computerMode: Bool
  init(defaults: UserDefaults = .standard, computer: ComputerConnection = .shared, account: CloudAccount = .shared) {
    self.defaults = defaults; self.computer = computer; self.account = account
    computerMode = true
    defaults.set("computer", forKey: "clarify.processing.destination")
  }
  var configured: Bool { computer.configured }
  var isBusy: Bool { computer.busy }
  var textStartBlocked: Bool { computer.busy }
  func captureTextIdentity() -> TextAccountIdentity? { nil }
  var textActions: TextActionCatalog { computer.textActions }
  var processingCapabilities: ProcessingCapabilities { computer.processingCapabilities }
  func dictationFields(_ policy: DictationPolicy) throws -> [String: Any] {
    try policy.fields(capabilities: processingCapabilities, catalog: textActions, computer: computerMode)
  }
  var outputPreferencesSupported: Bool { computer.outputPreferencesSupported }
  var legacyRewriteReady: Bool { computer.isReady(for: "rewrite") }
  var legacyTranslateReady: Bool { computer.isReady(for: "translate") }
  var historyScope: String? { computer.scope }
  var historyContext: String { revision + "|computer|\(computer.generation)" }
  func captureHistory() -> ProcessingCapture { ProcessingCapture(scope: historyScope, context: historyContext) }
  func acceptsHistory(_ capture: ProcessingCapture) -> Bool { configured && capture == captureHistory() }
  @MainActor func select(_ mode: String) throws {
    guard mode == "computer", !account.isBusy, !computer.busy else { throw ComputerFailure.busy }
    computer.suspend(); account.clearTextCapabilities(); computerMode = mode == "computer"; revision = UUID().uuidString
    defaults.set(mode, forKey: "clarify.processing.destination")
  }
  func snapshot() -> [String: Any] {
    var result = account.snapshot()
    result["mode"] = "computer"
    result["processingConfigured"] = configured
    result["computer"] = computer.snapshot()
    result["historyContext"] = historyContext
    result["historyAccount"] = false
    result.merge(textActions.snapshot) { _, new in new }
    result["outputPreferencesSupported"] = outputPreferencesSupported
    result["processingContract"] = processingCapabilities.value
    result["busy"] = computer.busy || account.isBusy
    return result
  }
  @MainActor func automaticRefresh(_ library: LocalLibrary) async throws -> Bool {
    let changed = (try? await account.command("auto", value: "", library: library)) ?? false
    if computer.configured, !computer.busy { try await computer.refresh() }
    return changed
  }
  @MainActor func authorizeComputerConnection(_ action: String, value: String, library: LocalLibrary) async throws {
    guard computerMode, !computer.busy else { throw ComputerFailure.busy }
    if action == "connect" {
      guard account.configured else { throw ComputerFailure.authentication }
      try await computer.resumeRemoteRegistration(); return
    }
    let capture = captureHistory()
    _ = try await account.command(action, value: value, library: library, connectionOnly: true)
    try Task.checkCancellation()
    guard computerMode, capture == captureHistory() else { throw CancellationError() }
    if account.configured && ["confirm", "social", "refresh"].contains(action) {
      try await computer.resumeRemoteRegistration()
    }
  }
  @MainActor func syncHistory(_ library: LocalLibrary, force: Bool = false) async -> Bool {
    return await account.syncHistory(library, force: force)
  }
  @MainActor func prepareText(_ action: String, actionID: String? = nil, revision: String? = nil,
    language: String, context: String, preferences: OutputPreferences,
    accountIdentity: TextAccountIdentity? = nil) async throws -> PreparedTextOperation {
    guard configured, context == historyContext, ["rewrite", "translate", "text_action"].contains(action),
      OutputLanguage(rawValue: language) != nil else { throw ComputerFailure.notReady }
    let owner = captureHistory()
    let identity = accountIdentity ?? captureTextIdentity()
    if let identity, !account.acceptsTextIdentity(identity) { throw CancellationError() }
    if computerMode { try await computer.refresh() }

    try Task.checkCancellation()
    guard acceptsHistory(owner), context == historyContext else { throw CancellationError() }
    if let identity, !account.acceptsTextIdentity(identity) { throw CancellationError() }
    let saved: TextActionDescriptor?
    if action == "text_action" {
      guard let actionID, let revision else { throw ComputerFailure.invalidResponse }
      saved = try textActions.resolve(actionID, revision: revision, language: preferences.language.rawValue)
    } else {
      // Only an advertised old service permits fixed-action fallback. An empty
      // or failed saved catalog cannot silently enable a different definition.
      guard textActions.status == .unsupported,
        (action == "rewrite" ? legacyRewriteReady : legacyTranslateReady) else { throw ComputerFailure.notReady }
      saved = nil
    }
    _ = try preferences.requestFields(supported: outputPreferencesSupported, dictation: false)
    return PreparedTextOperation(owner: owner, action: action, language: preferences.language.rawValue,
      savedAction: saved, preferences: preferences, accountIdentity: identity)
  }
  @MainActor func withActivation(prepare: @MainActor () async throws -> Void, activate: @MainActor () throws -> Void) async throws {
    let capture = captureHistory()
    if computerMode {
      guard configured else { throw ComputerFailure.authentication }
      try await computer.refresh()
      guard computer.actionReadiness.available || computer.textActions.actions.contains(where: { $0.enabled && $0.ready }) else { throw ComputerFailure.notReady }
      try await prepare()
      try Task.checkCancellation()
      guard computerMode, acceptsHistory(capture) else { throw CancellationError() }
      try activate()
    } else { throw ComputerFailure.notReady }
  }
  @MainActor func prepareLive(_ operationID: String, preferences: OutputPreferences,
    policy: DictationPolicy, partial: @escaping (String) -> Void) throws -> ComputerLiveCapture? {
    guard computerMode, configured else { throw ComputerFailure.notReady }
    return try computer.prepareLive(operationID, preferences: preferences, policy: policy, partial: partial)
  }
  @MainActor func finishLive(_ capture: ComputerLiveCapture, owner: ProcessingCapture) async throws -> ProcessingDictation {
    guard acceptsHistory(owner) else { capture.cancel(); throw CancellationError() }
    let result = try await capture.result()
    try Task.checkCancellation()
    guard acceptsHistory(owner), !result.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw CancellationError() }
    return ProcessingDictation(transcript: result.transcript, text: result.text, rewritten: result.rewritten,
      successful: result.successful, outputPreferenceFailed: result.outputPreferenceFailed)
  }
  @MainActor func dictate(_ url: URL, operationID: String, library: LocalLibrary,
    preferences: OutputPreferences = OutputPreferences(), policy: DictationPolicy = .legacy) async throws -> ProcessingDictation {
    let capture = captureHistory()
    let wav = try await ComputerAudio.convert(url)
    guard computerMode, acceptsHistory(capture) else { throw CancellationError() }
    let result = try await computer.process(operationID, wav: wav, language: "auto", preferences: preferences, policy: policy)
    guard computerMode, acceptsHistory(capture), !result.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw CancellationError() }
    return ProcessingDictation(transcript: result.transcript, text: result.text, rewritten: result.rewritten, successful: result.successful,
      outputPreferenceFailed: result.outputPreferenceFailed)
  }
  @MainActor func processText(_ operationID: String, prepared: PreparedTextOperation, text: String) async throws -> ProcessingText {
    let capture = prepared.owner
    guard acceptsHistory(capture) else { throw CancellationError() }
    guard configured else { throw ComputerFailure.notReady }
    let result: ProcessingText
    if computerMode {
      let response = try await computer.process(operationID, action: prepared.action, text: text, language: prepared.language,
        savedAction: prepared.savedAction, preferences: prepared.preferences)
      result = ProcessingText(text: response.text, successful: response.successful, outputPreferenceFailed: response.outputPreferenceFailed)
    } else { throw ComputerFailure.notReady }
    try Task.checkCancellation()
    guard acceptsHistory(capture) else { throw CancellationError() }
    return result
  }
}

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

// Explicit routing for the containing app. CloudAccount continues to own hosted
// security and sync. ComputerConnection owns only the computer protocol.
final class ProcessingDestination {
  static let shared = ProcessingDestination()
  private let defaults: UserDefaults
  private let computer: ComputerConnection
  private let account: CloudAccount
  private var revision = UUID().uuidString
  private(set) var computerMode: Bool
  init(defaults: UserDefaults = .standard, computer: ComputerConnection = .shared, account: CloudAccount = .shared) {
    self.defaults = defaults; self.computer = computer; self.account = account
    computerMode = defaults.string(forKey: "clarify.processing.destination") == "computer"
  }
  var configured: Bool { computerMode ? computer.configured : account.configured }
  var isBusy: Bool { computerMode ? computer.busy : account.isBusy }
  var textActions: TextActionCatalog { computerMode ? computer.textActions : account.textActions }
  var outputPreferencesSupported: Bool { computerMode ? computer.outputPreferencesSupported : account.outputPreferencesSupported }
  var legacyRewriteReady: Bool { computerMode ? computer.isReady(for: "rewrite") : account.configured }
  var legacyTranslateReady: Bool { computerMode ? computer.isReady(for: "translate") : account.configured }
  var historyScope: String? { computerMode ? computer.scope : account.historyScope }
  var historyContext: String { revision + (computerMode ? "|computer|\(computer.generation)" : "|hosted|" + account.historyContext) }
  func captureHistory() -> ProcessingCapture { ProcessingCapture(scope: historyScope, context: historyContext) }
  func acceptsHistory(_ capture: ProcessingCapture) -> Bool { configured && capture == captureHistory() }
  @MainActor func select(_ mode: String) throws {
    guard ["hosted", "computer"].contains(mode), !account.isBusy, !computer.busy else { throw ComputerFailure.busy }
    computer.suspend(); account.clearTextCapabilities(); computerMode = mode == "computer"; revision = UUID().uuidString
    defaults.set(mode, forKey: "clarify.processing.destination")
  }
  func snapshot() -> [String: Any] {
    var result = account.snapshot()
    result["mode"] = computerMode ? "computer" : "hosted"
    result["processingConfigured"] = configured
    result["computer"] = computer.snapshot()
    result["historyContext"] = historyContext
    result["historyAccount"] = !computerMode && account.historyScope != nil
    result.merge(textActions.snapshot) { _, new in new }
    result["outputPreferencesSupported"] = outputPreferencesSupported
    if computerMode { result["syncEnabled"] = false; result["busy"] = computer.busy; result["error"] = ""; result["dictionaryConflict"] = false }
    return result
  }
  @MainActor func automaticRefresh(_ library: LocalLibrary) async throws -> Bool {
    if computerMode {
      if computer.configured, !computer.busy { try await computer.refresh() }
      return false
    }
    return try await account.command("auto", value: "", library: library)
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
    guard computerMode, acceptsHistory(capture) else { throw CancellationError() }
    if account.configured && ["confirm", "social", "refresh"].contains(action) {
      try await computer.resumeRemoteRegistration()
    }
  }
  @MainActor func syncHistory(_ library: LocalLibrary, force: Bool = false) async -> Bool {
    guard !computerMode else { return false }
    return await account.syncHistory(library, force: force)
  }
  @MainActor func withComputerText(_ action: String, context: String, start: @MainActor () throws -> Void) async throws {
    guard ["rewrite", "translate"].contains(action) else { throw ComputerFailure.invalidResponse }
    guard computerMode, configured, context == historyContext else { throw ComputerFailure.notReady }
    let capture = captureHistory()
    try await computer.refresh()
    try Task.checkCancellation()
    guard computerMode, acceptsHistory(capture), context == historyContext else { throw CancellationError() }
    guard computer.isReady(for: action) else { throw ComputerFailure.notReady }
    try start()
  }
  @MainActor func prepareText(_ action: String, actionID: String? = nil, revision: String? = nil,
    language: String, context: String, preferences: OutputPreferences) async throws -> PreparedTextOperation {
    guard configured, context == historyContext, ["rewrite", "translate", "text_action"].contains(action),
      OutputLanguage(rawValue: language) != nil, action != "translate" || language != "auto" else { throw ComputerFailure.notReady }
    let owner = captureHistory()
    if computerMode { try await computer.refresh() }
    else { try await account.refreshTextActions() }
    try Task.checkCancellation()
    guard acceptsHistory(owner), context == historyContext else { throw CancellationError() }
    let saved: TextActionDescriptor?
    if action == "text_action" {
      guard let actionID, let revision else { throw ComputerFailure.invalidResponse }
      saved = try textActions.resolve(actionID, revision: revision, language: language)
    } else {
      // Only an advertised old service permits fixed-action fallback. An empty
      // or failed saved catalog cannot silently enable a different definition.
      guard textActions.status == .unsupported,
        (action == "rewrite" ? legacyRewriteReady : legacyTranslateReady) else { throw ComputerFailure.notReady }
      saved = nil
    }
    _ = try preferences.requestFields(supported: outputPreferencesSupported, dictation: false)
    return PreparedTextOperation(owner: owner, action: action, language: action == "rewrite" || saved?.kind == "rewrite" ? "auto" : language,
      savedAction: saved, preferences: preferences, accountIdentity: computerMode ? nil : account.captureTextIdentity())
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
    } else {
      try await account.withActivationAccount(prepare: prepare, activate: {
        guard !self.computerMode, self.acceptsHistory(capture) else { throw CancellationError() }
        try activate()
      })
    }
  }
  @MainActor func dictate(_ url: URL, operationID: String, library: LocalLibrary,
    preferences: OutputPreferences = OutputPreferences()) async throws -> ProcessingDictation {
    if !computerMode {
      let result = try await account.dictate(url, operationID: operationID, library: library, preferences: preferences)
      return ProcessingDictation(transcript: result.transcript, text: result.text, rewritten: result.rewritten, successful: result.successful,
        outputPreferenceFailed: result.outputPreferenceFailed)
    }
    let capture = captureHistory()
    let wav = try await ComputerAudio.convert(url)
    guard computerMode, acceptsHistory(capture) else { throw CancellationError() }
    let result = try await computer.process(operationID, wav: wav, language: "auto", preferences: preferences)
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
    } else {
      if let identity = prepared.accountIdentity, !account.acceptsTextIdentity(identity) { throw CancellationError() }
      result = try await account.processText(operationID, action: prepared.action, text: text, language: prepared.language,
        savedAction: prepared.savedAction, preferences: prepared.preferences)
    }
    try Task.checkCancellation()
    guard acceptsHistory(capture) else { throw CancellationError() }
    return result
  }
  // Retain the original internal legacy entrypoint for existing callers/tests.
  @MainActor func processText(_ operationID: String, action: String, text: String, language: String) async throws -> ProcessingText {
    try await processText(operationID, prepared: PreparedTextOperation(owner: captureHistory(), action: action,
      language: language, savedAction: nil, preferences: OutputPreferences()), text: text)
  }
}

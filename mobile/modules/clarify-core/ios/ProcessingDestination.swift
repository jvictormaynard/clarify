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
}
struct ProcessingText {
  let text: String
  let successful: Bool
  var rewritten: Bool { successful }
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
  var historyScope: String? { computerMode ? computer.scope : account.historyScope }
  var historyContext: String { revision + (computerMode ? "|computer|\(computer.generation)" : "|hosted|" + account.historyContext) }
  func captureHistory() -> ProcessingCapture { ProcessingCapture(scope: historyScope, context: historyContext) }
  func acceptsHistory(_ capture: ProcessingCapture) -> Bool { configured && capture == captureHistory() }
  @MainActor func select(_ mode: String) throws {
    guard ["hosted", "computer"].contains(mode), !account.isBusy, !computer.busy else { throw ComputerFailure.busy }
    computer.suspend(); computerMode = mode == "computer"; revision = UUID().uuidString
    defaults.set(mode, forKey: "clarify.processing.destination")
  }
  func snapshot() -> [String: Any] {
    var result = account.snapshot()
    result["mode"] = computerMode ? "computer" : "hosted"
    result["processingConfigured"] = configured
    result["computer"] = computer.snapshot()
    result["historyContext"] = historyContext
    result["historyAccount"] = !computerMode && account.historyScope != nil
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
  @MainActor func withActivation(prepare: @MainActor () async throws -> Void, activate: @MainActor () throws -> Void) async throws {
    let capture = captureHistory()
    if computerMode {
      guard configured else { throw ComputerFailure.authentication }
      try await computer.refresh()
      guard computer.actionReadiness.available else { throw ComputerFailure.notReady }
      try await prepare()
      try Task.checkCancellation()
      guard computerMode, acceptsHistory(capture), computer.actionReadiness.available else { throw CancellationError() }
      try activate()
    } else {
      try await account.withActivationAccount(prepare: prepare, activate: {
        guard !self.computerMode, self.acceptsHistory(capture) else { throw CancellationError() }
        try activate()
      })
    }
  }
  @MainActor func dictate(_ url: URL, operationID: String, library: LocalLibrary) async throws -> ProcessingDictation {
    if !computerMode {
      let result = try await account.dictate(url, operationID: operationID, library: library)
      return ProcessingDictation(transcript: result.transcript, text: result.text, rewritten: result.rewritten, successful: result.successful)
    }
    let capture = captureHistory()
    let wav = try await ComputerAudio.convert(url)
    guard computerMode, acceptsHistory(capture) else { throw CancellationError() }
    let result = try await computer.process(operationID, wav: wav, language: "auto")
    guard computerMode, acceptsHistory(capture), !result.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw CancellationError() }
    return ProcessingDictation(transcript: result.transcript, text: result.text, rewritten: result.rewritten, successful: result.successful)
  }
  @MainActor func processText(_ operationID: String, action: String, text: String, language: String) async throws -> ProcessingText {
    let capture = captureHistory()
    guard configured else { throw ComputerFailure.notReady }
    let result: ProcessingText
    if computerMode {
      guard computer.isReady(for: action) else { throw ComputerFailure.notReady }
      let response = try await computer.process(operationID, action: action, text: text, language: language)
      result = ProcessingText(text: response.text, successful: response.successful)
    } else {
      result = try await account.processText(operationID, action: action, text: text, language: language)
    }
    try Task.checkCancellation()
    guard acceptsHistory(capture) else { throw CancellationError() }
    return result
  }
}

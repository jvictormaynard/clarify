import Foundation

enum OutputLanguage: String, Codable, CaseIterable { case auto, pt, en, es, de, ru }
enum OutputStyle: String, Codable, CaseIterable { case `default`, formal, casual, very_casual, natural, informal, organized }

struct OutputPreferences: Codable, Equatable {
  var language: OutputLanguage = .auto
  var style: OutputStyle = .default
  var snapshot: [String: String] { ["language": language.rawValue, "style": style.rawValue] }
  func requestFields(supported: Bool, dictation: Bool) throws -> [String: String] {
    var fields: [String: String] = [:]
    if dictation, language != .auto { fields["output_language"] = language.rawValue }
    if style != .default { fields["writing_style"] = style.rawValue }
    guard fields.isEmpty || supported else {
      throw ClarifyError(L("Atualize o serviço para usar estas preferências de saída."), code: "output_preferences_unsupported")
    }
    return fields
  }
  func applied(in raw: [String: Any], dictation: Bool) -> Bool {
    let explicit = (dictation && language != .auto ? [("output_language", language.rawValue)] : []) +
      (style != .default ? [("writing_style", style.rawValue)] : [])
    if explicit.contains(where: { raw[$0.0 + "_status"] as? String == "standalone" }) {
      return dictation && raw["rewritten"] as? Bool == false && explicit.allSatisfy {
        raw[$0.0 + "_requested"] as? String == $0.1 && raw[$0.0 + "_status"] as? String == "standalone" &&
          (raw[$0.0 + "_applied"] == nil || raw[$0.0 + "_applied"] is NSNull)
      }
    }
    func applied(_ prefix: String, _ requested: String) -> Bool {
      guard raw[prefix + "_requested"] as? String == requested else { return false }
      let status = raw[prefix + "_status"] as? String
      return status == "applied" && raw[prefix + "_applied"] as? String == requested
    }
    return (!dictation || language == .auto || applied("output_language", language.rawValue)) &&
      (style == .default || applied("writing_style", style.rawValue))
  }
  func hasDictationFallback(in raw: [String: Any]) -> Bool {
    let explicit = (language != .auto ? [("output_language", language.rawValue)] : []) +
      (style != .default ? [("writing_style", style.rawValue)] : [])
    let statuses = explicit.compactMap { raw[$0.0 + "_status"] as? String }
    // The destination expands inline snippets before its one refinement step.
    // Keep that bounded fallback only when every requested field consistently
    // reports controlled failure or disabled refinement, with no applied value.
    return !explicit.isEmpty && statuses.count == explicit.count && Set(statuses).count == 1 &&
      statuses.allSatisfy { ["refinement_failed", "refinement_not_allowed"].contains($0) } &&
      explicit.allSatisfy { raw[$0.0 + "_requested"] as? String == $0.1 && raw[$0.0 + "_applied"] is NSNull }
  }
  static let unappliedMessage = "A preferência de saída não foi aplicada. O texto original foi preservado."
}

// Descriptors are the only saved-action data permitted in the App Group.
// Revisions use decimal strings across JavaScript, and Int64 on the wire.
struct TextActionDescriptor: Codable, Equatable {
  let id: String
  let revision: String
  let name: String
  let kind: String
  let enabled: Bool
  let ready: Bool
  static func validID(_ value: String) -> Bool {
    !value.isEmpty && value.utf8.count <= 64 && value.utf8.allSatisfy {
      (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95
    }
  }
  static func wireRevision(_ value: String) -> Int64? {
    guard let number = Int64(value), number > 0, String(number) == value else { return nil }
    return number
  }
  var valid: Bool {
    Self.validID(id) && Self.wireRevision(revision) != nil && !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && name.count <= 80 &&
      name.utf8.count <= 320 && !name.unicodeScalars.contains { [.control, .format, .surrogate, .privateUse, .unassigned].contains($0.properties.generalCategory) } &&
      ["rewrite", "translation", "custom"].contains(kind)
  }
  var snapshot: [String: Any] { ["id": id, "revision": revision, "name": name, "kind": kind, "enabled": enabled, "ready": ready] }
}

struct TextActionCatalog: Codable, Equatable {
  enum Status: String, Codable { case unavailable, loading, ready, unsupported }
  let status: Status
  let actions: [TextActionDescriptor]
  static let unavailable = Self(status: .unavailable, actions: [])
  static let loading = Self(status: .loading, actions: [])
  static let unsupported = Self(status: .unsupported, actions: [])
  var supported: Bool { status == .ready }
  var valid: Bool { actions.count <= 64 && actions.allSatisfy(\.valid) && Set(actions.map(\.id)).count == actions.count && (status == .ready || actions.isEmpty) }
  var snapshot: [String: Any] { ["textActionsSupported": supported, "textActionsStatus": status.rawValue, "textActions": actions.map(\.snapshot)] }
}

enum DictationPhase: String, Codable {
  case idle, recording, locked, transcribing, rewriting, ready, error
  var busy: Bool { [.recording, .locked, .transcribing, .rewriting].contains(self) }
}

struct DictationSnapshot: Codable {
  var sessionActive = false
  var heartbeat = Date().timeIntervalSince1970
  var phase = DictationPhase.idle
  var operationID: String?
  var text: String?
  var message: String?
  var errorCode: String?
  var errorPhase: String?
  var errorStatus: Int?
  var configured = false
  var computerMode = false
  var processingContext: String?
  var textOperation = false
  var textActions = TextActionCatalog.unavailable
  var legacyRewriteReady = false
  var legacyTranslateReady = false
  var outputPreferencesSupported = false
  var libraryRevision = 0
  var isLive: Bool { sessionActive && Date().timeIntervalSince1970 - heartbeat < 3 }
  func textResult(for id: String, context: String, currentContext: String) -> String? {
    guard !context.isEmpty, context == currentContext, processingContext == context,
      operationID == id, textOperation, phase == .ready,
      let text, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
    return text
  }
  private enum CodingKeys: String, CodingKey { case sessionActive, heartbeat, phase, operationID, text, message, errorCode, errorPhase, errorStatus, configured, libraryRevision, computerMode, processingContext, textOperation, textActions, legacyRewriteReady, legacyTranslateReady, outputPreferencesSupported }
  init() {}
  init(from decoder: Decoder) throws {
    let values = try decoder.container(keyedBy: CodingKeys.self)
    sessionActive = try values.decode(Bool.self, forKey: .sessionActive)
    heartbeat = try values.decode(TimeInterval.self, forKey: .heartbeat)
    phase = try values.decode(DictationPhase.self, forKey: .phase)
    operationID = try values.decodeIfPresent(String.self, forKey: .operationID)
    text = try values.decodeIfPresent(String.self, forKey: .text)
    message = try values.decodeIfPresent(String.self, forKey: .message)
    errorCode = try values.decodeIfPresent(String.self, forKey: .errorCode)
    errorPhase = try values.decodeIfPresent(String.self, forKey: .errorPhase)
    errorStatus = try values.decodeIfPresent(Int.self, forKey: .errorStatus)
    configured = try values.decode(Bool.self, forKey: .configured)
    computerMode = try values.decodeIfPresent(Bool.self, forKey: .computerMode) ?? false
    processingContext = try values.decodeIfPresent(String.self, forKey: .processingContext)
    textOperation = try values.decodeIfPresent(Bool.self, forKey: .textOperation) ?? false
    textActions = try values.decodeIfPresent(TextActionCatalog.self, forKey: .textActions) ?? .unavailable
    if !textActions.valid { textActions = .unavailable }
    legacyRewriteReady = try values.decodeIfPresent(Bool.self, forKey: .legacyRewriteReady) ?? false
    legacyTranslateReady = try values.decodeIfPresent(Bool.self, forKey: .legacyTranslateReady) ?? false
    outputPreferencesSupported = try values.decodeIfPresent(Bool.self, forKey: .outputPreferencesSupported) ?? false
    libraryRevision = try values.decodeIfPresent(Int.self, forKey: .libraryRevision) ?? 0
  }
}

struct DictationCommand: Codable {
  let commandID: String
  let operationID: String
  let action: String
  let createdAt: TimeInterval
  let text: String?
  let language: String?
  let context: String?
  let actionID: String?
  let actionRevision: String?
  let outputPreferences: OutputPreferences?
  init(_ action: String, operationID: String, text: String? = nil, language: String? = nil, context: String? = nil,
    actionID: String? = nil, actionRevision: String? = nil, outputPreferences: OutputPreferences? = nil) {
    self.actionID = actionID; self.actionRevision = actionRevision; self.outputPreferences = outputPreferences
    self.text = text; self.language = language; self.context = context
    self.commandID = UUID().uuidString
    self.operationID = operationID
    self.action = action
    self.createdAt = Date().timeIntervalSince1970
  }
}

// Separate atomic files avoid concurrent writes between app and keyboard.
struct SharedState {
  private static let preferenceLock = NSLock()
  let root: URL
  init(root: URL) { self.root = root }
  init?() {
    guard let group = Bundle.main.object(forInfoDictionaryKey: "ClarifyAppGroup") as? String,
          let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group)
    else { return nil }
    self.root = root
  }
  func read<T: Decodable>(_ name: String, as type: T.Type) -> T? {
    guard let data = try? Data(contentsOf: root.appendingPathComponent(name)) else { return nil }
    return try? JSONDecoder().decode(type, from: data)
  }
  func write<T: Encodable>(_ value: T, to name: String) throws {
    try JSONEncoder().encode(value).write(to: root.appendingPathComponent(name), options: .atomic)
  }
  func snapshot() -> DictationSnapshot { read("state.json", as: DictationSnapshot.self) ?? DictationSnapshot() }
  func outputPreferences() -> OutputPreferences {
    guard let data = try? Data(contentsOf: root.appendingPathComponent("output-preferences.json")), data.count <= 512,
      let value = try? JSONDecoder().decode(OutputPreferences.self, from: data) else { return OutputPreferences() }
    return value
  }
  func setOutputPreference(_ key: String, value: String) throws -> OutputPreferences {
    guard (key == "language" && OutputLanguage(rawValue: value) != nil) ||
      (key == "style" && OutputStyle(rawValue: value) != nil) else { throw ClarifyError(L("Preferência de saída inválida.")) }
    Self.preferenceLock.lock(); defer { Self.preferenceLock.unlock() }
    var failure: Error?, coordinationError: NSError?, updated = OutputPreferences()
    // NSFileCoordinator serializes app/extension read-modify-write transactions.
    // Atomic replacement also keeps uncoordinated readers on complete snapshots.
    NSFileCoordinator().coordinate(writingItemAt: root.appendingPathComponent("output-preferences.json"), options: .forMerging, error: &coordinationError) { _ in
      do {
        updated = outputPreferences()
        if key == "language" { updated.language = OutputLanguage(rawValue: value)! }
        else { updated.style = OutputStyle(rawValue: value)! }
        try write(updated, to: "output-preferences.json")
      } catch { failure = error }
    }
    if let coordinationError { throw coordinationError }
    if let failure { throw failure }
    return updated
  }
  func send(_ action: String, operationID: String, context: String?, text: String? = nil, language: String? = nil,
    actionID: String? = nil, actionRevision: String? = nil) throws {
    // The caller supplies the context that authorized this action. Reading a
    // newer snapshot here could retarget text to another processing owner.
    let command = DictationCommand(action, operationID: operationID, text: text, language: language, context: context,
      actionID: actionID, actionRevision: actionRevision, outputPreferences: outputPreferences())
    // Persist intent before command delivery. App acknowledgement, command
    // expiry and controller replacement must not restore a cancelled result.
    if action == "cancel" {
      try FileManager.default.createDirectory(at: root.appendingPathComponent("cancelled-operations"), withIntermediateDirectories: true)
      try write(operationID, to: cancellationName(operationID))
    }
    try write(command, to: "command-\(command.commandID).json")
    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
      CFNotificationName("com.clarify.keyboard.command" as CFString), nil, nil, true)
  }
  func commands() -> [(URL, DictationCommand)] {
    let files = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
    return files.filter { $0.lastPathComponent.hasPrefix("command-") && $0.pathExtension == "json" }
      .compactMap { url in read(url.lastPathComponent, as: DictationCommand.self).map { (url, $0) } }
      .sorted { $0.1.createdAt < $1.1.createdAt }
  }
  private func cancellationName(_ operationID: String) -> String {
    // Encode legacy IDs too; an operation ID cannot become a directory path.
    let encoded = operationID.utf8.map { String(format: "%02x", $0) }.joined()
    return "cancelled-operations/\(encoded).json"
  }
  func isCancelled(_ operationID: String?) -> Bool {
    guard let operationID else { return false }
    // Each operation has its own atomic marker. Overlapping controllers cannot
    // overwrite another cancellation through a shared read/modify/write list.
    return FileManager.default.fileExists(atPath: root.appendingPathComponent(cancellationName(operationID)).path)
  }
  func receipt() -> String? { read("receipt.json", as: String.self) }
  func acknowledge(_ operationID: String) throws {
    guard !isCancelled(operationID) else { throw CancellationError() }
    try write(operationID, to: "receipt.json")
  }
}

// A nonsecret, short-lived measurement. The app publishes it independently of
// dictation state so audio feedback does not refresh ActivityKit or retain audio.
struct AudioMeterReading: Codable {
  let operationID: String?
  let measuredAt: TimeInterval
  let level: Double
  static func inactive(now: TimeInterval = Date().timeIntervalSince1970) -> Self {
    Self(operationID: nil, measuredAt: now, level: 0)
  }
  func level(for operation: String?, now: TimeInterval = Date().timeIntervalSince1970) -> Double {
    guard let operation, operation == operationID, measuredAt.isFinite, now.isFinite,
          now >= measuredAt, now - measuredAt <= 0.4, level.isFinite else { return 0 }
    return min(1, max(0, level))
  }
}

enum AudioLevel {
  // Clamp bad/overloaded samples; silence and nonfinite buffers cannot move UI.
  static func measure<S: Sequence>(_ samples: S) -> Double where S.Element == Float {
    var energy = 0.0
    var count = 0
    for sample in samples {
      guard sample.isFinite else { continue }
      let value = min(1, max(-1, Double(sample)))
      energy += value * value; count += 1
    }
    guard count > 0, energy > 0 else { return 0 }
    let decibels = 20 * log10(sqrt(energy / Double(count)))
    return min(1, max(0, (decibels + 52) / 43))
  }
}

extension SharedState {
  func audioMeter() -> AudioMeterReading? { read("audio-meter.json", as: AudioMeterReading.self) }
  func publishAudioMeter(_ reading: AudioMeterReading) throws { try write(reading, to: "audio-meter.json") }
}

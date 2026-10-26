import Foundation

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
  var libraryRevision = 0
  var isLive: Bool { sessionActive && Date().timeIntervalSince1970 - heartbeat < 3 }
  private enum CodingKeys: String, CodingKey { case sessionActive, heartbeat, phase, operationID, text, message, errorCode, errorPhase, errorStatus, configured, libraryRevision, computerMode, processingContext, textOperation }
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
  init(_ action: String, operationID: String, text: String? = nil, language: String? = nil, context: String? = nil) {
    self.text = text; self.language = language; self.context = context
    self.commandID = UUID().uuidString
    self.operationID = operationID
    self.action = action
    self.createdAt = Date().timeIntervalSince1970
  }
}

// Separate atomic files avoid concurrent writes between app and keyboard.
struct SharedState {
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
  func send(_ action: String, operationID: String, text: String? = nil, language: String? = nil) throws {
    let command = DictationCommand(action, operationID: operationID, text: text, language: language, context: snapshot().processingContext)
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

import Foundation

// Pure keyboard state. Typed text stays in the document proxy, never in storage.
struct KeyboardState {
  enum Page { case letters, numbers, symbols }
  enum Shift { case off, once, caps }
  var page: Page = .letters
  var shift: Shift = .once
  private(set) var shiftIsManual = false
  var rows: [[String]] {
    switch page {
    case .letters:
      return [Array("qwertyuiop"), Array("asdfghjkl"), Array("zxcvbnm")].map {
        $0.map { shift == .off ? String($0) : String($0).uppercased() }
      }
    case .numbers:
      return [Array("1234567890"), Array("-/:;()$&@\""), Array(".,?!'")].map { $0.map(String.init) }
    case .symbols:
      return [Array("[]{}#%^*+="), Array("_\\|~<>€£¥•"), Array(".,?!'")].map { $0.map(String.init) }
    }
  }
  mutating func toggleShift(caps: Bool = false) {
    shiftIsManual = true
    shift = caps ? .caps : (shift == .off ? .once : .off)
  }
  mutating func didInsert(_ text: String) {
    if text.contains(where: { $0.isLetter }), shift != .caps {
      if shift == .once { shift = .off }
      shiftIsManual = false
    }
    if text == " " || text == "\n" { page = .letters }
  }
  static func startsSentence(after context: String) -> Bool {
    if context.isEmpty { return true }
    // Closing quotes/brackets and any number of spaces may follow punctuation.
    // A newline starts a new sentence even after an unfinished previous line.
    for character in context.reversed() {
      if character.isNewline { return true }
      if character.isWhitespace || "\"'”’»)]}".contains(character) { continue }
      return ".?!…".contains(character)
    }
    return true
  }
  static func accents(for key: String) -> [String] {
    let values: [String: String] = ["a": "aáàâãä", "e": "eéèêë", "i": "iíìîï",
      "o": "oóòôõö", "u": "uúùûü", "c": "cç", "n": "nñ"]
    guard let value = values[key.lowercased()] else { return [] }
    return value.map { key == key.uppercased() ? String($0).uppercased() : String($0) }
  }
}

// A tap starts one continuous clip. Release/movement do not issue commands.
// Pending actions stay separate from the app's acknowledged recording state.
struct RecordingRequest {
  private(set) var action: String?
  private(set) var operationID: String?
  private var requestedAt: TimeInterval = 0
  // Keep local publication intent for this keyboard's lifetime. A command can
  // expire or be acknowledged while its cancelled result remains in the store.
  private var cancelledOperations: Set<String> = []
  func isCancelled(_ id: String?) -> Bool { id.map { cancelledOperations.contains($0) } ?? false }
  mutating func submit(_ next: String, operationID id: String, now: TimeInterval) -> Bool {
    guard ["start", "finish", "cancel"].contains(next) else { return false }
    guard action == nil || (next == "cancel" && action != "cancel" && operationID == id) else { return false }
    action = next; operationID = id; requestedAt = now
    if next == "cancel" { cancelledOperations.insert(id) }
    return true
  }
  @discardableResult
  mutating func observe(_ state: DictationSnapshot, now: TimeInterval) -> Bool {
    guard let action else { return false }
    if !state.isLive { reset(); return false }
    let same = state.operationID == operationID
    let acknowledged = same && (action == "start" ? state.phase != .idle :
      action == "finish" ? ![.recording, .locked].contains(state.phase) :
      !state.phase.busy && state.heartbeat >= requestedAt)
    if acknowledged || (state.phase == .error && state.heartbeat >= requestedAt) ||
      (action == "cancel" && !state.phase.busy && state.operationID == nil && state.heartbeat >= requestedAt) { reset(); return false }
    // Commands older than five seconds are rejected by the app. Do not permit
    // another start until that delivery window has closed.
    if now - requestedAt >= 6 { reset(); return true }
    return false
  }
  // Reset delivery state only; acknowledgement does not undo a Cancel tap.
  mutating func reset() { action = nil; operationID = nil; requestedAt = 0 }
}

// Cancel can arrive before start when atomic command files share a timestamp.
// A bounded, short-lived tombstone prevents that cancelled clip from starting.
struct RecordingCancellations {
  private var operations: [String: TimeInterval] = [:]
  mutating func cancel(_ id: String, now: TimeInterval) {
    prune(now: now)
    if operations.count >= 64, let oldest = operations.min(by: { $0.value < $1.value })?.key { operations.removeValue(forKey: oldest) }
    operations[id] = now
  }
  mutating func acceptsStart(_ id: String, now: TimeInterval) -> Bool {
    prune(now: now); return operations[id] == nil
  }
  private mutating func prune(now: TimeInterval) { operations = operations.filter { now - $0.value < 10 } }
}

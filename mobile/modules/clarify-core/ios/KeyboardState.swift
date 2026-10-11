import Foundation

// Pure keyboard state. Typed text stays in the document proxy, never in storage.
struct KeyboardState {
  enum Page { case letters, numbers, symbols }
  enum Shift { case off, once, caps }
  var page: Page = .letters
  var shift: Shift = .once
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
    shift = caps ? .caps : (shift == .off ? .once : .off)
  }
  mutating func didInsert(_ text: String) {
    if shift == .once { shift = .off }
    if text == " " || text == "\n" { page = .letters }
  }
  static func accents(for key: String) -> [String] {
    let values: [String: String] = ["a": "aáàâãä", "e": "eéèêë", "i": "iíìîï",
      "o": "oóòôõö", "u": "uúùûü", "c": "cç", "n": "nñ"]
    guard let value = values[key.lowercased()] else { return [] }
    return value.map { key == key.uppercased() ? String($0).uppercased() : String($0) }
  }
}

struct RecordGesture {
  private(set) var holding = false
  var locked = false
  mutating func press() -> String {
    if locked { reset(); return "finish" }
    holding = true; return "start"
  }
  mutating func move(vertical: Double) -> String? {
    guard holding, !locked, vertical <= -28 else { return nil }
    locked = true; return "lock"
  }
  mutating func release() -> String? {
    defer { holding = false }
    return holding && !locked ? "finish" : nil
  }
  mutating func reset() { holding = false; locked = false }
}

import Foundation

enum KeyboardSelection {
  static func term(_ selection: String?) -> String? {
    guard let selection, selection.count <= 256 else { return nil }
    let words = selection.precomposedStringWithCanonicalMapping.split(whereSeparator: { $0.isWhitespace })
    guard (1...2).contains(words.count) else { return nil }
    let term = words.joined(separator: " ")
    guard term.rangeOfCharacter(from: .alphanumerics) != nil else { return nil }
    return term
  }
  static func key(_ term: String) -> String { term.precomposedStringWithCanonicalMapping.lowercased() }
}

struct KeyboardDictionaryWord: Codable, Equatable {
  var term: String
  var enabled: Bool
}

struct KeyboardDictionaryContext: Codable, Equatable {
  var scope: String
  var words: [KeyboardDictionaryWord]
}

struct KeyboardDictionaryAddition: Codable {
  var id = UUID().uuidString
  var scope: String
  var term: String
  var createdAt = Date().timeIntervalSince1970
}

// Only vocabulary and opaque scope IDs cross this boundary. The containing app
// alone owns SQLite, account credentials and network synchronization. Each add
// is durable before the keyboard confirms it, even if the app is suspended.
extension SharedState {
  func keyboardDictionary() -> KeyboardDictionaryContext? {
    guard let context = read("keyboard-dictionary.json", as: KeyboardDictionaryContext.self),
          context.scope == "guest" || UUID(uuidString: context.scope) != nil else { return nil }
    return context
  }
  func publishKeyboardDictionary(_ context: KeyboardDictionaryContext?) throws {
    if let context {
      if keyboardDictionary() != context { try write(context, to: "keyboard-dictionary.json") }
    } else {
      let url = root.appendingPathComponent("keyboard-dictionary.json")
      if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
    }
  }
  func keyboardAdditions(scope: String) -> [(URL, KeyboardDictionaryAddition)] {
    let files = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
    return files.filter { $0.lastPathComponent.hasPrefix("dictionary-add-") && $0.pathExtension == "json" }
      .compactMap { url -> (URL, KeyboardDictionaryAddition)? in
        guard let item = read(url.lastPathComponent, as: KeyboardDictionaryAddition.self), item.scope == scope,
              UUID(uuidString: item.id) != nil, KeyboardSelection.term(item.term) == item.term else { return nil }
        return (url, item)
      }.sorted { $0.1.createdAt < $1.1.createdAt }
  }
  func isKeyboardTermSaved(_ term: String, context: KeyboardDictionaryContext) -> Bool {
    let key = KeyboardSelection.key(term)
    return context.words.contains { $0.enabled && KeyboardSelection.key($0.term) == key }
      || keyboardAdditions(scope: context.scope).contains { KeyboardSelection.key($0.1.term) == key }
  }
  func addKeyboardTerm(_ selection: String, scope: String) throws {
    func failure(_ message: String) -> NSError {
      NSError(domain: "ClarifyDictionary", code: 1, userInfo: [NSLocalizedDescriptionKey: L(message)])
    }
    guard let term = KeyboardSelection.term(selection) else { throw failure("Selecione uma ou duas palavras.") }
    guard let context = keyboardDictionary(), context.scope == scope else {
      throw failure("Abra o Clarify para configurar o teclado.")
    }
    if isKeyboardTermSaved(term, context: context) { return }
    let pending = keyboardAdditions(scope: scope)
    let keys = Set((context.words.map(\.term) + pending.map { $0.1.term } + [term]).map(KeyboardSelection.key))
    guard keys.count <= 512 else { throw failure("O limite é de 512 termos.") }
    let item = KeyboardDictionaryAddition(scope: scope, term: term)
    try write(item, to: "dictionary-add-\(item.id).json")
    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
      CFNotificationName("com.clarify.keyboard.command" as CFString), nil, nil, true)
  }
  func discardKeyboardAdditions(scope: String) throws {
    for (url, _) in keyboardAdditions(scope: scope) { try FileManager.default.removeItem(at: url) }
  }
}

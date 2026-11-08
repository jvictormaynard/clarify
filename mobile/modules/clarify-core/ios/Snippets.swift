import Foundation

struct Snippet: Codable, Equatable {
  var trigger: String
  var replacement: String
  var enabled = true
  var caseSensitive = false
  enum CodingKeys: String, CodingKey { case trigger, replacement, enabled; case caseSensitive = "case_sensitive" }

  static func key(_ text: String) -> String {
    text.precomposedStringWithCanonicalMapping.folding(options: .caseInsensitive, locale: Locale(identifier: "en_US_POSIX"))
  }
  static func validate(_ entries: [Snippet]) throws -> [Snippet] {
    guard entries.count <= 512 else { throw ClarifyError(L("O limite é de 512 snippets.")) }
    var seen = Set<String>()
    return try entries.map { entry in
      var value = entry
      value.trigger = entry.trigger.precomposedStringWithCanonicalMapping
      value.replacement = entry.replacement.precomposedStringWithCanonicalMapping
      guard !value.trigger.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        value.trigger.unicodeScalars.count <= 256, !value.trigger.contains("\n"), !value.trigger.contains("\r"),
        !value.replacement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        value.replacement.unicodeScalars.count <= 4096 else {
        throw ClarifyError(L("Use uma frase de até 256 caracteres e um texto de até 4096 caracteres."))
      }
      guard seen.insert(key(value.trigger)).inserted else { throw ClarifyError(L("Esta frase de ativação já existe.")) }
      return value
    }
  }
  static func validateAccount(_ entries: [Snippet]) throws -> [Snippet] {
    let entries = try validate(entries)
    let encoder = JSONEncoder(); encoder.outputFormatting = .withoutEscapingSlashes
    guard try encoder.encode(entries).count <= 262_144 else {
      throw ClarifyError(L("Os snippets da conta excedem o limite de 256 KiB. Reduza o texto salvo."))
    }
    return entries
  }
  static func standalone(_ text: String, entries: [Snippet]) -> String? {
    let ignored = CharacterSet.whitespacesAndNewlines.union(.punctuationCharacters).union(.symbols)
    func spoken(_ value: String, sensitive: Bool) -> String {
      let normalized = sensitive ? value.precomposedStringWithCanonicalMapping : key(value)
      return String(String.UnicodeScalarView(normalized.unicodeScalars.filter { !ignored.contains($0) }))
    }
    let active = ordered(entries)
    guard !active.isEmpty else { return nil }
    let keys = [false: spoken(text, sensitive: false), true: spoken(text, sensitive: true)]
    for entry in active {
      let phrase = spoken(entry.trigger, sensitive: entry.caseSensitive)
      if !phrase.isEmpty, keys[entry.caseSensitive] == phrase { return entry.replacement }
    }
    return nil
  }
  private static func ordered(_ entries: [Snippet]) -> [Snippet] {
    entries.enumerated().filter { $0.element.enabled }.sorted {
      let a = key($0.element.trigger).unicodeScalars.count, b = key($1.element.trigger).unicodeScalars.count
      return a == b ? $0.offset < $1.offset : a > b
    }.map(\.element)
  }
  static func expand(_ text: String, entries: [Snippet]) throws -> String {
    guard text.unicodeScalars.count <= 1_000_000 else { throw ClarifyError(L("O texto é muito longo.")) }
    if let replacement = standalone(text, entries: entries) { return replacement }
    let active = ordered(entries)
    guard !active.isEmpty else { return text }
    let patterns = active.map { entry -> String in
      let literal = NSRegularExpression.escapedPattern(for: entry.trigger)
      return "(" + (entry.caseSensitive ? literal : "(?i:" + literal + ")") + ")"
    }
    let regex = try NSRegularExpression(pattern: "(?<![\\p{L}\\p{N}_])(?:" + patterns.joined(separator: "|") + ")(?![\\p{L}\\p{N}_])")
    // Map canonical grapheme boundaries to the original UTF-16 offsets. Keep
    // unmatched text byte-for-byte, including decomposed accents.
    var canonical = "", boundaries = [0: 0], originalOffset = 0, normalizedOffset = 0
    for character in text {
      let raw = String(character), normalized = raw.precomposedStringWithCanonicalMapping
      canonical += normalized
      originalOffset += raw.utf16.count; normalizedOffset += normalized.utf16.count
      boundaries[normalizedOffset] = originalOffset
    }
    let source = canonical as NSString, original = text as NSString
    var result = "", cursor = 0
    for match in regex.matches(in: source as String, range: NSRange(location: 0, length: source.length)) {
      guard let start = boundaries[match.range.location], let end = boundaries[NSMaxRange(match.range)],
        let index = active.indices.first(where: { match.range(at: $0 + 1).location != NSNotFound }) else { continue }
      result += original.substring(with: NSRange(location: cursor, length: start - cursor))
      result += active[index].replacement
      cursor = end
      guard result.unicodeScalars.count <= 1_000_000 else { throw ClarifyError(L("O texto é muito longo.")) }
    }
    result += original.substring(from: cursor)
    guard result.unicodeScalars.count <= 1_000_000 else { throw ClarifyError(L("O texto é muito longo.")) }
    return result
  }
  static func vocabulary(_ entries: [Snippet]) -> [VocabularyEntry] {
    entries.filter(\.enabled).map { VocabularyEntry(term: $0.trigger) }
  }
}

struct CloudSnippets: Codable {
  var entries: [Snippet] = []
  var base: [Snippet] = []
  var revision: Int?
  static func validateScope(_ value: String) throws {
    let parts = value.components(separatedBy: "|")
    guard parts.count == 2, UUID(uuidString: parts[1]) != nil,
      let endpoint = URLComponents(string: parts[0]), let host = endpoint.host, !host.isEmpty,
      endpoint.user == nil, endpoint.password == nil, endpoint.query == nil,
      endpoint.fragment == nil, endpoint.path.isEmpty,
      endpoint.scheme == "https" || (endpoint.scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host)) else {
      throw ClarifyError(L("Resposta inválida do Clarify."))
    }
  }
}

struct SnippetResponse: Decodable {
  let revision: Int
  let entries: [Snippet]
  static func decode(_ value: [String: Any]) throws -> SnippetResponse {
    let result = try JSONDecoder().decode(SnippetResponse.self, from: JSONSerialization.data(withJSONObject: value))
    guard result.revision >= 0, try Snippet.validateAccount(result.entries) == result.entries else {
      throw ClarifyError(L("Resposta inválida do Clarify."))
    }
    return result
  }
}

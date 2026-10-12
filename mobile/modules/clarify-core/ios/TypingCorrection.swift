import Foundation

// Local, ephemeral edit plans. No document text is stored or sent to a provider.
struct TypingContext: Equatable {
  var document: UUID
  var before: String
  var after: String
  var hasSelection = false
}

struct TypingEdit: Equatable {
  var deleteCount: Int
  var text: String
}

struct TypingCorrection {
  private struct Undo {
    var context: TypingContext
    var original: String
    var replacement: String
    var separator: String
  }
  private var undo: Undo?
  private var rejectedWord: String?

  static func word(in context: TypingContext) -> String? {
    guard !context.hasSelection, context.before.last?.isLetter == true,
          context.after.first.map({ !$0.isLetter && !$0.isNumber && $0 != "_" }) ?? true else { return nil }
    let raw = context.before.split(whereSeparator: { $0.isWhitespace }).last ?? ""
    let token = String(raw.drop(while: { "([{«“\"'¿¡".contains($0) }))
    guard (2...40).contains(token.count), token.allSatisfy({ $0.isLetter }) else { return nil }
    return token
  }

  static func canAutomaticallyReplace(_ word: String, with candidate: String) -> Bool {
    guard !word.isEmpty, !candidate.isEmpty, candidate != word, candidate.allSatisfy({ $0.isLetter }),
          word != word.uppercased(),
          word.dropFirst().allSatisfy({ !$0.isUppercase }) else { return false }
    return editDistance(word, candidate) <= (word.count >= 6 ? 2 : 1)
  }

  static func rankedCandidates(for word: String, guesses: [String]) -> [String] {
    let letters = Array(word.lowercased())
    var repeatedLetterFixes = Set<String>()
    if letters.count > 1 {
      for index in 1..<letters.count where letters[index] == letters[index - 1] {
        var fixed = letters; fixed.remove(at: index); repeatedLetterFixes.insert(String(fixed))
      }
    }
    return guesses.enumerated().sorted {
      let left = editDistance(word, $0.element), right = editDistance(word, $1.element)
      if left != right { return left < right }
      let leftRepeat = repeatedLetterFixes.contains($0.element.lowercased())
      let rightRepeat = repeatedLetterFixes.contains($1.element.lowercased())
      return leftRepeat == rightRepeat ? $0.offset < $1.offset : leftRepeat
    }.map { $0.element }
  }

  // Include swapped neighbours, as well as insertion, deletion and substitution.
  private static func editDistance(_ word: String, _ candidate: String) -> Int {
    let a = Array(word.lowercased()), b = Array(candidate.lowercased())
    var distance = Array(repeating: Array(repeating: 0, count: b.count + 1), count: a.count + 1)
    for i in 0...a.count { distance[i][0] = i }
    for j in 0...b.count { distance[0][j] = j }
    guard !a.isEmpty, !b.isEmpty else { return max(a.count, b.count) }
    for i in 1...a.count {
      for j in 1...b.count {
        distance[i][j] = min(distance[i - 1][j] + 1, distance[i][j - 1] + 1,
          distance[i - 1][j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1))
        if i > 1, j > 1, a[i - 1] == b[j - 2], a[i - 2] == b[j - 1] {
          distance[i][j] = min(distance[i][j], distance[i - 2][j - 2] + 1)
        }
      }
    }
    return distance[a.count][b.count]
  }

  mutating func replacement(in context: TypingContext, candidate: String,
                            separator: String, automatic: Bool) -> TypingEdit? {
    undo = nil
    guard let word = Self.word(in: context), candidate != word,
          !candidate.isEmpty, candidate.allSatisfy({ $0.isLetter }),
          !automatic || (word != rejectedWord && Self.canAutomaticallyReplace(word, with: candidate)) else { return nil }
    var expected = context
    expected.before = String(context.before.dropLast(word.count)) + candidate + separator
    undo = Undo(context: expected, original: word, replacement: candidate, separator: separator)
    rejectedWord = nil
    return TypingEdit(deleteCount: word.count, text: candidate + separator)
  }

  func original(in context: TypingContext) -> String? {
    guard let undo, matchesUndo(undo, context: context) else { return nil }
    return undo.original
  }

  private func matchesUndo(_ undo: Undo, context: TypingContext) -> Bool {
    guard undo.context.document == context.document, undo.context.after == context.after,
          !context.hasSelection, context.before.count >= undo.replacement.count + undo.separator.count else { return false }
    // Document proxies expose a bounded suffix. An insertion can push one
    // character out of that window without changing the correction at its end.
    return undo.context.before == context.before ||
      (context.before.count < undo.context.before.count && undo.context.before.hasSuffix(context.before))
  }

  mutating func revert(in context: TypingContext, keepSeparator: Bool = false) -> TypingEdit? {
    defer { undo = nil }
    guard let undo = undo, matchesUndo(undo, context: context) else { return nil }
    rejectedWord = undo.original
    return TypingEdit(deleteCount: undo.replacement.count + undo.separator.count,
      text: undo.original + (keepSeparator ? undo.separator : ""))
  }

  mutating func reset() { undo = nil; rejectedWord = nil }

  mutating func keepOriginal(in context: TypingContext) -> TypingEdit? {
    guard let word = Self.word(in: context) else { return nil }
    undo = nil; rejectedWord = word
    return TypingEdit(deleteCount: 0, text: " ")
  }
}

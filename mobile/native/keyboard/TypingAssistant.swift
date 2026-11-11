import UIKit
import NaturalLanguage

// UITextChecker supplies the local dictionaries. This adapter never does I/O.
final class TypingAssistant {
  struct Suggestion {
    var title: String
    var value: String
    var context: TypingContext
    var undo = false
  }
  var autocorrectionEnabled: Bool {
    didSet { if oldValue != autocorrectionEnabled { correction.reset() } }
  }
  init(autocorrectionEnabled: Bool = true,
       now: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
    self.autocorrectionEnabled = autocorrectionEnabled; self.now = now
  }
  private let now: () -> TimeInterval
  private var pendingSpace: (context: TypingContext, time: TimeInterval)?
  private struct CursorSnapshot {
    var context: TypingContext
    var offset = 0
    var lastMovement = 0
  }
  private var cursorSnapshots: [CursorSnapshot] = []
  private var inputGeneration: UInt = 0
  private let checker = UITextChecker()
  private var correction = TypingCorrection()
  private var protectedWords = Set<String>()
  private var vocabularyWords = Set<String>()
  private let languages: [String] = {
    let available = UITextChecker.availableLanguages
    return [available.first { $0 == "pt_BR" } ?? available.first { $0.hasPrefix("pt") },
      available.first { $0 == "en_US" } ?? available.first { $0.hasPrefix("en") },
      available.first { $0 == "es_ES" } ?? available.first { $0.hasPrefix("es") }].compactMap { $0 }.sorted {
        $0.hasPrefix(ClarifyLocale.language) && !$1.hasPrefix(ClarifyLocale.language)
      }
  }()

  func protect(_ lexicon: UILexicon) {
    protectedWords = Set(lexicon.entries.flatMap { [$0.documentText.lowercased(), $0.userInput.lowercased()] })
  }
  func protectVocabulary(_ words: [String]) {
    vocabularyWords = Set(words.flatMap { $0.lowercased().split(whereSeparator: { $0.isWhitespace }).map(String.init) })
  }
  func reset() { invalidateSpace(); correction.reset() }
  private func invalidateSpace() { inputGeneration &+= 1; pendingSpace = nil; cursorSnapshots = [] }
  func prepareCursor(in proxy: UITextDocumentProxy) {
    endCursor()
    let generation = inputGeneration
    let captured = proxy.isSecureTextEntry != true ? context(proxy) : nil
    if generation == inputGeneration, let captured, !captured.hasSelection {
      cursorSnapshots = [CursorSnapshot(context: captured)]
    }
  }
  func endCursor() { inputGeneration &+= 1; cursorSnapshots = [] }
  private func cursorMatches(_ actual: TypingContext, _ snapshot: CursorSnapshot) -> Bool {
    let expected = snapshot.context
    guard actual.document == expected.document, !actual.hasSelection else { return false }
    // Preparation is exact. Only an owned move permits a bounded window refresh.
    let before = actual.before == expected.before || (!actual.before.isEmpty && !expected.before.isEmpty &&
      ((snapshot.offset < 0 && actual.before.hasSuffix(expected.before)) ||
       (snapshot.offset > 0 && expected.before.hasSuffix(actual.before))))
    let after = actual.after == expected.after || (!actual.after.isEmpty && !expected.after.isEmpty &&
      ((snapshot.offset > 0 && actual.after.hasPrefix(expected.after)) ||
       (snapshot.offset < 0 && expected.after.hasPrefix(actual.after))))
    // UIKit can replace its optimistic following context between drag events.
    // Require the exact preceding anchor, including the character we moved over.
    // A newly exposed tail can be indistinguishable from an external tail edit.
    let refreshedAfter = !actual.before.isEmpty && actual.before == expected.before &&
      actual.after.utf16.count <= 64 &&
      ((snapshot.lastMovement > 0 && actual.after.hasPrefix(expected.after)) ||
       (snapshot.lastMovement < 0 && !actual.after.isEmpty && expected.after.hasPrefix(actual.after)))
    return before && (after || refreshedAfter)
  }
  func moveCursor(_ offset: Int, in proxy: UITextDocumentProxy) -> Bool {
    let preparedGeneration = inputGeneration
    guard offset != 0, (-32...32).contains(offset), proxy.isSecureTextEntry != true,
          var target = cursorSnapshots.last, let observed = context(proxy),
          let confirmed = cursorSnapshots.firstIndex(where: { cursorMatches(observed, $0) }),
          inputGeneration == preparedGeneration else {
      endCursor(); return false
    }
    var snapshots = Array(cursorSnapshots[confirmed...])
    if snapshots.count == 1 {
      target = CursorSnapshot(context: observed, lastMovement: target.lastMovement); snapshots = [target]
    }
    let moved = offset < 0 ? String(target.context.before.suffix(-offset)) : String(target.context.after.prefix(offset))
    if moved.isEmpty { return true }
    let adjustment = (offset < 0 ? -1 : 1) * moved.utf16.count
    target.offset += adjustment
    target.lastMovement = adjustment
    if offset < 0 {
      target.context.before = String(target.context.before.dropLast(moved.count)); target.context.after = moved + target.context.after
    } else {
      target.context.before += moved; target.context.after = String(target.context.after.dropFirst(moved.count))
    }
    // A repeated position does not confirm a round trip while context is delayed.
    // Keep the earliest matching position and every unconfirmed movement after it.
    // Retain only this bounded session's positions and anchored window refreshes.
    guard snapshots.count < 64 else { endCursor(); return false }
    snapshots.append(target)
    invalidateSpace(); correction.reset()
    let generation = inputGeneration
    // The proxy offset uses UTF-16 units; the drag steps over whole characters.
    proxy.adjustTextPosition(byCharacterOffset: adjustment)
    guard let current = context(proxy), proxy.isSecureTextEntry != true,
          let confirmed = snapshots.firstIndex(where: { cursorMatches(current, $0) }),
          inputGeneration == generation else { return false }
    cursorSnapshots = Array(snapshots[confirmed...])
    if cursorSnapshots.count == 1 {
      cursorSnapshots = [CursorSnapshot(context: current, lastMovement: target.lastMovement)]
    }
    return true
  }
  private func matches(_ actual: TypingContext?, _ expected: TypingContext) -> Bool {
    guard let actual, actual.document == expected.document, actual.after == expected.after,
          !actual.hasSelection, !actual.before.isEmpty, !expected.before.isEmpty else { return false }
    // A proxy can expose a different bounded suffix after inserting or deleting.
    return actual.before.hasSuffix(expected.before) || expected.before.hasSuffix(actual.before)
  }
  private func context(_ proxy: UITextDocumentProxy) -> TypingContext? {
    guard let before = proxy.documentContextBeforeInput else { return nil }
    return TypingContext(document: proxy.documentIdentifier, before: before,
      after: proxy.documentContextAfterInput ?? "", hasSelection: proxy.selectedText?.isEmpty == false)
  }
  private func enabled(_ proxy: UITextDocumentProxy) -> Bool {
    guard autocorrectionEnabled, proxy.autocorrectionType != .no, proxy.spellCheckingType != .no,
          proxy.isSecureTextEntry != true else { return false }
    return [.default, .alphabet, .twitter].contains(proxy.keyboardType ?? .default)
  }
  private func guesses(_ word: String, context: TypingContext) -> [String] {
    guard !protectedWords.contains(word.lowercased()), !vocabularyWords.contains(word.lowercased()), !languages.isEmpty else { return [] }
    let range = NSRange(word.startIndex..<word.endIndex, in: word)
    // Do not correct a valid word in any supported language.
    if languages.contains(where: {
      checker.rangeOfMisspelledWord(in: word, range: range, startingAt: 0, wrap: false, language: $0).location == NSNotFound
    }) { return [] }
    var results: [String] = []
    let preceding = String(context.before.dropLast(word.count).suffix(200))
    let language = preceding.count >= 8 ? NLLanguageRecognizer.dominantLanguage(for: preceding)?.rawValue : nil
    let ordered = language.map { preferred in languages.sorted { $0.hasPrefix(preferred) && !$1.hasPrefix(preferred) } } ?? languages
    let fullText = preceding + word
    let fullRange = NSRange(location: (preceding as NSString).length, length: (word as NSString).length)
    for language in ordered {
      for guess in (checker.guesses(forWordRange: fullRange, in: fullText, language: language) ?? []).prefix(8) {
        let value = word.first?.isUppercase == true ? guess.prefix(1).uppercased() + guess.dropFirst() : guess
        if value != word, value.allSatisfy({ $0.isLetter }), !results.contains(value) { results.append(value) }
      }
    }
    return Array(TypingCorrection.rankedCandidates(for: word, guesses: results).prefix(2))
  }
  func suggestions(_ proxy: UITextDocumentProxy) -> [Suggestion] {
    guard enabled(proxy), let context = context(proxy) else { return [] }
    if let original = correction.original(in: context) {
      return [Suggestion(title: "↶ \(original)", value: original, context: context, undo: true)]
    }
    guard let word = TypingCorrection.word(in: context) else { return [] }
    let values = guesses(word, context: context)
    guard !values.isEmpty else { return [] }
    return [Suggestion(title: "“\(word)”", value: word, context: context)] + values.map {
      Suggestion(title: $0, value: $0, context: context)
    }
  }
  func insert(_ text: String, into proxy: UITextDocumentProxy) {
    let previousSpace = pendingSpace; invalidateSpace()
    let generation = inputGeneration, time = now(), before = context(proxy)
    let permitsShortcut = proxy.isSecureTextEntry != true &&
      [.default, .alphabet, .twitter].contains(proxy.keyboardType ?? .default)
    if text == " ", permitsShortcut, let before, !before.hasSelection,
       let previousSpace, previousSpace.context == before,
       (0...0.3).contains(time - previousSpace.time) {
      correction.reset()
      var expected = before; expected.before.removeLast()
      proxy.deleteBackward()
      guard inputGeneration == generation, matches(context(proxy), expected) else { return }
      proxy.insertText(". "); return
    }
    var expected = before
    expected?.before += text
    if enabled(proxy), [" ", "\n", ".", ",", "!", "?", ";", ":"].contains(text),
       let context = context(proxy), let word = TypingCorrection.word(in: context),
       let guess = guesses(word, context: context).first,
       let edit = correction.replacement(in: context, candidate: guess, separator: text, automatic: true) {
      expected?.before = String(context.before.dropLast(edit.deleteCount)) + edit.text
      apply(edit, to: proxy)
    } else { proxy.insertText(text) }
    if text == " ", permitsShortcut, generation == inputGeneration,
       let before, !before.hasSelection, let expected, let after = context(proxy),
       matches(after, expected), after.before.last == " ",
       let character = after.before.dropLast().last, character.isLetter || character.isNumber {
      pendingSpace = (after, time)
    }
  }
  func delete(in proxy: UITextDocumentProxy) {
    invalidateSpace()
    if let context = context(proxy), let edit = correction.revert(in: context) { apply(edit, to: proxy) }
    else { proxy.deleteBackward() }
  }
  func choose(_ suggestion: Suggestion, in proxy: UITextDocumentProxy) {
    invalidateSpace()
    guard enabled(proxy), context(proxy) == suggestion.context else { return }
    if suggestion.undo {
      if let edit = correction.revert(in: suggestion.context, keepSeparator: true) { apply(edit, to: proxy) }
    } else if let edit = correction.replacement(in: suggestion.context, candidate: suggestion.value, separator: " ", automatic: false) {
      apply(edit, to: proxy)
    } else {
      // Choosing the quoted original explicitly keeps its spelling.
      if let edit = correction.keepOriginal(in: suggestion.context) { apply(edit, to: proxy) }
    }
  }
  private func apply(_ edit: TypingEdit, to proxy: UITextDocumentProxy) {
    for _ in 0..<edit.deleteCount { proxy.deleteBackward() }
    proxy.insertText(edit.text)
  }
}

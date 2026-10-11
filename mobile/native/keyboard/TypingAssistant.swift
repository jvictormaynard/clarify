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
  private let checker = UITextChecker()
  private var correction = TypingCorrection()
  private var protectedWords = Set<String>()
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
  func reset() { correction.reset() }
  private func context(_ proxy: UITextDocumentProxy) -> TypingContext? {
    guard let before = proxy.documentContextBeforeInput else { return nil }
    return TypingContext(document: proxy.documentIdentifier, before: before,
      after: proxy.documentContextAfterInput ?? "", hasSelection: proxy.selectedText?.isEmpty == false)
  }
  private func enabled(_ proxy: UITextDocumentProxy) -> Bool {
    guard proxy.autocorrectionType != .no, proxy.spellCheckingType != .no,
          proxy.isSecureTextEntry != true else { return false }
    return [.default, .alphabet, .twitter].contains(proxy.keyboardType ?? .default)
  }
  private func guesses(_ word: String, context: TypingContext) -> [String] {
    guard !protectedWords.contains(word.lowercased()), !languages.isEmpty else { return [] }
    let range = NSRange(word.startIndex..<word.endIndex, in: word)
    // Do not correct a valid word in either supported language.
    if languages.contains(where: {
      checker.rangeOfMisspelledWord(in: word, range: range, startingAt: 0, wrap: false, language: $0).location == NSNotFound
    }) { return [] }
    var results: [String] = []
    let preceding = String(context.before.dropLast(word.count).suffix(200))
    let english = preceding.count >= 8 && NLLanguageRecognizer.dominantLanguage(for: preceding) == .english
    let ordered = english ? languages.sorted { $0.hasPrefix("en") && !$1.hasPrefix("en") } : languages
    for language in ordered {
      for guess in (checker.guesses(forWordRange: range, in: word, language: language) ?? []).prefix(8) {
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
    if enabled(proxy), [" ", "\n", ".", ",", "!", "?", ";", ":"].contains(text),
       let context = context(proxy), let word = TypingCorrection.word(in: context),
       let guess = guesses(word, context: context).first,
       let edit = correction.replacement(in: context, candidate: guess, separator: text, automatic: true) {
      apply(edit, to: proxy)
    } else { proxy.insertText(text) }
  }
  func delete(in proxy: UITextDocumentProxy) {
    if let context = context(proxy), let edit = correction.revert(in: context) { apply(edit, to: proxy) }
    else { proxy.deleteBackward() }
  }
  func choose(_ suggestion: Suggestion, in proxy: UITextDocumentProxy) {
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

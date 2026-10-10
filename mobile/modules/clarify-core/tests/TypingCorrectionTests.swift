import XCTest
@testable import ClarifyContracts

final class TypingCorrectionTests: XCTestCase {
  private func context(_ before: String, after: String = "") -> TypingContext {
    TypingContext(document: UUID(), before: before, after: after)
  }
  func testPortugueseCorrectionCanBeUndoneAndRejected() {
    var engine = TypingCorrection()
    var field = context("Olá, voce")
    XCTAssertEqual(engine.replacement(in: field, candidate: "você", separator: " ", automatic: true),
      TypingEdit(deleteCount: 4, text: "você "))
    field.before = "Olá, você "
    XCTAssertEqual(engine.original(in: field), "voce")
    XCTAssertEqual(engine.revert(in: field), TypingEdit(deleteCount: 5, text: "voce"))
    field.before = "Olá, voce"
    XCTAssertNil(engine.replacement(in: field, candidate: "você", separator: " ", automatic: true))
  }
  func testUndoCannotDeleteTextInAnotherFieldOrAfterCursorMovement() {
    var engine = TypingCorrection()
    var field = context("teh")
    XCTAssertNotNil(engine.replacement(in: field, candidate: "the", separator: " ", automatic: true))
    field.before = "the "
    var other = field; other.document = UUID()
    XCTAssertNil(engine.original(in: other))
    other = field; other.after = "another word"
    XCTAssertNil(engine.original(in: other))
    field.before += "x"
    XCTAssertNil(engine.revert(in: field))
  }
  func testIdentifiersURLsEmailAndPartialWordsAreExcluded() {
    for token in ["https://clarfy", "victor@clarfy", "build123", "foo_bar", "gsk-test"] {
      XCTAssertNil(TypingCorrection.word(in: context(token)))
    }
    XCTAssertNil(TypingCorrection.word(in: context("te", after: "xt")))
    var selected = context("teh"); selected.hasSelection = true
    XCTAssertNil(TypingCorrection.word(in: selected))
    XCTAssertFalse(TypingCorrection.canAutomaticallyReplace("GROQ", with: "grow"))
    XCTAssertFalse(TypingCorrection.canAutomaticallyReplace("iPhone", with: "phone"))
    XCTAssertFalse(TypingCorrection.canAutomaticallyReplace("clarify", with: "claridade"))
    XCTAssertNil(TypingCorrection.word(in: context("word ")))
  }
  func testManualSuggestionAndUnicodeUseCharacterCounts() {
    var engine = TypingCorrection()
    let field = context("🙂 cafe")
    XCTAssertEqual(engine.replacement(in: field, candidate: "café", separator: " ", automatic: false),
      TypingEdit(deleteCount: 4, text: "café "))
    XCTAssertTrue(TypingCorrection.canAutomaticallyReplace("teh", with: "the"))
    XCTAssertTrue(TypingCorrection.canAutomaticallyReplace("ola", with: "olá"))
  }
  func testAccidentalRepeatedLetterIsRemovedBeforeChangingAnotherLetter() {
    XCTAssertEqual(TypingCorrection.rankedCandidates(for: "obrigaddo", guesses: ["obrigando", "obrigado"]).first, "obrigado")
    XCTAssertEqual(TypingCorrection.rankedCandidates(for: "teh", guesses: ["the", "ter"]).first, "the")
  }
  func testChoosingTheOriginalKeepsItAfterDeletingAndRetypingTheSpace() {
    var engine = TypingCorrection()
    let field = context("voce")
    XCTAssertEqual(engine.keepOriginal(in: field), TypingEdit(deleteCount: 0, text: " "))
    XCTAssertNil(engine.replacement(in: field, candidate: "você", separator: " ", automatic: true))
  }
}

import XCTest
@testable import ClarifyContracts

final class KeyboardVocabularyTests: XCTestCase {
  private func fixture() throws -> (URL, SharedState, LocalLibrary) {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return (root, SharedState(root: root), try LocalLibrary(root: root.appendingPathComponent("app-only")))
  }
  func testOnlyOneOrTwoWordsAreOfferedAndUnicodeIsPreserved() {
    let invalid: [String?] = [nil, "", " \n ", "+ …", "one two three", String(repeating: "a", count: 257)]
    for selection in invalid {
      XCTAssertNil(KeyboardSelection.term(selection))
    }
    XCTAssertEqual(KeyboardSelection.term("  Clarify  "), "Clarify")
    XCTAssertEqual(KeyboardSelection.term("João\nVictor"), "João Victor")
    XCTAssertEqual(KeyboardSelection.term("Cafe\u{301}"), "Café")
    XCTAssertEqual(KeyboardSelection.term("São\u{00a0}Paulo"), "São Paulo")
    XCTAssertNotEqual(KeyboardSelection.key("cafe"), KeyboardSelection.key("café"))
  }
  func testTapIsDurableAndDuplicateTapsRemainIdempotentAcrossRelaunch() throws {
    let (root, store, library) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
    let context = KeyboardDictionaryContext(scope: "guest", words: [])
    try store.publishKeyboardDictionary(context)
    try store.addKeyboardTerm("Cafe\u{301}", scope: "guest")
    let relaunched = SharedState(root: root)
    XCTAssertTrue(relaunched.isKeyboardTermSaved("CAFÉ", context: context))
    try relaunched.addKeyboardTerm("CAFÉ", scope: "guest")
    XCTAssertEqual(relaunched.keyboardAdditions(scope: "guest").count, 1)
    XCTAssertTrue(try library.dictionary().isEmpty, "The extension must not write the app-only database")
    XCTAssertTrue(try library.importKeyboardAdditions(relaunched, scope: nil))
    XCTAssertEqual(try library.dictionary().map(\.term), ["Café"])
    XCTAssertFalse(try library.importKeyboardAdditions(relaunched, scope: nil))
    XCTAssertTrue(relaunched.keyboardAdditions(scope: "guest").isEmpty)
  }
  func testExistingTermsAreSavedAndDisabledTermsRetainTheirMetadataWhenEnabled() throws {
    let (root, store, library) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
    let entries = [VocabularyEntry(term: "Clarify"), VocabularyEntry(term: "João Victor", pronunciation: "joao", aliases: ["JV"], enabled: false)]
    try library.saveDictionary(entries)
    let context = KeyboardDictionaryContext(scope: "guest", words: entries.map { KeyboardDictionaryWord(term: $0.term, enabled: $0.enabled) })
    try store.publishKeyboardDictionary(context)
    try store.addKeyboardTerm("CLARIFY", scope: "guest")
    XCTAssertTrue(store.keyboardAdditions(scope: "guest").isEmpty)
    XCTAssertFalse(store.isKeyboardTermSaved("João Victor", context: context))
    try store.addKeyboardTerm("João Victor", scope: "guest")
    XCTAssertTrue(try library.importKeyboardAdditions(store, scope: nil))
    var expected = entries; expected[1].enabled = true
    XCTAssertEqual(try library.dictionary(), expected)
  }
  func testAccountAndGuestQueuesNeverCrossScopesAndStaleScopeCannotSave() throws {
    let (root, store, library) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
    let first = UUID().uuidString, second = UUID().uuidString
    try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: first, words: []))
    try store.addKeyboardTerm("Account One", scope: first)
    try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: second, words: []))
    XCTAssertThrowsError(try store.addKeyboardTerm("Wrong Account", scope: first))
    try store.addKeyboardTerm("Account Two", scope: second)
    XCTAssertFalse(try library.importKeyboardAdditions(store, scope: nil))
    XCTAssertTrue(try library.importKeyboardAdditions(store, scope: second))
    XCTAssertEqual(try library.dictionary(scope: second).map(\.term), ["Account Two"])
    XCTAssertTrue(try library.dictionary(scope: first).isEmpty)
    XCTAssertEqual(store.keyboardAdditions(scope: first).count, 1)
    try store.discardKeyboardAdditions(scope: first)
    XCTAssertTrue(store.keyboardAdditions(scope: first).isEmpty)
    XCTAssertTrue(try library.dictionary().isEmpty)
    try store.publishKeyboardDictionary(nil)
    XCTAssertThrowsError(try store.addKeyboardTerm("No Context", scope: "guest"))
  }
  func testImportPreservesConcurrentAppEditsAndCanRecoverFromAnInterruptedAcknowledgement() throws {
    let (root, store, library) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
    try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: []))
    try store.addKeyboardTerm("Keyboard", scope: "guest")
    try library.saveDictionary([VocabularyEntry(term: "App Edit"), VocabularyEntry(term: "Keyboard")])
    XCTAssertFalse(try library.importKeyboardAdditions(store, scope: nil))
    XCTAssertEqual(try library.dictionary().map(\.term), ["App Edit", "Keyboard"])
    XCTAssertTrue(store.keyboardAdditions(scope: "guest").isEmpty)
  }
  func testCapacityRejectionDoesNotClaimASaveOrDropQueuedEdits() throws {
    let (root, store, library) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
    let entries = (0..<512).map { VocabularyEntry(term: "Term\($0)") }
    try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: entries.map { KeyboardDictionaryWord(term: $0.term, enabled: true) }))
    XCTAssertThrowsError(try store.addKeyboardTerm("Overflow", scope: "guest"))
    XCTAssertTrue(store.keyboardAdditions(scope: "guest").isEmpty)
    try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: []))
    try store.addKeyboardTerm("Pending", scope: "guest")
    try library.saveDictionary(entries)
    XCTAssertThrowsError(try library.importKeyboardAdditions(store, scope: nil))
    XCTAssertEqual(store.keyboardAdditions(scope: "guest").count, 1)
    XCTAssertEqual(try library.dictionary(), entries)
  }
  func testDictionaryActionLabelsFollowTheSharedCatalog() {
    for (language, add, saved) in [("pt", "Adicionar ao dicionário", "Salvo"), ("en", "Add to Dictionary", "Saved"), ("es", "Añadir al diccionario", "Guardado")] {
      XCTAssertEqual(L("Adicionar ao dicionário", language: language), add)
      XCTAssertEqual(L("Salvo", language: language), saved)
    }
  }
}

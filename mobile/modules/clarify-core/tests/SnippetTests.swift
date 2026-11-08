import XCTest
import SQLite3
@testable import ClarifyContracts

final class SnippetTests: XCTestCase {
  func testSharedMatchingExamples() throws {
    struct Example: Decodable { let input: String; let snippets: [Snippet]; let expected: String }
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0..<5 { root.deleteLastPathComponent() }
    let examples = try JSONDecoder().decode([Example].self, from: Data(contentsOf: root.appendingPathComponent("shared/snippet_examples.json")))
    for example in examples { XCTAssertEqual(try Snippet.expand(example.input, entries: Snippet.validate(example.snippets)), example.expected, example.input) }
  }
  func testGuestAndAccountsRemainSeparateAcrossLaunchesAndDeletion() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let user = UUID().uuidString, first = "https://one.test|" + user, second = "https://two.test|" + user
    let guest = Snippet(trigger: "sig", replacement: "Guest"), account = Snippet(trigger: "sig", replacement: "Account")
    do {
      let library = try LocalLibrary(root: root)
      try library.saveSnippets([guest]); try library.saveSnippets([account], scope: first)
      XCTAssertTrue(try library.snippets(scope: second).isEmpty)
      XCTAssertThrowsError(try library.saveSnippets([guest, guest]))
      try library.saveDictionary([], scope: user)
      XCTAssertEqual(try library.snippets(scope: first), [account])
    }
    let library = try LocalLibrary(root: root)
    XCTAssertEqual(try library.snippets(), [guest]); XCTAssertEqual(try library.snippets(scope: first), [account])
    try library.deleteCloudAccount(dictionaryScope: user, historyScope: first)
    XCTAssertTrue(try library.snippets(scope: first).isEmpty); XCTAssertEqual(try library.snippets(), [guest])
  }
  func testUpgradeFromHistorySchemaPreservesDictionaryHistoryAndOutbox() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let scope = "https://one.test|" + UUID().uuidString
    let entry = HistoryEntry(id: "existing", createdAt: 1000, transcript: "before", text: "Before.", rewritten: true)
    do {
      let library = try LocalLibrary(root: root)
      try library.saveDictionary([VocabularyEntry(term: "Clarify")]); try library.record(entry, scope: scope)
    }
    var database: OpaquePointer?
    XCTAssertEqual(sqlite3_open(root.appendingPathComponent("library.sqlite").path, &database), SQLITE_OK)
    XCTAssertEqual(sqlite3_exec(database, "DROP TABLE snippets; PRAGMA user_version=3", nil, nil, nil), SQLITE_OK)
    sqlite3_close(database)
    let upgraded = try LocalLibrary(root: root)
    XCTAssertEqual(try upgraded.dictionary().map(\.term), ["Clarify"])
    XCTAssertEqual(try upgraded.history(scope: scope).entries, [entry])
    XCTAssertEqual(try upgraded.historyBatch(scope: scope).upserts, [entry])
    XCTAssertTrue(try upgraded.snippets(scope: scope).isEmpty)
    try upgraded.saveSnippets([Snippet(trigger: "sig", replacement: "Saved\nText")], scope: scope)
    XCTAssertEqual(try upgraded.historyBatch(scope: scope).upserts, [entry])
  }
  func testMergePreservesIndependentEditsAndDetectsConflicts() throws {
    let base = Snippet(trigger: "sig", replacement: "before")
    let ours = Snippet(trigger: "sig", replacement: "ours"), theirs = Snippet(trigger: "sig", replacement: "theirs")
    XCTAssertThrowsError(try CloudAccount.mergeSnippets(base: [base], local: [ours], remote: [theirs]))
    XCTAssertEqual(try CloudAccount.mergeSnippets(base: [base], local: [ours], remote: [theirs], prefer: "remote"), [theirs])
    XCTAssertEqual(try CloudAccount.mergeSnippets(base: [base], local: [], remote: [base]), [])
    let extra = Snippet(trigger: "extra", replacement: "Extra")
    XCTAssertEqual(try CloudAccount.mergeSnippets(base: [base], local: [ours], remote: [base, extra]), [ours, extra])
    XCTAssertEqual(Snippet.vocabulary([ours]).map(\.term), ["sig"])
    XCTAssertFalse(String(describing: Snippet.vocabulary([ours])).contains("ours"))
  }
  func testAccountSizeIsBoundedWithoutChangingGuestLimits() throws {
    let entries = (0..<80).map { Snippet(trigger: "trigger \($0)", replacement: String(repeating: "é", count: 4096)) }
    XCTAssertEqual(try Snippet.validate(entries).count, 80)
    XCTAssertThrowsError(try Snippet.validateAccount(entries))
    XCTAssertEqual(try Snippet.validateAccount([Snippet(trigger: "assinatura", replacement: "João\nEngenharia")]).count, 1)
  }
  func testRemoteLibraryRejectsBooleanRevisionAndMalformedEntries() throws {
    XCTAssertThrowsError(try SnippetResponse.decode(["revision": true, "entries": []]))
    XCTAssertThrowsError(try SnippetResponse.decode(["revision": -1, "entries": []]))
    XCTAssertThrowsError(try SnippetResponse.decode(["revision": 0, "entries": [["trigger": "sig", "replacement": "Saved", "enabled": "yes", "case_sensitive": false]]]))
    XCTAssertTrue(try SnippetResponse.decode(["revision": 0, "entries": []]).entries.isEmpty)
  }
  func testServerExpansionIsUsableWithoutRewritingAndOlderResponsesStillDecode() throws {
    let result = try JSONDecoder().decode(CloudDictation.self, from: Data(#"{"transcript":"sig","text":"Signature","rewritten":false,"snippet_expanded":true}"#.utf8))
    XCTAssertTrue(result.successful)
    let old = try JSONDecoder().decode(CloudDictation.self, from: Data(#"{"transcript":"sig","text":"sig","rewritten":false}"#.utf8))
    XCTAssertFalse(old.successful); XCTAssertNil(old.snippetExpanded)
  }
}

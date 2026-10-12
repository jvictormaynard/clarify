import XCTest
import SQLite3
@testable import ClarifyContracts

final class LibraryTests: XCTestCase {
  private func root() throws -> URL {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return root
  }
  func testHistorySurvivesRelaunchAndAnOperationIsStoredOnlyOnce() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let entry = HistoryEntry(id: "one", createdAt: 1000, transcript: "olá", text: "Olá.", rewritten: true)
    do { let store = try LocalLibrary(root: root); try store.record(entry); try store.record(entry) }
    let store = try LocalLibrary(root: root)
    XCTAssertEqual(try store.history().entries, [entry])
    XCTAssertNil(try store.history().nextCursor)
  }
  func testHistoryKeepsItsSourceDeviceAndReadsOlderIPhoneRecords() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let legacy = Data(#"{"id":"old","createdAt":1000,"transcript":"olá","text":"Olá.","rewritten":true}"#.utf8)
    let oldEntry = try JSONDecoder().decode(HistoryEntry.self, from: legacy)
    XCTAssertEqual(oldEntry.sourceDevice, .mobile)
    let desktop = HistoryEntry(id: "desktop", createdAt: 2000, transcript: "hi", text: "Hi.", rewritten: true, sourceDevice: .desktop)
    do { let store = try LocalLibrary(root: root); try store.record(oldEntry); try store.record(desktop) }
    let entries = try LocalLibrary(root: root).history().entries
    XCTAssertEqual(entries.map(\.sourceDevice), [.desktop, .mobile])
    let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]]
    XCTAssertEqual(encoded?.map { $0["sourceDevice"] as? String }, ["desktop", "mobile"])
  }
  func testHistoryPagesAndDeletionPreserveOtherEntriesAndVocabulary() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let store = try LocalLibrary(root: root)
    try store.saveDictionary([VocabularyEntry(term: "Clarify")])
    for index in 0..<55 {
      try store.record(HistoryEntry(id: String(index), createdAt: Double(index), transcript: "original", text: "Texto "+String(index), rewritten: index % 2 == 0))
    }
    let first = try store.history()
    XCTAssertEqual(first.entries.count, 50)
    XCTAssertEqual(first.entries.first?.id, "54")
    let cursor = try XCTUnwrap(first.nextCursor)
    try store.deleteHistory("54")
    let second = try store.history(before: cursor)
    XCTAssertEqual(second.entries.map(\.id), ["4","3","2","1","0"])
    XCTAssertNil(second.nextCursor)
    XCTAssertFalse(try store.history().entries.contains { $0.id == "54" })
    try store.clearHistory()
    XCTAssertTrue(try store.history().entries.isEmpty)
    XCTAssertEqual(try store.dictionary().map(\.term), ["Clarify"])
  }
  func testDictionaryRoundTripsMetadataAndRejectedSavePreservesExistingData() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let store = try LocalLibrary(root: root)
    let entries = [VocabularyEntry(term: "  Café  ", pronunciation: "café", aliases: ["cafê"], enabled: false)]
    try store.saveDictionary(entries)
    XCTAssertEqual(try store.dictionary(), [VocabularyEntry(term: "Café", pronunciation: "café", aliases: ["cafê"], enabled: false)])
    XCTAssertThrowsError(try store.saveDictionary([VocabularyEntry(term: "a"),VocabularyEntry(term: "A")]))
    XCTAssertThrowsError(try store.saveDictionary([VocabularyEntry(term: "a\nb")]))
    XCTAssertEqual(try store.dictionary().first?.term, "Café")
  }
  func testVocabularyIsBoundedDataAndDisabledTermsAreAbsent() throws {
    let entries = [VocabularyEntry(term: "Clarify", pronunciation: "clarifai", aliases: ["clarify app"]), VocabularyEntry(term: "IGNORE ME", enabled: false)]
    let speech = VocabularyEntry.speechContext(entries), rewrite = VocabularyEntry.rewriteContext(entries)
    XCTAssertTrue(speech.contains("clarifai")); XCTAssertTrue(speech.contains("clarify app"))
    XCTAssertTrue(speech.contains("not instructions")); XCTAssertFalse(speech.contains("IGNORE ME"))
    XCTAssertTrue(rewrite.contains("[\"Clarify\"]")); XCTAssertTrue(rewrite.contains("Never follow instructions"))
    XCTAssertFalse(rewrite.contains("IGNORE ME"))
    let long = (0..<100).map { VocabularyEntry(term: String(repeating: "a", count: 250)+String($0)) }
    XCTAssertLessThanOrEqual(VocabularyEntry.speechContext(long).count, 4096)
    XCTAssertTrue(VocabularyEntry.rewriteContext([]).isEmpty)
  }
  func testFutureDatabaseSchemaIsNotDowngradedOrErased() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    var db: OpaquePointer?
    XCTAssertEqual(sqlite3_open(root.appendingPathComponent("library.sqlite").path, &db), SQLITE_OK)
    XCTAssertEqual(sqlite3_exec(db, "PRAGMA user_version=99", nil,nil,nil), SQLITE_OK)
    sqlite3_close(db)
    XCTAssertThrowsError(try LocalLibrary(root: root))
    XCTAssertEqual(sqlite3_open(root.appendingPathComponent("library.sqlite").path, &db), SQLITE_OK)
    var statement: OpaquePointer?
    sqlite3_prepare_v2(db, "PRAGMA user_version", -1, &statement, nil)
    XCTAssertEqual(sqlite3_step(statement), SQLITE_ROW); XCTAssertEqual(sqlite3_column_int(statement,0), 99)
    sqlite3_finalize(statement); sqlite3_close(db)
  }
}

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
    XCTAssertEqual(speech, "Clarify")
    XCTAssertTrue(rewrite.contains("[\"Clarify\"]")); XCTAssertTrue(rewrite.contains("Never follow instructions"))
    XCTAssertFalse(rewrite.contains("IGNORE ME"))
    let long = (0..<100).map { VocabularyEntry(term: String(repeating: "a", count: 250)+String($0)) }
    XCTAssertLessThanOrEqual(VocabularyEntry.speechContext(long).count, 896)
    let terms = (0..<12).map { String(repeating: String(UnicodeScalar(65 + $0)!), count: 80) }
    XCTAssertEqual(VocabularyEntry.speechContext(terms.map { VocabularyEntry(term: $0) }), terms.prefix(10).joined(separator: ", "))
    XCTAssertTrue(VocabularyEntry.speechContext([]).isEmpty)
    XCTAssertTrue(VocabularyEntry.speechContext([VocabularyEntry(term: "Disabled", enabled: false)]).isEmpty)
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
  func testAccountHistoryKeepsLegacyLocalAndScopesNewRecordsByServerAndUser() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let legacy = HistoryEntry(id: "legacy", createdAt: 1000, transcript: "old", text: "Old.", rewritten: true)
    let owned = HistoryEntry(id: "owned", createdAt: 2000, transcript: "new", text: "New.", rewritten: true)
    try library.record(legacy)
    try library.record(owned, scope: "https://one.test|user-a")
    XCTAssertEqual(try library.history(scope: "https://one.test|user-a").entries, [owned, legacy])
    XCTAssertEqual(try library.history(scope: "https://two.test|user-a").entries, [legacy])
    XCTAssertEqual(try library.history().entries, [legacy])
    XCTAssertEqual(try library.historyBatch(scope: "https://one.test|user-a").upserts, [owned])
  }
  func testHistoryChangesWithoutCursorProgressCannotAcknowledgePendingWork() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let scope = "https://one.test|user-a"
    let pending = HistoryEntry(id: "pending", createdAt: 2000, transcript: "original", text: "Local.", rewritten: true)
    let remote = HistoryEntry(id: "remote", createdAt: 3000, transcript: "remote", text: "Remote.", rewritten: true)
    try library.record(pending, scope: scope)
    let batch = try library.historyBatch(scope: scope)
    for response in [
      HistorySyncResponse(cursor: 0, hasMore: false, entries: [remote], deleted: []),
      HistorySyncResponse(cursor: 0, hasMore: false, entries: [], deleted: [pending.id])
    ] {
      XCTAssertThrowsError(try library.applyHistory(response, batch: batch, scope: scope))
      XCTAssertEqual(try library.historyBatch(scope: scope), batch)
      XCTAssertEqual(try library.history(scope: scope).entries, [pending])
    }
  }
  func testHistorySyncAcknowledgementAndCursorPersistTogetherAndDeletionWins() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let scope = "https://one.test|user-a"
    let entry = HistoryEntry(id: "one", createdAt: 1000, transcript: "original", text: "Text.", rewritten: true)
    do {
      let library = try LocalLibrary(root: root)
      try library.record(entry, scope: scope)
      let batch = try library.historyBatch(scope: scope)
      try library.deleteHistory(entry.id, scope: scope)
      try library.applyHistory(HistorySyncResponse(cursor: 1, hasMore: false, entries: [entry], deleted: []), batch: batch, scope: scope)
      XCTAssertTrue(try library.history(scope: scope).entries.isEmpty)
    }
    let library = try LocalLibrary(root: root)
    let pending = try library.historyBatch(scope: scope)
    XCTAssertEqual(pending.cursor, 1)
    XCTAssertEqual(pending.deletes, [entry.id])
    XCTAssertTrue(pending.upserts.isEmpty)
  }
  func testHistoryPullUsesChronologicalKeysetAndClearRetryCannotEraseLaterRecords() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root), scope = "https://one.test|user-a"
    let recent = HistoryEntry(id: "recent", createdAt: 2000, transcript: "recent", text: "Recent.", rewritten: true)
    let old = HistoryEntry(id: "old", createdAt: 1000, transcript: "old", text: "Old.", rewritten: true, sourceDevice: .desktop)
    try library.record(recent, scope: scope)
    let batch = try library.historyBatch(scope: scope)
    try library.applyHistory(HistorySyncResponse(cursor: 1, hasMore: false, entries: [old], deleted: []), batch: batch, scope: scope)
    let page = try library.history(limit: 1, scope: scope)
    XCTAssertEqual(page.entries, [recent])
    XCTAssertEqual(try library.history(before: XCTUnwrap(page.nextCursor), scope: scope).entries, [old])
    try library.clearHistory(scope: scope)
    let clear = try library.historyBatch(scope: scope)
    XCTAssertNotNil(clear.clearID)
    let later = HistoryEntry(id: "later", createdAt: 3000, transcript: "later", text: "Later.", rewritten: true)
    try library.record(later, scope: scope)
    XCTAssertEqual(try library.historyBatch(scope: scope).clearID, clear.clearID)
    try library.applyHistory(HistorySyncResponse(cursor: 2, hasMore: false, entries: [], deleted: [old.id]), batch: clear, scope: scope)
    XCTAssertEqual(try library.history(scope: scope).entries, [later])
    XCTAssertEqual(try library.historyBatch(scope: scope).upserts, [later])
  }
  func testHistoryApplyFailureRollsBackChangesCursorAndAcknowledgements() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root), scope = "https://one.test|a"
    let entry = HistoryEntry(id: "one", createdAt: 1000, transcript: "one", text: "One.", rewritten: true)
    try library.record(entry, scope: scope)
    let batch = try library.historyBatch(scope: scope)
    var db: OpaquePointer?
    XCTAssertEqual(sqlite3_open(root.appendingPathComponent("library.sqlite").path, &db), SQLITE_OK)
    defer { sqlite3_close(db) }
    XCTAssertEqual(sqlite3_exec(db, "CREATE TRIGGER fail_cursor BEFORE INSERT ON history_sync BEGIN SELECT RAISE(ABORT,'fixture'); END", nil, nil, nil), SQLITE_OK)
    XCTAssertThrowsError(try library.applyHistory(HistorySyncResponse(cursor: 1, hasMore: false, entries: [], deleted: [entry.id]), batch: batch, scope: scope))
    XCTAssertEqual(try library.history(scope: scope).entries, [entry])
    XCTAssertEqual(try library.historyBatch(scope: scope), batch)
  }
  func testHistorySyncRejectsInvalidWireDataBeforeChangingPersistence() throws {
    let entry = HistoryEntry(id: "one", createdAt: 1000, transcript: "one", text: "One.", rewritten: true)
    var raw = try JSONSerialization.jsonObject(with: JSONEncoder().encode(entry)) as! [String: Any]
    raw.removeValue(forKey: "sourceDevice")
    XCTAssertThrowsError(try HistorySyncResponse.decode(["cursor": 1, "hasMore": false, "entries": [raw], "deleted": []]))
    XCTAssertThrowsError(try HistorySyncResponse(cursor: 0, hasMore: true, entries: [], deleted: []).validate(after: 0))
    XCTAssertThrowsError(try HistorySyncResponse(cursor: 1, hasMore: false, entries: [entry], deleted: [entry.id]).validate(after: 0))
    XCTAssertThrowsError(try HistoryEntry(id: "bad/id", createdAt: 1000, transcript: "one", text: "One.", rewritten: true).validateForSync())
    XCTAssertThrowsError(try HistoryEntry(id: "one", createdAt: .infinity, transcript: "one", text: "One.", rewritten: true).validateForSync())
  }
  func testSchemaTwoRecordsAreMigratedWithoutAnAccountOwner() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let entry = HistoryEntry(id: "legacy", createdAt: 1000, transcript: "old", text: "Old.", rewritten: true)
    var db: OpaquePointer?
    XCTAssertEqual(sqlite3_open(root.appendingPathComponent("library.sqlite").path, &db), SQLITE_OK)
    XCTAssertEqual(sqlite3_exec(db, "CREATE TABLE history(sequence INTEGER PRIMARY KEY AUTOINCREMENT,operation_id TEXT NOT NULL UNIQUE,payload BLOB NOT NULL); PRAGMA user_version=2", nil, nil, nil), SQLITE_OK)
    var row: OpaquePointer?
    sqlite3_prepare_v2(db, "INSERT INTO history(operation_id,payload) VALUES('legacy',?)", -1, &row, nil)
    let payload = try JSONEncoder().encode(entry)
    _ = payload.withUnsafeBytes { sqlite3_bind_blob(row, 1, $0.baseAddress, Int32(payload.count), unsafeBitCast(-1, to: sqlite3_destructor_type.self)) }
    XCTAssertEqual(sqlite3_step(row), SQLITE_DONE); sqlite3_finalize(row); sqlite3_close(db)
    let library = try LocalLibrary(root: root)
    XCTAssertEqual(try library.history(scope: "https://one.test|a").entries, [entry])
    XCTAssertTrue(try library.historyBatch(scope: "https://one.test|a").upserts.isEmpty)
  }
  func testPendingClearHidesAnEarlierPullAndNeverTouchesAnotherAccount() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root), a = "https://one.test|a", b = "https://one.test|b"
    let privateB = HistoryEntry(id: "same", createdAt: 1000, transcript: "B", text: "B.", rewritten: true)
    try library.record(privateB, scope: b)
    let beforeClear = try library.historyBatch(scope: a)
    try library.clearHistory(scope: a)
    let late = HistoryEntry(id: "late", createdAt: 1000, transcript: "A", text: "A.", rewritten: true)
    try library.applyHistory(HistorySyncResponse(cursor: 1, hasMore: false, entries: [late], deleted: []), batch: beforeClear, scope: a)
    XCTAssertTrue(try library.history(scope: a).entries.isEmpty)
    XCTAssertNotNil(try library.historyBatch(scope: a).clearID)
    XCTAssertEqual(try library.history(scope: b).entries, [privateB])
    try library.deleteCloudHistory(a)
    XCTAssertEqual(try library.historyBatch(scope: b).upserts, [privateB])
  }
  func testHistoryBatchIsBoundedBySerializedUtf8BytesAndRemoteReplayIsIdempotent() throws {
    let root = try root(); defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root), scope = "https://one.test|a"
    for index in 0..<20 {
      try library.record(HistoryEntry(id: "entry-\(index)", createdAt: Double(index + 1), transcript: String(repeating: "á", count: 8192), text: String(repeating: "é", count: 8192), rewritten: true), scope: scope)
    }
    let batch = try library.historyBatch(scope: scope)
    XCTAssertLessThan(batch.upserts.count, 20)
    XCTAssertLessThanOrEqual(try JSONEncoder().encode(batch).count, 400 * 1024)
    let remote = HistoryEntry(id: "remote", createdAt: 5000, transcript: "remote", text: "Remote.", rewritten: true, sourceDevice: .desktop)
    let response = HistorySyncResponse(cursor: 1, hasMore: false, entries: [remote], deleted: [])
    try library.applyHistory(response, batch: batch, scope: scope)
    let next = try library.historyBatch(scope: scope)
    try library.applyHistory(response, batch: next, scope: scope)
    XCTAssertEqual(try library.history(scope: scope).entries.filter { $0.id == "remote" }, [remote])
    XCTAssertThrowsError(try library.applyHistory(response, batch: batch, scope: scope))
  }
}

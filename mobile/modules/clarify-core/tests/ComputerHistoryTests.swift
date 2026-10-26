import Foundation
import SQLite3
import XCTest
@testable import ClarifyContracts

final class ComputerHistoryTests: XCTestCase {
  private let computer = UUID(uuidString: "4BE646DB-0E41-41BE-8BD9-D72885FC1AAD")!
  private func credential(_ address: String, computerID: UUID? = nil) -> ComputerCredential {
    ComputerCredential(computerID: computerID ?? computer, computerName: "Fixture", deviceID: UUID(),
      sessionToken: String(repeating: "x", count: 43),
      routes: [ComputerRoute(url: address, certificateSHA256: String(repeating: "a", count: 64))])
  }
  private func database(_ root: URL, _ body: (OpaquePointer) throws -> Void) throws {
    var db: OpaquePointer?
    guard sqlite3_open(root.appendingPathComponent("library.sqlite").path, &db) == SQLITE_OK, let db else {
      sqlite3_close(db); throw NSError(domain: "FixtureSQLite", code: 1)
    }
    defer { sqlite3_close(db) }
    try body(db)
  }
  // Seed the exact old owner format without passing through the new writer.
  private func legacy(_ entry: HistoryEntry, scope: String, root: URL) throws {
    try database(root) { db in
      var row: OpaquePointer?
      XCTAssertEqual(sqlite3_prepare_v2(db, "INSERT INTO history(operation_id,owner,created_at,payload) VALUES(?,?,?,?)", -1, &row, nil), SQLITE_OK)
      defer { sqlite3_finalize(row) }
      let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
      sqlite3_bind_text(row, 1, entry.id, -1, transient); sqlite3_bind_text(row, 2, scope, -1, transient)
      sqlite3_bind_double(row, 3, entry.createdAt)
      let payload = try JSONEncoder().encode(entry)
      _ = payload.withUnsafeBytes { sqlite3_bind_blob(row, 4, $0.baseAddress, Int32(payload.count), transient) }
      XCTAssertEqual(sqlite3_step(row), SQLITE_DONE)
    }
  }
  private func entry(_ id: String, time: TimeInterval = 1000) -> HistoryEntry {
    HistoryEntry(id: id, createdAt: time, transcript: "Original", text: "Saved", rewritten: true)
  }
  func testSameComputerRouteChangeReadsPagesAndDeletesOldOwnersWithoutCrossingScopes() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let routeA = "https://192.168.1.12:47653", routeB = "https://10.0.0.9:47653"
    let first = credential(routeA), changed = credential(routeB)
    let stable = "computer|4be646db-0e41-41be-8bd9-d72885fc1aad"
    XCTAssertEqual(first.scope, stable); XCTAssertEqual(changed.scope, stable)
    let oldA = entry("route-a", time: 1001), oldB = entry("route-b", time: 1002), current = entry("current", time: 1003)
    try legacy(oldA, scope: stable + "|" + routeA, root: root)
    try legacy(oldB, scope: stable + "|" + routeB, root: root)
    try library.record(oldA, scope: changed.scope)
    try library.record(current, scope: changed.scope)
    XCTAssertFalse(try library.historyBatch(scope: changed.scope).hasWork)
    let guest = entry("guest"), account = entry("account"), other = entry("route-a")
    let accountScope = "https://account.example.com|" + UUID().uuidString
    let otherScope = credential(routeB, computerID: UUID()).scope
    try library.record(guest); try library.record(account, scope: accountScope)
    try library.record(other, scope: otherScope)
    let page = try library.history(limit: 1, scope: changed.scope, includeLocal: false)
    XCTAssertEqual(page.entries, [current]); XCTAssertEqual(page.localEntries, [false])
    XCTAssertEqual(try library.history(before: XCTUnwrap(page.nextCursor), scope: changed.scope, includeLocal: false).entries, [oldB, oldA])
    try library.deleteHistory(oldA.id, scope: changed.scope)
    XCTAssertFalse(try library.historyBatch(scope: changed.scope).hasWork)
    // A late old-route writer cannot restore a deleted local operation.
    try library.record(oldA, scope: stable + "|" + routeA)
    XCTAssertEqual(try library.history(scope: changed.scope, includeLocal: false).entries, [current, oldB])
    try library.clearHistory(scope: changed.scope, includeLocal: false)
    XCTAssertFalse(try library.historyBatch(scope: changed.scope).hasWork)
    try library.record(oldB, scope: stable + "|" + routeB)
    XCTAssertTrue(try library.history(scope: first.scope, includeLocal: false).entries.isEmpty)
    XCTAssertEqual(try library.history().entries, [guest])
    XCTAssertEqual(try library.history(scope: accountScope, includeLocal: false).entries, [account])
    XCTAssertEqual(try library.history(scope: otherScope, includeLocal: false).entries, [other])
    XCTAssertEqual(try library.historyBatch(scope: accountScope).upserts, [account])
    XCTAssertEqual(try LocalLibrary(root: root).history(scope: stable, includeLocal: false).entries, [])
  }
  func testFailedCompatibilityDeleteRollsBackAndReadsDoNotRequireMigrationWrites() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let scope = "computer|4be646db-0e41-41be-8bd9-d72885fc1aad"
    let saved = entry("preserved")
    try legacy(saved, scope: scope + "|https://192.168.1.12:47653", root: root)
    try database(root) { db in
      XCTAssertEqual(sqlite3_exec(db, "BEGIN IMMEDIATE", nil, nil, nil), SQLITE_OK)
      defer { sqlite3_exec(db, "ROLLBACK", nil, nil, nil) }
      XCTAssertEqual(try library.history(scope: scope, includeLocal: false).entries, [saved])
    }
    try database(root) { db in
      XCTAssertEqual(sqlite3_exec(db, "CREATE TRIGGER refuse_history_delete BEFORE DELETE ON history BEGIN SELECT RAISE(ABORT,'fixture write failure'); END", nil, nil, nil), SQLITE_OK)
    }
    XCTAssertThrowsError(try library.deleteHistory(saved.id, scope: scope))
    XCTAssertThrowsError(try library.clearHistory(scope: scope, includeLocal: false))
    XCTAssertEqual(try LocalLibrary(root: root).history(scope: scope, includeLocal: false).entries, [saved])
    try database(root) { db in
      var row: OpaquePointer?
      XCTAssertEqual(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM history_deleted", -1, &row, nil), SQLITE_OK)
      XCTAssertEqual(sqlite3_step(row), SQLITE_ROW); XCTAssertEqual(sqlite3_column_int(row, 0), 0)
      sqlite3_finalize(row)
      XCTAssertEqual(sqlite3_exec(db, "DROP TRIGGER refuse_history_delete", nil, nil, nil), SQLITE_OK)
    }
    try library.deleteHistory(saved.id, scope: scope)
    XCTAssertTrue(try library.history(scope: scope, includeLocal: false).entries.isEmpty)
  }
}

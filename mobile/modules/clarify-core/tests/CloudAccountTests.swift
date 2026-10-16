import XCTest
@testable import ClarifyContracts

final class CloudAccountTests: XCTestCase {
  private func response(_ request: URLRequest, _ value: [String: Any], status: Int = 200) throws -> (Data, HTTPURLResponse) {
    (try JSONSerialization.data(withJSONObject: value), HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
  }
  @MainActor func testGuestHistoryNeverSendsRequestsAndExistingRowsNeverUpload() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let old = HistoryEntry(id: "old", createdAt: 1000, transcript: "old", text: "Old.", rewritten: true)
    try library.record(old)
    var requests: [HistorySyncBatch] = []
    let transport: (URLRequest) async throws -> (Data, HTTPURLResponse) = { request in
      requests.append(try JSONDecoder().decode(HistorySyncBatch.self, from: request.httpBody!))
      return try self.response(request, ["cursor": 1, "hasMore": false, "entries": [], "deleted": []])
    }
    let guest = CloudAccount(defaults: defaults, transport: transport, readCredential: { nil }, saveCredential: { _ in })
    _ = await guest.syncHistory(library, force: true)
    XCTAssertTrue(requests.isEmpty)
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let account = CloudAccount(defaults: defaults, transport: transport, readCredential: { "fixture" }, saveCredential: { _ in })
    let fresh = HistoryEntry(id: "fresh", createdAt: 2000, transcript: "fresh", text: "Fresh.", rewritten: true)
    try library.record(fresh, scope: account.historyScope)
    _ = await account.syncHistory(library, force: true)
    XCTAssertEqual(requests.count, 1)
    XCTAssertEqual(requests.first?.upserts, [fresh])
    XCTAssertEqual(try library.history().entries, [old])
    XCTAssertEqual(try library.history(scope: account.historyScope).entries, [fresh, old])
  }
  @MainActor func testFailedHistoryKeepsDurableOutboxAndRetriesWithoutPollingStorm() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var count = 0, now = 0.0
    let account = CloudAccount(defaults: defaults, transport: { request in
      count += 1
      if count == 1 { throw URLError(.notConnectedToInternet) }
      return try self.response(request, ["cursor": 1, "hasMore": false, "entries": [], "deleted": []])
    }, readCredential: { "fixture" }, saveCredential: { _ in }, historyClock: { now })
    let scope = try XCTUnwrap(account.historyScope)
    let entry = HistoryEntry(id: "one", createdAt: 1000, transcript: "one", text: "One.", rewritten: true)
    do { let library = try LocalLibrary(root: root); try library.record(entry, scope: scope); _ = await account.syncHistory(library, force: true) }
    let library = try LocalLibrary(root: root)
    XCTAssertEqual(try library.historyBatch(scope: scope).upserts, [entry])
    _ = await account.syncHistory(library, force: true)
    XCTAssertEqual(count, 1)
    now = 61
    _ = await account.syncHistory(library)
    XCTAssertEqual(count, 2)
    XCTAssertTrue(try library.historyBatch(scope: scope).upserts.isEmpty)
    XCTAssertEqual(try library.historyBatch(scope: scope).cursor, 1)
    _ = await account.syncHistory(library)
    XCTAssertEqual(count, 2)
  }
  @MainActor func testLateHistoryUnauthorizedResponseCannotChangeNewSessionOrGuestCache() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var pending: CheckedContinuation<(Data, HTTPURLResponse), Error>?
    var historyRequest: URLRequest?, token: String? = "fixture"
    let account = CloudAccount(defaults: defaults, transport: { request in
      if request.url!.path == "/v1/history/sync" {
        historyRequest = request
        return try await withCheckedThrowingContinuation { pending = $0 }
      }
      return try self.response(request, [:], status: 204)
    }, readCredential: { token }, saveCredential: { token = $0 })
    let library = try LocalLibrary(root: root), oldScope = try XCTUnwrap(account.historyScope)
    let entry = HistoryEntry(id: "private", createdAt: 1000, transcript: "private", text: "Private.", rewritten: true)
    try library.record(entry, scope: oldScope)
    let task = Task { await account.syncHistory(library, force: true) }
    while pending == nil { await Task.yield() }
    _ = try await account.command("logout", value: "", library: library)
    token = "new-session"
    pending!.resume(returning: try response(historyRequest!, [:], status: 401))
    _ = await task.value
    XCTAssertEqual(token, "new-session")
    XCTAssertNil(account.historyScope)
    XCTAssertTrue(try library.history().entries.isEmpty)
    XCTAssertEqual(try library.historyBatch(scope: oldScope).upserts, [entry])
  }
  @MainActor func testExpiredSessionKeepsHistoryInAccountScopeAndRejectsOldRecording() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var token: String? = "fixture"
    let account = CloudAccount(defaults: defaults, transport: { request in try self.response(request, [:], status: 401) }, readCredential: { token }, saveCredential: { token = $0 })
    let library = try LocalLibrary(root: root), scope = account.historyScope, capture = account.captureHistory()
    _ = await account.syncHistory(library, force: true)
    XCTAssertNil(account.scope)
    XCTAssertEqual(account.historyScope, scope)
    XCTAssertTrue(account.managed)
    XCTAssertFalse(account.acceptsHistory(capture))
    XCTAssertFalse(account.configured)
  }
  func testExistingSignedInAccountProcessesWithoutSeparateActivation() throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    var state = CloudAccountState()
    state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let account = CloudAccount(defaults: defaults)
    XCTAssertTrue(account.hosted)
    XCTAssertTrue(account.managed)
    XCTAssertEqual(account.snapshot()["hosted"] as? Bool, true)
  }
  func testSavingAnOpenDraftPreservesWordsReceivedDuringAutomaticRefresh() throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    let account = CloudAccount(defaults: defaults), library = try LocalLibrary(root: root)
    let original = VocabularyEntry(term: "A"), remote = VocabularyEntry(term: "Remote")
    try library.saveDictionary([original, remote])
    let edit = VocabularyEntry(term: "A", pronunciation: "ours")
    try account.saveDictionaryDraft([edit], base: [original], library: library)
    XCTAssertEqual(try library.dictionary(), [edit, remote])
    XCTAssertThrowsError(try account.saveDictionaryDraft([VocabularyEntry(term: "A", pronunciation: "other")], base: [original], library: library))
    XCTAssertEqual(try library.dictionary(), [edit, remote])
  }
  func testExpiredManagedSessionCannotUsePersonalCredentials() throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    var state = CloudAccountState()
    state.hosted = true
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let account = CloudAccount(defaults: defaults)
    XCTAssertTrue(account.managed)
    XCTAssertFalse(account.hosted)
    XCTAssertFalse(account.configured)
  }
  func testFirstAccountCacheImportsGuestWordsOnceWithoutChangingGuestData() throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState()
    state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let account = CloudAccount(defaults: defaults)
    let library = try LocalLibrary(root: root)
    try library.saveDictionary([VocabularyEntry(term: "Guest")])
    try account.prepareLibrary(library)
    try library.saveDictionary([VocabularyEntry(term: "Account")], scope: account.scope)
    try account.prepareLibrary(library)
    XCTAssertEqual(try library.dictionary().map(\.term), ["Guest"])
    XCTAssertEqual(try library.dictionary(scope: account.scope).map(\.term), ["Account"])
  }
  func testEndpointRejectsCredentialBearingURLsAndAllowsLocalSelfHosting() throws {
    for value in ["http://example.com", "https://user:secret@example.com", "https://example.com/path", "https://example.com?token=secret", "file:///tmp/x"] {
      XCTAssertThrowsError(try CloudAccount.validateEndpoint(value))
    }
    XCTAssertEqual(try CloudAccount.validateEndpoint("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")
    XCTAssertEqual(try CloudAccount.validateEndpoint("HTTPS://EXAMPLE.COM:443/"), "https://example.com")
  }
  func testIndependentEditsMergeAndDeletedWordsStayDeleted() throws {
    let a = VocabularyEntry(term: "A"), b = VocabularyEntry(term: "B")
    let merged = try CloudAccount.merge(base: [a, b], local: [b, VocabularyEntry(term: "Local")],
      remote: [a, b, VocabularyEntry(term: "Remote")])
    XCTAssertEqual(Set(merged.map(\.term)), Set(["B", "Local", "Remote"]))
  }
  func testConcurrentChangeOfSameWordRequiresResolution() {
    XCTAssertThrowsError(try CloudAccount.merge(base: [VocabularyEntry(term: "A")],
      local: [VocabularyEntry(term: "A", pronunciation: "ours")],
      remote: [VocabularyEntry(term: "A", pronunciation: "theirs")]))
  }
  func testAccountDictionariesCannotLeakIntoAnotherAccountOrLocalDictionary() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let a = UUID().uuidString, b = UUID().uuidString
    try library.saveDictionary([VocabularyEntry(term: "Local")])
    try library.saveCloudDictionary(CloudDictionary(entries: [VocabularyEntry(term: "Private A")], base: [], revision: 0), scope: a)
    try library.saveDictionary([VocabularyEntry(term: "Private B")], scope: b)
    XCTAssertEqual(try library.dictionary().map(\.term), ["Local"])
    XCTAssertEqual(try library.dictionary(scope: a).map(\.term), ["Private A"])
    XCTAssertEqual(try library.dictionary(scope: b).map(\.term), ["Private B"])
    try library.deleteCloudDictionary(a)
    XCTAssertTrue(try library.dictionary(scope: a).isEmpty)
    XCTAssertEqual(try library.dictionary(scope: b).map(\.term), ["Private B"])
  }
}

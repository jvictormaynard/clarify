import XCTest
@testable import ClarifyContracts

final class CloudSnippetTests: XCTestCase {
  private func response(_ request: URLRequest, _ value: [String: Any], status: Int = 200) throws -> (Data, HTTPURLResponse) {
    (try JSONSerialization.data(withJSONObject: value), HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
  }
  @MainActor func testSyncRoundTripKeepsGuestSeparateAndPreservesConflictingAccountEdits() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var remote: [[String: Any]] = [], revision = 0, writes = 0
    let account = CloudAccount(defaults: defaults, transport: { request in
      if request.url!.path == "/v1/dictionary" { return try self.response(request, ["revision": 0, "entries": []]) }
      XCTAssertEqual(request.url!.path, "/v1/snippets")
      if request.httpMethod == "PUT" {
        let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
        XCTAssertEqual(body["revision"] as? Int, revision)
        remote = body["entries"] as! [[String: Any]]; revision += 1; writes += 1
      }
      return try self.response(request, ["revision": revision, "entries": remote])
    }, readCredential: { "fixture" }, saveCredential: { _ in })
    let library = try LocalLibrary(root: root), owner = try XCTUnwrap(account.snippetScope)
    let guest = Snippet(trigger: "guest", replacement: "Guest secret")
    try library.saveSnippets([guest])
    _ = try await account.command("sync", value: "", library: library)
    XCTAssertTrue(remote.isEmpty); XCTAssertEqual(writes, 0)
    let initial = Snippet(trigger: "sig", replacement: "First\nSignature")
    try account.saveSnippetDraft([initial], base: [], context: account.historyContext, library: library)
    _ = try await account.command("sync", value: "", library: library)
    XCTAssertEqual(writes, 1); XCTAssertEqual(try library.cloudSnippets(owner).base, [initial])
    let local = Snippet(trigger: "sig", replacement: "Local"), other = Snippet(trigger: "sig", replacement: "Desktop")
    try account.saveSnippetDraft([local], base: [initial], context: account.historyContext, library: library)
    remote = try JSONSerialization.jsonObject(with: JSONEncoder().encode([other])) as! [[String: Any]]; revision += 1
    do { _ = try await account.command("sync", value: "", library: library); XCTFail("A conflict requires a choice") }
    catch { XCTAssertEqual(account.snapshot()["dictionaryConflict"] as? Bool, true) }
    XCTAssertEqual(try library.snippets(scope: owner), [local]); XCTAssertEqual(try library.snippets(), [guest])
    _ = try await account.command("sync-remote", value: "", library: library)
    XCTAssertEqual(try library.snippets(scope: owner), [other]); XCTAssertEqual(writes, 1)
  }
  @MainActor func testLateSnippetResponseCannotChangeNewSessionOrPersistTheOldResult() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var token: String? = "old", pending: CheckedContinuation<(Data, HTTPURLResponse), Error>?, snippetRequest: URLRequest?
    let account = CloudAccount(defaults: defaults, transport: { request in
      if request.url!.path == "/v1/dictionary" { return try self.response(request, ["revision": 0, "entries": []]) }
      snippetRequest = request
      return try await withCheckedThrowingContinuation { pending = $0 }
    }, readCredential: { token }, saveCredential: { token = $0 })
    let library = try LocalLibrary(root: root), owner = try XCTUnwrap(account.snippetScope)
    let task = Task { try await account.command("sync", value: "", library: library) }
    while pending == nil { await Task.yield() }
    token = "new"
    pending!.resume(returning: try response(snippetRequest!, ["revision": 1, "entries": []]))
    do { _ = try await task.value; XCTFail("The stale response must be rejected") } catch is CancellationError {}
    XCTAssertEqual(token, "new"); XCTAssertTrue(account.hosted); XCTAssertFalse(account.isBusy)
    XCTAssertNil(try library.cloudSnippets(owner).revision)
  }
  @MainActor func testOldEditorCannotSaveAfterAccountTransition() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    let account = CloudAccount(defaults: defaults, readCredential: { nil }, saveCredential: { _ in })
    let library = try LocalLibrary(root: root), context = account.historyContext
    _ = try await account.command("configure", value: "https://two.test", library: library)
    XCTAssertThrowsError(try account.saveSnippetDraft([Snippet(trigger: "sig", replacement: "Private")], base: [], context: context, library: library))
    XCTAssertTrue(try library.snippets().isEmpty)
  }
}

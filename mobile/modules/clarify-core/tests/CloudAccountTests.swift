import XCTest
@testable import ClarifyContracts

final class CloudAccountTests: XCTestCase {
  @MainActor func testSelectedTextUsesAccountSessionAndExplicitTranslationTarget() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    var requests: [URLRequest] = []
    let account = CloudAccount(defaults: f.defaults, transport: { request in
      requests.append(request)
      return try f.response(request, ["text": "Hi, how are you?", "usage": ["used_ms": 0]])
    }, readCredential: { f.token }, saveCredential: { f.token = $0 })
    for action in ["rewrite", "translate"] {
      let id = UUID().uuidString
      let result = try await account.processText(id, action: action, text: "Oi, tudo bem?", language: "en")
      XCTAssertEqual(result.text, "Hi, how are you?"); XCTAssertTrue(result.successful)
      let request = try XCTUnwrap(requests.last)
      XCTAssertEqual(request.url?.absoluteString, "https://one.test/v1/text")
      XCTAssertEqual(request.httpMethod, "POST")
      XCTAssertEqual(request.value(forHTTPHeaderField: "X-Session-Token"), "fixture")
      let body = try XCTUnwrap(JSONSerialization.jsonObject(with: try XCTUnwrap(request.httpBody)) as? [String: String])
      XCTAssertEqual(body, ["operation_id": id, "action": action, "text": "Oi, tudo bem?", "language": "en"])
      XCTAssertFalse(account.isBusy)
    }
    XCTAssertEqual(requests.count, 2, "One request per action, without audio or automatic retries")
  }
  @MainActor func testSelectedTextRejectsInvalidInputAndDoesNotRetryQuotaOrMalformedResults() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    var requests = 0, status = 429
    var response: [String: Any] = ["code": "allowance_exhausted"]
    let account = CloudAccount(defaults: f.defaults, transport: { request in
      requests += 1; return try f.response(request, response, status)
    }, readCredential: { f.token }, saveCredential: { f.token = $0 })
    let id = UUID().uuidString
    for (operation, action, text, language) in [("invalid", "rewrite", "Text", "en"),
      (id, "dictate", "Text", "en"), (id, "rewrite", "Text", "xx"),
      (id, "translate", " ", "pt"), (id, "rewrite", String(repeating: "é", count: 8001), "auto")] {
      do { _ = try await account.processText(operation, action: action, text: text, language: language); XCTFail("Invalid text input accepted") }
      catch let error as ClarifyError { XCTAssertEqual(error.code, "invalid_text_request") }
    }
    XCTAssertEqual(requests, 0)
    do { _ = try await account.processText(id, action: "rewrite", text: "Text", language: "auto"); XCTFail("Quota error accepted") }
    catch let error as ClarifyError { XCTAssertEqual(error.code, "allowance_exhausted") }
    XCTAssertEqual(requests, 1); XCTAssertFalse(account.isBusy)
    status = 200
    for output in [" ", String(repeating: "é", count: 32_001)] {
      response = ["text": output]
      do { _ = try await account.processText(UUID().uuidString, action: "translate", text: "Text", language: "pt"); XCTFail("Invalid result accepted") }
      catch is ClarifyError {}
    }
    XCTAssertEqual(requests, 3); XCTAssertFalse(account.isBusy)
  }
  @MainActor func testLateSelectedTextResponseCannotEnterAnotherSession() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    var pending: CheckedContinuation<(Data, HTTPURLResponse), Error>?, sent: URLRequest?
    let account = CloudAccount(defaults: f.defaults, transport: { request in
      sent = request; return try await withCheckedThrowingContinuation { pending = $0 }
    }, readCredential: { f.token }, saveCredential: { f.token = $0 })
    let task = Task { try await account.processText(UUID().uuidString, action: "rewrite", text: "Original", language: "auto") }
    while pending == nil { await Task.yield() }
    f.token = "new-session"
    pending!.resume(returning: try f.response(try XCTUnwrap(sent), ["text": "Stale result", "usage": ["used_ms": 999]]))
    do { _ = try await task.value; XCTFail("Stale result accepted") }
    catch is CancellationError {}
    XCTAssertEqual(f.token, "new-session"); XCTAssertFalse(account.isBusy)
    XCTAssertNil((account.snapshot()["usage"] as? [String: Any])?["used_ms"])
  }
  @MainActor private final class ActivationFixture {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let user = UUID().uuidString
    let defaults: UserDefaults
    let library: LocalLibrary
    var token: String? = "fixture"
    var responseUser: String?
    var status = 200
    var failure: Error?
    var suspended: CheckedContinuation<Void, Never>?
    var onRequest: (() -> Void)?
    var paths: [String] = []
    lazy var account = CloudAccount(defaults: defaults, transport: { request in
      self.paths.append(request.url!.path)
      if request.url!.path == "/v1/account" {
        await withCheckedContinuation { self.suspended = $0; self.onRequest?() }
        if let failure = self.failure { throw failure }
        return try self.response(request, ["id": self.responseUser ?? self.user, "email": "fixture@example.test"], self.status)
      }
      if request.httpMethod == "DELETE" { return try self.response(request, [:], 204) }
      return try self.response(request, ["revision": 0, "entries": []])
    }, readCredential: { self.token }, saveCredential: { self.token = $0 })
    init() throws {
      defaults = UserDefaults(suiteName: suite)!
      library = try LocalLibrary(root: root)
      var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = user
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    }
    func response(_ request: URLRequest, _ json: [String: Any], _ status: Int = 200) throws -> (Data, HTTPURLResponse) {
      (try JSONSerialization.data(withJSONObject: json), HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
    }
    func resume() { suspended?.resume(); suspended = nil }
    func cleanup() {
      resume(); defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root)
    }
  }
  @MainActor func testActivationWaitsForAutomaticRefreshWithoutTakingAccountOwnership() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    let refreshing = expectation(description: "automatic refresh suspended")
    f.onRequest = { refreshing.fulfill() }
    let automatic = Task { try await f.account.command("auto", value: "", library: f.library) }
    await fulfillment(of: [refreshing], timeout: 2)
    var prepared = false, activations = 0
    let entered = expectation(description: "activation entered")
    let activation = Task { @MainActor in
      entered.fulfill()
      try await f.account.withActivationAccount(prepare: { prepared = true }, activate: {
        XCTAssertFalse(f.account.isBusy); activations += 1
      })
    }
    await fulfillment(of: [entered], timeout: 2)
    XCTAssertTrue(f.account.isBusy); XCTAssertFalse(prepared); XCTAssertEqual(activations, 0)
    f.resume(); _ = try await automatic.value
    try await activation.value
    XCTAssertTrue(prepared); XCTAssertEqual(activations, 1); XCTAssertFalse(f.account.isBusy)
    XCTAssertEqual(f.paths, ["/v1/account", "/v1/dictionary", "/v1/snippets"])
  }
  @MainActor func testActivationRejectsInteractiveAccountWorkWithoutWaiting() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    let refreshing = expectation(description: "explicit refresh suspended")
    f.onRequest = { refreshing.fulfill() }
    let interactive = Task { try await f.account.command("refresh", value: "", library: f.library) }
    await fulfillment(of: [refreshing], timeout: 2)
    let rejected = expectation(description: "activation rejected before explicit refresh ends")
    let activation = Task { @MainActor in
      do {
        try await f.account.withActivationAccount(prepare: { XCTFail("Busy account must not request permission") },
          activate: { XCTFail("Busy account must not start audio") })
        XCTFail("Explicit account work must exclude activation")
      } catch let error as ClarifyError { XCTAssertEqual(error.localizedDescription, L("Aguarde a operação da conta.")) }
      rejected.fulfill()
    }
    await fulfillment(of: [rejected], timeout: 2)
    XCTAssertTrue(f.account.isBusy)
    f.resume(); _ = try await interactive.value; try await activation.value
  }
  @MainActor func testActivationWaitsForRefreshStartedDuringPermissionAndChecksForegroundLast() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    let permission = expectation(description: "permission suspended"), refreshing = expectation(description: "automatic refresh suspended")
    var permissionContinuation: CheckedContinuation<Void, Never>?
    var foreground = true, activations = 0
    let activation = Task { @MainActor in
      try await f.account.withActivationAccount(prepare: {
        await withCheckedContinuation { permissionContinuation = $0; permission.fulfill() }
      }, activate: {
        guard foreground else { throw ClarifyError("foreground") }
        activations += 1
      })
    }
    await fulfillment(of: [permission], timeout: 2)
    f.onRequest = { refreshing.fulfill() }
    let automatic = Task { try await f.account.command("auto", value: "", library: f.library) }
    await fulfillment(of: [refreshing], timeout: 2)
    permissionContinuation?.resume()
    await Task.yield()
    XCTAssertTrue(f.account.isBusy); XCTAssertEqual(activations, 0)
    foreground = false
    f.resume(); _ = try await automatic.value
    do { try await activation.value; XCTFail("Background activation must fail after the refresh wait") }
    catch let error as ClarifyError { XCTAssertEqual(error.message, "foreground") }
    XCTAssertEqual(activations, 0); XCTAssertFalse(f.account.isBusy)
  }
  @MainActor func testActivationRejectsRevocationAccountChangeAndReplacedCredentialDuringRefresh() async throws {
    for change in ["expired", "account", "credential"] {
      let f = try ActivationFixture(); defer { f.cleanup() }
      let refreshing = expectation(description: "automatic refresh suspended")
      f.onRequest = { refreshing.fulfill() }
      let automatic = Task { try await f.account.command("auto", value: "", library: f.library) }
      await fulfillment(of: [refreshing], timeout: 2)
      let entered = expectation(description: "activation entered")
      let activation = Task { @MainActor in
        entered.fulfill()
        try await f.account.withActivationAccount(prepare: { XCTFail("Changed session must not request permission") },
          activate: { XCTFail("Changed session must not start audio") })
      }
      await fulfillment(of: [entered], timeout: 2)
      if change == "expired" { f.status = 401 }
      if change == "account" { f.responseUser = UUID().uuidString }
      if change == "credential" { f.token = "replacement-fixture" }
      f.resume(); _ = try await automatic.value
      do { try await activation.value; XCTFail("Activation must retain its original account") }
      catch is CancellationError {}
      catch is ClarifyError { XCTAssertFalse(f.account.configured) }
      XCTAssertFalse(f.account.isBusy)
    }
  }
  @MainActor func testCancellingActivationLeavesAutomaticRefreshRunning() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    let refreshing = expectation(description: "automatic refresh suspended")
    f.onRequest = { refreshing.fulfill() }
    let automatic = Task { try await f.account.command("auto", value: "", library: f.library) }
    await fulfillment(of: [refreshing], timeout: 2)
    let entered = expectation(description: "activation entered"), cancelled = expectation(description: "activation cancelled during refresh")
    let activation = Task { @MainActor in
      entered.fulfill()
      do {
        try await f.account.withActivationAccount(prepare: { XCTFail("Cancelled activation must not request permission") },
          activate: { XCTFail("Cancelled activation must not start audio") })
        XCTFail("Cancelled activation must fail")
      } catch is CancellationError {}
      cancelled.fulfill()
    }
    await fulfillment(of: [entered], timeout: 2)
    activation.cancel()
    await fulfillment(of: [cancelled], timeout: 2)
    XCTAssertTrue(f.account.isBusy); XCTAssertNotNil(f.suspended); XCTAssertEqual(f.token, "fixture")
    f.resume(); _ = try await automatic.value; try await activation.value
    XCTAssertTrue(f.account.configured); XCTAssertFalse(f.account.isBusy)
  }
  @MainActor func testOfflineAutomaticRefreshStillAllowsActivationOfTheSameSignedInAccount() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    f.failure = URLError(.notConnectedToInternet)
    let refreshing = expectation(description: "automatic refresh suspended")
    f.onRequest = { refreshing.fulfill() }
    let automatic = Task { try await f.account.command("auto", value: "", library: f.library) }
    await fulfillment(of: [refreshing], timeout: 2)
    var activations = 0
    let entered = expectation(description: "activation entered")
    let activation = Task { @MainActor in
      entered.fulfill()
      try await f.account.withActivationAccount(prepare: {}, activate: { activations += 1 })
    }
    await fulfillment(of: [entered], timeout: 2)
    f.resume(); _ = try await automatic.value; try await activation.value
    XCTAssertEqual(activations, 1); XCTAssertTrue(f.account.configured)
  }
  @MainActor func testActivationRechecksSignoutEndpointAndCredentialsAfterPermissionWait() async throws {
    for change in ["logout", "endpoint", "credential", "cancel"] {
      let f = try ActivationFixture(); defer { f.cleanup() }
      do {
        try await f.account.withActivationAccount(prepare: {
          if change == "logout" || change == "endpoint" {
            _ = try await f.account.command("logout", value: "", library: f.library)
            if change == "endpoint" { _ = try await f.account.command("configure", value: "https://two.test", library: f.library) }
          } else if change == "credential" { f.token = "replacement-fixture" }
          else { throw CancellationError() }
        }, activate: { XCTFail("A stale activation must not start audio") })
        XCTFail("The account must be checked after permission and foreground waits")
      } catch is CancellationError {}
      catch is ClarifyError { XCTAssertFalse(f.account.configured) }
      XCTAssertFalse(f.account.isBusy)
    }
  }
  @MainActor func testActivationPropagatesPermissionForegroundAndAudioFailuresWithoutTakingBusyState() async throws {
    let f = try ActivationFixture(); defer { f.cleanup() }
    for stage in ["permission", "foreground", "audio"] {
      var activations = 0
      do {
        try await f.account.withActivationAccount(prepare: {
          if stage != "audio" { throw ClarifyError(stage) }
        }, activate: { activations += 1; throw ClarifyError(stage) })
        XCTFail("Activation failure must reach the caller")
      } catch let error as ClarifyError { XCTAssertEqual(error.message, stage) }
      XCTAssertEqual(activations, stage == "audio" ? 1 : 0); XCTAssertFalse(f.account.isBusy)
    }
  }
  @MainActor func testSnippetRewriteAndExpandedFallbackStayTerminalAndKeepRawHistory() async throws {
    let raw = "Quero avisar que minha disponibilidade."
    let expanded = "Quero avisar que posso atender de segunda a sexta."
    let rewritten = "Posso atender de segunda a sexta. Segunda frase."
    let snippets = [Snippet(trigger: "minha disponibilidade", replacement: "posso atender de segunda a sexta"),
      Snippet(trigger: "segunda frase", replacement: "RECURSION SHOULD NOT RUN")]
    for (text, didRewrite) in [(rewritten, true), (expanded, false)] {
      let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
      let defaults = UserDefaults(suiteName: suite)!
      defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
      var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
      let library = try LocalLibrary(root: root), audio = root.appendingPathComponent("synthetic.m4a")
      let guest = Snippet(trigger: "guest", replacement: "Guest only")
      try library.saveSnippets([guest]); try Data("synthetic audio".utf8).write(to: audio)
      var dictations = 0
      let account = CloudAccount(defaults: defaults, transport: { request in
        switch request.url!.path {
        case "/v1/dictionary": return try self.response(request, ["revision": 0, "entries": []])
        case "/v1/snippets":
          XCTAssertEqual(request.httpMethod, "GET")
          return try self.response(request, ["revision": 1, "entries": snippets.map { ["trigger": $0.trigger, "replacement": $0.replacement, "enabled": $0.enabled, "case_sensitive": $0.caseSensitive] as [String: Any] }])
        default:
          XCTAssertEqual(request.url!.path, "/v1/dictations", "The mobile app must not call a rewrite provider or apply another snippet pass")
          dictations += 1
          return try self.response(request, ["transcript": raw, "text": text, "rewritten": didRewrite, "snippet_expanded": true])
        }
      }, readCredential: { "fixture" }, saveCredential: { _ in })
      let operationID = UUID().uuidString
      let outcome = try await account.dictate(audio, operationID: operationID, library: library)
      XCTAssertTrue(outcome.successful); XCTAssertEqual(outcome.rewritten, didRewrite)
      XCTAssertEqual(outcome.transcript, raw); XCTAssertEqual(outcome.text, text)
      XCTAssertFalse(outcome.text.contains("RECURSION SHOULD NOT RUN")); XCTAssertEqual(dictations, 1)
      let entry = HistoryEntry(id: operationID, createdAt: 1000, transcript: outcome.transcript, text: outcome.text, rewritten: outcome.successful)
      try library.record(entry, scope: account.historyScope)
      let reopened = try LocalLibrary(root: root)
      XCTAssertEqual(try reopened.history(scope: account.historyScope).entries, [entry])
      XCTAssertEqual(try reopened.snippets(scope: account.snippetScope), snippets)
      XCTAssertEqual(try reopened.snippets(), [guest])
    }
  }
  @MainActor func testDictationRevocationNotifiesResourceOwnerAfterInvalidatingSession() async throws {
    for status in [401, 403] {
      let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
      let defaults = UserDefaults(suiteName: suite)!
      defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
      var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
      let library = try LocalLibrary(root: root), audio = root.appendingPathComponent("synthetic.m4a")
      try Data("synthetic audio".utf8).write(to: audio)
      var token: String? = "fixture", invalidations = 0, dictations = 0
      var account: CloudAccount! = nil
      account = CloudAccount(defaults: defaults, transport: { request in
        if ["/v1/dictionary", "/v1/snippets"].contains(request.url!.path) {
          return try self.response(request, ["revision": 0, "entries": []])
        }
        XCTAssertEqual(request.url!.path, "/v1/dictations"); dictations += 1
        return try self.response(request, ["code": "authentication_required"], status: status)
      }, readCredential: { token }, saveCredential: { token = $0 }, sessionInvalidated: {
        XCTAssertTrue(Thread.isMainThread); XCTAssertNil(token); XCTAssertFalse(account.configured)
        XCTAssertNil(account.scope); invalidations += 1
      })
      do {
        _ = try await account.dictate(audio, operationID: UUID().uuidString, library: library)
        XCTFail("An expired session cannot publish a dictation")
      } catch let error as ClarifyError { XCTAssertEqual(error.code, "authentication_required") }
      XCTAssertEqual(invalidations, 1); XCTAssertEqual(dictations, 1)
      XCTAssertTrue(try library.history(scope: account.historyScope).entries.isEmpty)
      account.setSessionInvalidationHandler({})
    }
  }
  @MainActor func testPreflightRevocationKeepsLocalSnippetsAndNeverStartsPaidDictation() async throws {
    for deniedPath in ["/v1/dictionary", "/v1/snippets"] {
      for status in [401, 403] {
        let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
        defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
        var token: String? = "fixture", invalidations = 0, paths: [String] = []
        var account: CloudAccount! = nil
        account = CloudAccount(defaults: defaults, transport: { request in
          let path = request.url!.path; paths.append(path)
          XCTAssertTrue(["/v1/dictionary", "/v1/snippets"].contains(path), "An expired preflight must not start inference")
          return try self.response(request, path == deniedPath ? ["code": "authentication_required"] : ["revision": 0, "entries": []],
            status: path == deniedPath ? status : 200)
        }, readCredential: { token }, saveCredential: { token = $0 }, sessionInvalidated: {
          XCTAssertTrue(Thread.isMainThread); XCTAssertNil(token); XCTAssertFalse(account.configured)
          XCTAssertNil(account.scope); invalidations += 1
        })
        let library = try LocalLibrary(root: root), owner = try XCTUnwrap(account.snippetScope)
        let saved = Snippet(trigger: "signature", replacement: "Offline saved text")
        try library.saveSnippets([saved], scope: owner)
        do {
          // The absent audio also proves that revocation stops before reading it.
          _ = try await account.dictate(root.appendingPathComponent("must-not-be-read.m4a"), operationID: UUID().uuidString, library: library)
          XCTFail("A revoked preflight cannot continue to dictation")
        } catch let error as ClarifyError {
          XCTAssertEqual(error.code, "authentication_required")
          XCTAssertEqual(error.localizedDescription, L("Entre na conta novamente."))
          XCTAssertNil(error.operationID, "No inference operation was submitted")
        }
        XCTAssertEqual(paths, deniedPath == "/v1/dictionary" ? ["/v1/dictionary"] : ["/v1/dictionary", "/v1/snippets"])
        XCTAssertEqual(invalidations, 1); XCTAssertNil(token); XCTAssertFalse(account.configured); XCTAssertFalse(account.isBusy)
        XCTAssertEqual(try library.snippets(scope: owner), [saved]); XCTAssertTrue(try library.snippets().isEmpty)
        account.setSessionInvalidationHandler({})
      }
    }
  }
  @MainActor func testAccountCommandRevocationNotifiesTheSameResourceOwner() async throws {
    for action in ["refresh", "sync"] {
      let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
      let defaults = UserDefaults(suiteName: suite)!
      defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
      var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
      var token: String? = "fixture", invalidations = 0
      let account = CloudAccount(defaults: defaults, transport: { request in
        try self.response(request, [:], status: 401)
      }, readCredential: { token }, saveCredential: { token = $0 }, sessionInvalidated: {
        XCTAssertTrue(Thread.isMainThread); XCTAssertNil(token); invalidations += 1
      })
      do {
        _ = try await account.command(action, value: "", library: LocalLibrary(root: root))
        XCTFail("A revoked session must require a new sign-in")
      } catch is ClarifyError {}
      XCTAssertEqual(invalidations, 1); XCTAssertFalse(account.configured)
      XCTAssertEqual(account.snapshot()["signedIn"] as? Bool, false)
    }
  }
  @MainActor func testSignedOutProcessingRejectsBeforeReadingAudioOrSendingRequests() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let local = HistoryEntry(id: "old", createdAt: 1000, transcript: "old", text: "Old.", rewritten: true)
    try library.record(local)
    try library.saveDictionary([VocabularyEntry(term: "Local")])
    var requests = 0
    let account = CloudAccount(defaults: defaults, transport: { request in
      requests += 1; return try self.response(request, [:])
    }, readCredential: { nil }, saveCredential: { _ in XCTFail("Local credentials must not be changed") })
    XCTAssertFalse(account.configured)
    XCTAssertEqual(account.snapshot()["signedIn"] as? Bool, false)
    do {
      _ = try await account.dictate(root.appendingPathComponent("missing-audio"), operationID: UUID().uuidString, library: library)
      XCTFail("An account is required before processing")
    } catch let error as ClarifyError { XCTAssertEqual(error.localizedDescription, L("Entre na conta novamente.")) }
    XCTAssertEqual(requests, 0)
    XCTAssertEqual(try library.history().entries, [local])
    XCTAssertEqual(try library.dictionary().map(\.term), ["Local"])
  }
  @MainActor func testAccountMetadataWithoutCredentialRequiresSignInAndCanRequestANewCode() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var requests = 0; var token: String? = nil
    let account = CloudAccount(defaults: defaults, transport: { request in
      requests += 1; XCTAssertEqual(request.url!.path, "/_allauth/app/v1/auth/continue")
      return try self.response(request, ["meta": ["session_token": "pending-fixture"]], status: 401)
    }, readCredential: { token }, saveCredential: { token = $0 })
    XCTAssertFalse(account.configured)
    XCTAssertEqual(account.snapshot()["signedIn"] as? Bool, false)
    _ = try await account.command("login", value: "fixture@example.test", library: LocalLibrary(root: root))
    XCTAssertEqual(requests, 1)
    XCTAssertEqual(account.snapshot()["pending"] as? String, "login")
    XCTAssertEqual(token, "pending-fixture")
    XCTAssertFalse(account.configured, "A code-request session has not authenticated the old account")
    XCTAssertEqual(account.snapshot()["signedIn"] as? Bool, false)
    XCTAssertNil(account.scope)
    XCTAssertNotNil(account.historyScope, "Keep the previous account cache isolated during reauthentication")
  }
  func testProcessingFailuresUseKnownCodesAndKeepOnlySafeDiagnostics() throws {
    let operation = UUID().uuidString
    let examples: [(Int, String, String)] = [
      (422, "no_speech", "Nenhuma fala foi reconhecida. Tente falar novamente."),
      (502, "transcription_failed", "Não foi possível transcrever o áudio. Tente novamente."),
      (502, "text_processing_failed", "Não foi possível processar o texto. Tente novamente."),
      (429, "allowance_exhausted", "Sua cota foi atingida."),
      (429, "allocation_waiting", "Sua conta aguarda a próxima distribuição de cotas."),
      (429, "rate_limited", "Muitas solicitações. Aguarde um momento."),
      (429, "account_busy", "Já existe um processamento em andamento."),
      (503, "service_busy", "O Clarify está ocupado. Aguarde um momento."),
      (503, "service_budget_exhausted", "O processamento do Clarify está indisponível no momento.")
    ]
    for (status, code, expected) in examples {
      let failure = CloudAccount.processingFailure(status, result: ["code": code, "phase": "transcription", "operation_id": operation,
        "detail": "untrusted provider response"], operationID: operation)
      XCTAssertEqual(failure.message, expected, code)
      XCTAssertEqual(failure.code, code)
      XCTAssertEqual(failure.phase, "transcription")
      XCTAssertEqual(failure.operationID?.lowercased(), operation.lowercased())
      XCTAssertEqual(failure.status, status)
      XCTAssertFalse(failure.localizedDescription.contains("untrusted"))
    }
    let invalid = CloudAccount.processingFailure(502, result: ["code": String(repeating: "private", count: 100),
      "phase": "provider's private error", "operation_id": "not-a-uuid", "message": "secret"], operationID: operation)
    XCTAssertEqual(invalid.message, "Não foi possível concluir o processamento. Tente novamente.")
    XCTAssertNil(invalid.code); XCTAssertNil(invalid.phase); XCTAssertNil(invalid.operationID)
    let different = CloudAccount.processingFailure(502, result: ["code": "transcription_failed", "operation_id": UUID().uuidString], operationID: operation)
    XCTAssertNil(different.operationID, "Do not associate a different server operation with this recording")
    let unauthorized = CloudAccount.processingFailure(401, result: ["code": "no_speech"], operationID: operation)
    XCTAssertEqual(unauthorized.message, "Entre na conta novamente.")
    XCTAssertEqual(unauthorized.code, "authentication_required")
  }
  func testOlderOrMalformedErrorPayloadsUseStatusRecoveryWithoutClaimingAQuotaFailure() {
    let payloads: [[String: Any]] = [[:], ["code": 42], ["code": "new_server_code"]]
    for result in payloads {
      XCTAssertEqual(CloudAccount.processingFailure(429, result: result, operationID: "").message,
        "Muitas solicitações. Aguarde um momento.")
      XCTAssertEqual(CloudAccount.processingFailure(503, result: result, operationID: "").message,
        "O processamento do Clarify está indisponível no momento.")
    }
  }
  @MainActor func testWeeklyUsageEnvelopePreservesPercentagesAndAccountStatus() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var allocation = "available"
    let account = CloudAccount(defaults: defaults, transport: { request in
      XCTAssertEqual(request.url!.path, "/v1/account")
      return try self.response(request, ["id": state.userID!, "email": "fixture@example.test", "usage": [
        "schema_version": 2, "period_start": "2026-10-19T00:00:00Z", "reset_at": "2026-10-26T00:00:00Z",
        "used_percent": 12.5, "remaining_percent": 82.5, "reserved_percent": 5,
        "allocation_status": allocation, "hosted_available": allocation == "available"]])
    }, readCredential: { "fixture" }, saveCredential: { _ in })
    let library = try LocalLibrary(root: root)
    for status in ["available", "waiting", "unfunded", "inactive"] {
      allocation = status
      _ = try await account.command("refresh", value: "", library: library)
      let usage = try XCTUnwrap(account.snapshot()["usage"] as? [String: Any])
      XCTAssertEqual(usage["schema_version"] as? Int, 2)
      XCTAssertEqual(usage["used_percent"] as? Double, 12.5)
      XCTAssertEqual(usage["remaining_percent"] as? Double, 82.5)
      XCTAssertEqual(usage["reserved_percent"] as? Int, 5)
      XCTAssertEqual(usage["allocation_status"] as? String, status)
      XCTAssertEqual(usage["hosted_available"] as? Bool, status == "available")
      XCTAssertNil(usage["used_ms"]); XCTAssertNil(usage["limit_ms"])
      XCTAssertTrue(account.configured)
    }
  }
  @MainActor func testShortDictationFailureUpdatesUsageAndDoesNotRetryOrStoreHistory() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let operation = UUID().uuidString, library = try LocalLibrary(root: root)
    // The hosted client must not impose a one-second minimum. The server owns decoding.
    let audio = root.appendingPathComponent("short.wav")
    var clip = Data()
    func text(_ value: String) { clip.append(Data(value.utf8)) }
    func integer<T: FixedWidthInteger>(_ value: T) { var little = value.littleEndian; withUnsafeBytes(of: &little) { clip.append(contentsOf: $0) } }
    text("RIFF"); integer(UInt32(36 + 32_000)); text("WAVEfmt "); integer(UInt32(16)); integer(UInt16(1)); integer(UInt16(1))
    integer(UInt32(16_000)); integer(UInt32(32_000)); integer(UInt16(2)); integer(UInt16(16)); text("data"); integer(UInt32(32_000))
    clip.append(Data(repeating: 0, count: 32_000)); try clip.write(to: audio)
    var dictations = 0
    let account = CloudAccount(defaults: defaults, transport: { request in
      if ["/v1/dictionary", "/v1/snippets"].contains(request.url!.path) { return try self.response(request, ["revision": 0, "entries": []]) }
      XCTAssertEqual(request.url!.path, "/v1/dictations"); dictations += 1
      return try self.response(request, ["code": "no_speech", "phase": "transcription", "operation_id": operation,
        "usage": ["used_ms": 1000, "limit_ms": 18_000_000]], status: 422)
    }, readCredential: { "fixture" }, saveCredential: { _ in })
    do { _ = try await account.dictate(audio, operationID: operation, library: library); XCTFail("Empty speech must not become a successful dictation") }
    catch let error as ClarifyError { XCTAssertEqual(error.code, "no_speech"); XCTAssertEqual(error.phase, "transcription") }
    XCTAssertEqual(dictations, 1)
    XCTAssertEqual((account.snapshot()["usage"] as? [String: Any])?["used_ms"] as? Int, 1000)
    XCTAssertTrue(try library.history(scope: account.historyScope).entries.isEmpty)
  }
  @MainActor func testMalformedUnauthorizedResponseRevokesSessionBeforeAudioUpload() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var token: String? = "fixture", requests = 0
    let account = CloudAccount(defaults: defaults, transport: { request in
      requests += 1; XCTAssertEqual(request.url!.path, "/v1/dictionary")
      return (Data("not JSON".utf8), HTTPURLResponse(url: request.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!)
    }, readCredential: { token }, saveCredential: { token = $0 })
    let library = try LocalLibrary(root: root)
    do { _ = try await account.dictate(root.appendingPathComponent("never-read"), operationID: UUID().uuidString, library: library); XCTFail("Must require a new sign-in") }
    catch let error as ClarifyError { XCTAssertEqual(error.localizedDescription, L("Entre na conta novamente.")) }
    XCTAssertNil(token); XCTAssertFalse(account.hosted); XCTAssertTrue(account.managed); XCTAssertEqual(requests, 1)
  }
  @MainActor func testLateDictationFailureCannotRevokeOrUpdateTheNewCredential() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let library = try LocalLibrary(root: root), audio = root.appendingPathComponent("clip.m4a")
    try Data("synthetic audio".utf8).write(to: audio)
    var token: String? = "old", pending: CheckedContinuation<(Data, HTTPURLResponse), Error>?, dictationRequest: URLRequest?
    var invalidations = 0
    let account = CloudAccount(defaults: defaults, transport: { request in
      if ["/v1/dictionary", "/v1/snippets"].contains(request.url!.path) { return try self.response(request, ["revision": 0, "entries": []]) }
      dictationRequest = request
      return try await withCheckedThrowingContinuation { pending = $0 }
    }, readCredential: { token }, saveCredential: { token = $0 }, sessionInvalidated: { invalidations += 1 })
    let task = Task { try await account.dictate(audio, operationID: UUID().uuidString, library: library) }
    while pending == nil { await Task.yield() }
    token = "new"
    pending!.resume(returning: try response(dictationRequest!, ["code": "authentication_required", "usage": ["used_ms": 999]], status: 401))
    do { _ = try await task.value; XCTFail("A stale request must be cancelled") }
    catch is CancellationError {}
    XCTAssertEqual(token, "new"); XCTAssertTrue(account.hosted)
    XCTAssertNil((account.snapshot()["usage"] as? [String: Any])?["used_ms"])
    XCTAssertFalse(account.isBusy)
    XCTAssertEqual(invalidations, 0, "A response from the earlier session cannot stop the new session")
  }
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

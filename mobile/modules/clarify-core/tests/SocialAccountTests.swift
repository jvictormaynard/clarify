import XCTest
import SQLite3
@testable import ClarifyContracts

final class SocialAccountTests: XCTestCase {
  @MainActor private final class Fixture {
    let suite = "ClarifySocialTests.\(UUID().uuidString)"
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults: UserDefaults
    let user = UUID().uuidString
    let attempt = UUID().uuidString
    var token: String?
    var requests: [URLRequest] = []
    var opened: [URL] = []
    var now: TimeInterval = 0
    var clockStepAfterPoll: TimeInterval = 0
    var sleepIntervals: [TimeInterval] = []
    var polls = 0
    var pollStatus = 200
    var pollBody: [String: Any] = ["meta": ["is_authenticated": true, "session_token": "native-session"]]
    var authorizationURL = "https://one.test/browser/authorize?attempt=opaque"
    var callback = "clarify://auth/complete"
    var browserFailure: Error?
    var storageFailure = false
    var pendingPolls = 0
    var expireInBrowser = false
    var browserWaits = false
    var accountStatus = 200
    var startStatus = 200
    var onBrowser: (() -> Void)?
    var onPoll: (() -> Void)?
    lazy var account = CloudAccount(defaults: defaults, transport: { request in
      self.requests.append(request)
      let path = request.url!.path
      if path.hasSuffix("/social/start") {
        return try self.response(request, ["attempt_id": self.attempt, "authorization_url": self.authorizationURL, "expires_in": 300, "interval": 5], self.startStatus)
      }
      if path.hasSuffix("/social/cancel") || request.httpMethod == "DELETE" { return try self.response(request, [:], 204) }
      if path.hasSuffix("/social/poll") {
        self.polls += 1; self.onPoll?()
        if self.polls <= self.pendingPolls { return try self.response(request, [:], 202) }
        return try self.response(request, self.pollBody, self.pollStatus)
      }
      if path == "/v1/account" { return try self.response(request, ["id": self.user, "email": "person@example.test"], self.accountStatus) }
      if path.hasSuffix("/auth/email/verify") {
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Session-Token"), "pending-session")
        return try self.response(request, ["meta": ["is_authenticated": true, "session_token": "confirmed-session"]])
      }
      if path == "/v1/dictionary" || path == "/v1/snippets" { return try self.response(request, ["revision": 0, "entries": []]) }
      XCTFail("Unexpected request: \(path)"); return try self.response(request, [:], 500)
    }, readCredential: { self.token }, saveCredential: {
      if self.storageFailure, $0 != nil { throw ClarifyError("fixture storage failure") }
      self.token = $0
    }, socialBrowser: SocialBrowser(open: { url in
      self.opened.append(url); self.onBrowser?()
      if self.browserWaits { try await Task.sleep(nanoseconds: 3_600_000_000_000) }
      if let failure = self.browserFailure { throw failure }
      return URL(string: self.callback)!
    }, cancel: {}), socialClock: {
      let value = self.now
      if self.polls > 0 { self.now += self.clockStepAfterPoll }
      return value
    }, socialSleep: { seconds in
      self.sleepIntervals.append(seconds)
      if seconds >= 300, !self.expireInBrowser { try await Task.sleep(nanoseconds: 3_600_000_000_000) }
      else { self.now += seconds; await Task.yield(); try Task.checkCancellation() }
    })
    init() throws {
      defaults = UserDefaults(suiteName: suite)!
      var state = CloudAccountState(); state.endpoint = "https://one.test"
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    }
    func cleanup() {
      defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root)
    }
    func response(_ request: URLRequest, _ json: [String: Any], _ code: Int = 200) throws -> (Data, HTTPURLResponse) {
      (try JSONSerialization.data(withJSONObject: json), HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!)
    }
    func run(_ provider: String = "google") async throws -> Bool {
      try await account.command("social", value: provider, library: LocalLibrary(root: root))
    }
    var cancelled: [URLRequest] { requests.filter { $0.url!.path.hasSuffix("/social/cancel") } }
    func body(_ request: URLRequest) throws -> [String: String] {
      try XCTUnwrap(JSONSerialization.jsonObject(with: request.httpBody!) as? [String: String])
    }
  }

  func testPKCEUsesRFC7636S256AndIndependentRandomVerifiers() throws {
    XCTAssertEqual(SocialPKCE.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    let a = try SocialPKCE.verifier(), b = try SocialPKCE.verifier()
    XCTAssertNotEqual(a, b); XCTAssertEqual(a.count, 43)
    XCTAssertNotNil(a.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression))
  }

  @MainActor func testAllProvidersUseNativeHandoffAndKeepCredentialsOutOfSnapshotsAndBrowser() async throws {
    for provider in ["google", "microsoft", "github"] {
      let f = try Fixture(); defer { f.cleanup() }
      f.pendingPolls = 2
      let result = try await f.run(provider); XCTAssertTrue(result)
      XCTAssertTrue(f.account.configured); XCTAssertEqual(f.token, "native-session")
      let start = try f.body(f.requests[0]), poll = try f.body(XCTUnwrap(f.requests.first { $0.url!.path.hasSuffix("/social/poll") }))
      XCTAssertEqual(start["provider"], provider); XCTAssertEqual(start["client"], "ios")
      XCTAssertNil(start["code_verifier"]); XCTAssertEqual(start["code_challenge"], SocialPKCE.challenge(try XCTUnwrap(poll["code_verifier"])))
      XCTAssertEqual(poll["attempt_id"], f.attempt); XCTAssertEqual(f.polls, 3); XCTAssertEqual(f.now, 10)
      XCTAssertTrue(f.requests.filter { $0.url!.path.contains("/social/") }.allSatisfy { $0.value(forHTTPHeaderField: "X-Session-Token") == nil })
      XCTAssertEqual(f.opened.map(\.absoluteString), [f.authorizationURL]); XCTAssertTrue(f.cancelled.isEmpty)
      let snapshot = String(data: try JSONSerialization.data(withJSONObject: f.account.snapshot()), encoding: .utf8)!
      let metadata = String(data: f.defaults.data(forKey: "clarify.account.metadata")!, encoding: .utf8)!
      for secret in ["native-session", poll["code_verifier"]!, f.attempt] {
        XCTAssertFalse(snapshot.contains(secret)); XCTAssertFalse(metadata.contains(secret)); XCTAssertFalse(f.authorizationURL.contains(secret))
      }
      XCTAssertTrue(f.requests.contains { $0.url!.path == "/v1/dictionary" })
      XCTAssertTrue(f.requests.contains { $0.url!.path == "/v1/snippets" })
    }
  }

  @MainActor func testPendingEmailContinuesThroughExistingSignupConfirmation() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    f.pollStatus = 401; f.pollBody = ["meta": ["is_authenticated": false, "session_token": "pending-session"], "data": ["pending": "signup", "email": "person@example.test"]]
    _ = try await f.run("github")
    XCTAssertFalse(f.account.configured); XCTAssertEqual(f.token, "pending-session")
    XCTAssertEqual(f.account.snapshot()["pending"] as? String, "signup")
    _ = try await f.account.command("confirm", value: "123456", library: LocalLibrary(root: f.root))
    XCTAssertTrue(f.account.configured); XCTAssertEqual(f.token, "confirmed-session")
    XCTAssertEqual(f.account.snapshot()["pending"] as? String, "")
  }

  @MainActor func testBrowserCancellationFailureAndUntrustedCallbacksCancelWithoutSaving() async throws {
    for mode in ["cancel", "failure", "callback", "credentials"] {
      let f = try Fixture(); defer { f.cleanup() }
      if mode == "cancel" { f.browserFailure = CancellationError() }
      if mode == "failure" { f.browserFailure = ClarifyError("fixture browser failure") }
      if mode == "callback" { f.callback = "clarify://other/complete" }
      if mode == "credentials" { f.callback = "clarify://auth/complete?session_token=must-not-be-used" }
      do { let changed = try await f.run(); XCTAssertEqual(mode, "cancel"); XCTAssertFalse(changed) }
      catch { XCTAssertNotEqual(mode, "cancel") }
      XCTAssertNil(f.token); XCTAssertFalse(f.account.isBusy); XCTAssertEqual(f.polls, 0); XCTAssertEqual(f.cancelled.count, 1)
      let cancel = try f.body(f.cancelled[0]); XCTAssertEqual(cancel["attempt_id"], f.attempt); XCTAssertNotNil(cancel["code_verifier"])
    }
  }

  @MainActor func testAuthorizationURLMustUseSameHTTPSOriginWithoutUserInfoOrFragment() async throws {
    for url in ["http://one.test/auth", "https://evil.test/auth", "https://one.test.evil.test/auth", "https://one.test:8443/auth", "https://user@one.test/auth", "https://one.test/auth#token", "clarify://auth/complete"] {
      let f = try Fixture(); defer { f.cleanup() }; f.authorizationURL = url
      do { _ = try await f.run(); XCTFail("Must reject \(url)") } catch {}
      XCTAssertTrue(f.opened.isEmpty); XCTAssertEqual(f.cancelled.count, 1); XCTAssertNil(f.token)
    }
  }

  @MainActor func testTerminalPollFailuresExpiryReplayAndRateLimitsNeverPersistTokens() async throws {
    for (status, code) in [(400, "social_login_failed"), (400, "social_account_exists"), (400, "social_signup_closed"), (400, "social_email_required"), (410, ""), (429, "")] {
      let f = try Fixture(); defer { f.cleanup() }; f.pollStatus = status
      f.pollBody = ["code": code, "detail": "untrusted", "meta": ["session_token": "must-not-save"]]
      do { _ = try await f.run(); XCTFail("Terminal result \(status) must fail") } catch { XCTAssertFalse(error.localizedDescription.contains("untrusted")) }
      XCTAssertNil(f.token); XCTAssertEqual(f.polls, 1); XCTAssertEqual(f.cancelled.count, 1); XCTAssertFalse(f.account.isBusy)
    }
  }

  @MainActor func testMalformedSuccessAndPendingEmailDoNotAdoptSessions() async throws {
    for (status, payload) in [(200, ["meta": ["is_authenticated": false, "session_token": "bad"]]), (200, ["meta": ["is_authenticated": true, "session_token": ""]]), (401, ["meta": ["is_authenticated": false, "session_token": "bad"], "data": ["pending": "login", "email": "a@example.test"]])] as [(Int, [String: Any])] {
      let f = try Fixture(); defer { f.cleanup() }; f.pollStatus = status; f.pollBody = payload
      do { _ = try await f.run(); XCTFail("Malformed handoff must fail") } catch {}
      XCTAssertNil(f.token); XCTAssertFalse(f.account.configured); XCTAssertEqual(f.cancelled.count, 1)
    }
  }

  @MainActor func testStorageAndAccountFetchFailureRevokeHandedSessionAndPreserveLocalData() async throws {
    for storage in [true, false] {
      let f = try Fixture(); defer { f.cleanup() }; f.storageFailure = storage; f.accountStatus = storage ? 200 : 401
      let library = try LocalLibrary(root: f.root); try library.saveDictionary([VocabularyEntry(term: "Preserved")])
      do { _ = try await f.run(); XCTFail("Failed storage/account lookup must fail") } catch {}
      XCTAssertNil(f.token); XCTAssertFalse(f.account.configured); XCTAssertEqual(f.cancelled.count, 1)
      XCTAssertTrue(f.requests.contains { $0.httpMethod == "DELETE" && $0.value(forHTTPHeaderField: "X-Session-Token") == "native-session" })
      XCTAssertEqual(try library.dictionary().map(\.term), ["Preserved"])
    }
  }

  @MainActor func testTimeoutClosesBrowserAndCancelsExpiredAttempt() async throws {
    let f = try Fixture(); defer { f.cleanup() }; f.expireInBrowser = true; f.browserWaits = true
    do { _ = try await f.run(); XCTFail("Browser must time out") } catch {}
    XCTAssertNil(f.token); XCTAssertEqual(f.cancelled.count, 1); XCTAssertFalse(f.account.isBusy)
  }

  @MainActor func testPendingPollExpiresWithoutRetryingOrSavingAfterDeadline() async throws {
    let f = try Fixture(); defer { f.cleanup() }; f.pendingPolls = 100
    do { _ = try await f.run(); XCTFail("Pending handoff must expire") } catch {}
    XCTAssertEqual(f.now, 300); XCTAssertEqual(f.polls, 60)
    XCTAssertNil(f.token); XCTAssertEqual(f.cancelled.count, 1); XCTAssertFalse(f.account.isBusy)
  }

  @MainActor func testClockCrossingDeadlineBetweenReadsNeverSchedulesNegativeSleep() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    f.pendingPolls = 100; f.clockStepAfterPoll = 2; f.onPoll = { f.now = 299 }
    do { _ = try await f.run(); XCTFail("Pending handoff must expire") } catch {}
    XCTAssertEqual(f.polls, 1); XCTAssertTrue(f.sleepIntervals.contains(1))
    XCTAssertTrue(f.sleepIntervals.allSatisfy { $0 > 0 })
    XCTAssertNil(f.token); XCTAssertEqual(f.cancelled.count, 1); XCTAssertFalse(f.account.isBusy)
  }

  @MainActor func testSQLitePreparationFailureRevokesHandoffBeforePublishingAccountOrCredentials() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    let library = try LocalLibrary(root: f.root), otherUser = UUID().uuidString
    try library.saveDictionary([VocabularyEntry(term: "Guest preserved")])
    try library.saveCloudDictionary(CloudDictionary(entries: [VocabularyEntry(term: "Other account preserved")], base: [], revision: 1), scope: otherUser)
    var database: OpaquePointer?
    XCTAssertEqual(sqlite3_open(f.root.appendingPathComponent("library.sqlite").path, &database), SQLITE_OK)
    defer { sqlite3_close(database) }
    XCTAssertEqual(sqlite3_exec(database, "CREATE TRIGGER deny_account_cache BEFORE INSERT ON account_vocabulary BEGIN SELECT RAISE(ABORT,'fixture'); END", nil, nil, nil), SQLITE_OK)
    do { _ = try await f.run(); XCTFail("SQLite failure must reject the handoff") } catch {}
    XCTAssertNil(f.token); XCTAssertNil(f.account.scope); XCTAssertFalse(f.account.configured); XCTAssertFalse(f.account.isBusy)
    XCTAssertEqual(f.cancelled.count, 1)
    XCTAssertTrue(f.requests.contains { $0.httpMethod == "DELETE" && $0.value(forHTTPHeaderField: "X-Session-Token") == "native-session" })
    let metadata = try JSONDecoder().decode(CloudAccountState.self, from: f.defaults.data(forKey: "clarify.account.metadata")!)
    XCTAssertNil(metadata.userID)
    XCTAssertEqual(try library.dictionary().map(\.term), ["Guest preserved"])
    XCTAssertEqual(try library.dictionary(scope: otherUser).map(\.term), ["Other account preserved"])
  }

  @MainActor func testCancellationDuringPollDiscardsLateSuccessAndRevokesTheReturnedSession() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    var pollContinuation: CheckedContinuation<Void, Never>?
    let entered = expectation(description: "poll started")
    let account = CloudAccount(defaults: f.defaults, transport: { request in
      f.requests.append(request)
      if request.url!.path.hasSuffix("/social/start") {
        return try f.response(request, ["attempt_id": f.attempt, "authorization_url": f.authorizationURL, "expires_in": 300, "interval": 5])
      }
      if request.url!.path.hasSuffix("/social/poll") {
        await withCheckedContinuation { pollContinuation = $0; entered.fulfill() }
        return try f.response(request, f.pollBody)
      }
      return try f.response(request, [:], 204)
    }, readCredential: { f.token }, saveCredential: { f.token = $0 }, socialBrowser: SocialBrowser(open: { _ in URL(string: f.callback)! }, cancel: {}))
    let task = Task { @MainActor in try await account.command("social", value: "microsoft", library: LocalLibrary(root: f.root)) }
    await fulfillment(of: [entered], timeout: 2)
    _ = try await account.command("cancel-social", value: "", library: LocalLibrary(root: f.root))
    pollContinuation?.resume()
    let changed = try await task.value
    XCTAssertFalse(changed); XCTAssertNil(f.token); XCTAssertFalse(account.isBusy); XCTAssertEqual(f.cancelled.count, 1)
    XCTAssertTrue(f.requests.contains { $0.httpMethod == "DELETE" && $0.value(forHTTPHeaderField: "X-Session-Token") == "native-session" })
  }

  @MainActor func testStartFailureAndUnsupportedProviderNeverOpenBrowserOrStoreCredentials() async throws {
    for provider in ["google", "apple"] {
      let f = try Fixture(); defer { f.cleanup() }; f.startStatus = 429
      do { _ = try await f.run(provider); XCTFail("Start must fail") } catch {}
      XCTAssertNil(f.token); XCTAssertTrue(f.opened.isEmpty); XCTAssertEqual(f.polls, 0); XCTAssertFalse(f.account.isBusy)
      if provider == "apple" { XCTAssertTrue(f.requests.isEmpty) }
    }
  }

  @MainActor func testExplicitCancellationWhileBrowserOpenKeepsBusyUntilCleanup() async throws {
    let f = try Fixture(); defer { f.cleanup() }; f.browserWaits = true
    let opened = expectation(description: "browser opened"); f.onBrowser = { opened.fulfill() }
    let task = Task { @MainActor in try await f.run() }
    await fulfillment(of: [opened], timeout: 2)
    XCTAssertTrue(f.account.isBusy)
    _ = try await f.account.command("cancel-social", value: "", library: LocalLibrary(root: f.root))
    let changed = try await task.value
    XCTAssertFalse(changed); XCTAssertNil(f.token); XCTAssertFalse(f.account.isBusy); XCTAssertEqual(f.cancelled.count, 1)
  }

  @MainActor func testCancellationWhileWaitingForAutomaticRefreshNeverStartsSocialLogin() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    var state = CloudAccountState(); state.endpoint = "https://one.test"; state.userID = f.user
    f.defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    var refreshContinuation: CheckedContinuation<Void, Never>?
    let refreshing = expectation(description: "automatic refresh suspended")
    let account = CloudAccount(defaults: f.defaults, transport: { request in
      f.requests.append(request)
      guard request.url!.path == "/v1/account" else {
        XCTFail("Cancelled social login must not start after automatic refresh")
        return try f.response(request, [:], 500)
      }
      await withCheckedContinuation { refreshContinuation = $0; refreshing.fulfill() }
      return try f.response(request, [:], 401)
    }, readCredential: { f.token }, saveCredential: { f.token = $0 })
    let library = try LocalLibrary(root: f.root)
    let automatic = Task { @MainActor in try await account.command("auto", value: "", library: library) }
    await fulfillment(of: [refreshing], timeout: 2)
    let entered = expectation(description: "social command entered"), cancelled = expectation(description: "social cancelled before refresh completed")
    let social = Task { @MainActor in
      entered.fulfill()
      let changed = try await account.command("social", value: "google", library: library)
      cancelled.fulfill()
      return changed
    }
    await fulfillment(of: [entered], timeout: 2)
    await Task.yield()
    _ = try await account.command("cancel-social", value: "", library: library)
    await fulfillment(of: [cancelled], timeout: 2)
    XCTAssertTrue(account.isBusy, "The suspended automatic refresh still owns busy state")
    refreshContinuation?.resume()
    _ = try await automatic.value
    let changed = try await social.value
    XCTAssertFalse(changed); XCTAssertNil(f.token); XCTAssertFalse(account.isBusy)
    XCTAssertEqual(f.requests.map { $0.url!.path }, ["/v1/account"])
  }

  @MainActor func testLatePollCannotReplaceAnExternallyChangedIdentity() async throws {
    let f = try Fixture(); defer { f.cleanup() }; f.onPoll = { f.token = "newer-identity" }
    let changed = try await f.run(); XCTAssertFalse(changed)
    XCTAssertEqual(f.token, "newer-identity"); XCTAssertFalse(f.account.configured); XCTAssertEqual(f.cancelled.count, 1)
  }
}

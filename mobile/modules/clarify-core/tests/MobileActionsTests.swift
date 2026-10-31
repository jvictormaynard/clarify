import Foundation
import XCTest
@testable import ClarifyContracts

final class MobileActionsTests: XCTestCase {
  func testDestinationDefaultDoesNotClaimAnExplicitCasualStyle() {
    XCTAssertEqual(OutputStyle.default.title, L("Padrão"))
    XCTAssertNotEqual(OutputStyle.default.title, OutputStyle.casual.title)
  }
  func testCopyOnlyResolvesTheCurrentCompletedTextOperation() {
    let id = UUID().uuidString
    var state = DictationSnapshot()
    state.operationID = id; state.processingContext = "account-a"
    state.textOperation = true; state.phase = .ready; state.text = "Owned result"
    XCTAssertEqual(state.textResult(for: id, context: "account-a", currentContext: "account-a"), "Owned result")
    XCTAssertNil(state.textResult(for: UUID().uuidString, context: "account-a", currentContext: "account-a"))
    XCTAssertNil(state.textResult(for: id, context: "account-a", currentContext: "account-b"))
    XCTAssertNil(state.textResult(for: id, context: "account-b", currentContext: "account-b"))
    state.phase = .rewriting
    XCTAssertNil(state.textResult(for: id, context: "account-a", currentContext: "account-a"))
    state.phase = .error
    XCTAssertNil(state.textResult(for: id, context: "account-a", currentContext: "account-a"))
    state.phase = .ready; state.textOperation = false
    XCTAssertNil(state.textResult(for: id, context: "account-a", currentContext: "account-a"))
  }

  func testCatalogDistinguishesMissingEmptyAndMalformedAndPreservesInt64() throws {
    XCTAssertEqual(try TextActionCatalog.computer(nil).status, .unsupported)
    XCTAssertEqual(try TextActionCatalog.computer([]).status, .ready)
    let row: [String: Any] = ["id": "summary", "revision": Int64.max, "name": "Summary", "kind": "custom", "enabled": true, "ready": true]
    let catalog = try TextActionCatalog.computer([row])
    XCTAssertEqual(catalog.actions.first?.revision, "9223372036854775807")
    XCTAssertEqual(catalog.actions.first?.snapshot["revision"] as? String, "9223372036854775807")
    for (key, value) in [("revision", true as Any), ("revision", "1" as Any), ("revision", 1.5 as Any),
      ("ready", 1 as Any), ("kind", "translate" as Any), ("id", "../x" as Any), ("prompt", "secret" as Any)] {
      var invalid = row; invalid[key] = value
      XCTAssertThrowsError(try TextActionCatalog.computer([invalid]), key)
    }
    XCTAssertThrowsError(try TextActionCatalog.computer(NSNull()))
    XCTAssertThrowsError(try TextActionCatalog.computer([row, row]))
    XCTAssertThrowsError(try TextActionCatalog.computer(Array(repeating: row, count: 65)))
    for revision in ["0", "01", "+1", "1.0", "9223372036854775808"] {
      XCTAssertNil(TextActionDescriptor.wireRevision(revision))
    }
  }

  func testHostedCatalogDropsPromptsAndSanitizesProjection() throws {
    let raw: [String: Any] = ["revision": 0, "actions": [["id": "rewrite", "revision": 1,
      "name": "Safe\u{202e}\nname", "kind": "rewrite", "enabled": true, "prompt": "private instruction"]]]
    let catalog = try TextActionCatalog.hosted(raw)
    XCTAssertEqual(catalog.actions.first?.name, "Safename")
    let encoded = try JSONEncoder().encode(catalog)
    XCTAssertFalse(String(decoding: encoded, as: UTF8.self).contains("private instruction"))
    XCTAssertFalse(String(decoding: encoded, as: UTF8.self).contains("prompt"))
  }

  func testSingleFieldPreferencesDoNotOverwriteOtherOwnerOrAppState() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let app = SharedState(root: root), keyboard = SharedState(root: root)
    var state = DictationSnapshot(); state.operationID = UUID().uuidString
    try app.write(state, to: "state.json")
    let before = try Data(contentsOf: root.appendingPathComponent("state.json"))
    XCTAssertEqual(app.outputPreferences(), OutputPreferences())
    _ = try keyboard.setOutputPreference("language", value: "de")
    let frozen = app.outputPreferences()
    _ = try app.setOutputPreference("style", value: "formal")
    XCTAssertEqual(keyboard.outputPreferences(), OutputPreferences(language: .de, style: .formal))
    XCTAssertEqual(frozen, OutputPreferences(language: .de, style: .default))
    XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("state.json")), before)
    XCTAssertThrowsError(try keyboard.setOutputPreference("style", value: "invented"))
    XCTAssertEqual(keyboard.outputPreferences().style, .formal)
  }

  #if os(macOS)
  func testPreferenceTransactionCoordinatesWithAnotherProcess() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = SharedState(root: root)
    _ = try store.setOutputPreference("style", value: "default")
    let helper = root.appendingPathComponent("writer.swift")
    try """
      import Foundation
      let root = URL(fileURLWithPath: CommandLine.arguments[1])
      let file = root.appendingPathComponent("output-preferences.json")
      var error: NSError?
      NSFileCoordinator().coordinate(writingItemAt: file, options: .forMerging, error: &error) { _ in
        var value = try! JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: String]
        try! Data().write(to: root.appendingPathComponent("locked"))
        let deadline = Date().addingTimeInterval(10)
        while !FileManager.default.fileExists(atPath: root.appendingPathComponent("release").path), Date() < deadline { Thread.sleep(forTimeInterval: 0.01) }
        value["style"] = "formal"
        try! JSONSerialization.data(withJSONObject: value).write(to: file, options: .atomic)
      }
      if error != nil { exit(1) }
      """.write(to: helper, atomically: true, encoding: .utf8)
    let child = Process(); child.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    child.arguments = ["swift", helper.path, root.path]
    try child.run()
    defer { if child.isRunning { child.terminate(); child.waitUntilExit() } }
    let deadline = Date().addingTimeInterval(30)
    while !FileManager.default.fileExists(atPath: root.appendingPathComponent("locked").path), child.isRunning, Date() < deadline { Thread.sleep(forTimeInterval: 0.01) }
    XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("locked").path))
    DispatchQueue.global().asyncAfter(deadline: .now() + 0.2) { try? Data().write(to: root.appendingPathComponent("release")) }
    _ = try store.setOutputPreference("language", value: "de")
    child.waitUntilExit(); XCTAssertEqual(child.terminationStatus, 0)
    XCTAssertEqual(store.outputPreferences(), OutputPreferences(language: .de, style: .formal), "The app must read after the other process commits its style")
  }
  #endif

  func testExplicitPreferencesRequireCompleteProvenanceAndKeepExactStandalone() throws {
    let preferences = OutputPreferences(language: .es, style: .formal)
    XCTAssertThrowsError(try preferences.requestFields(supported: false, dictation: true))
    XCTAssertTrue(try OutputPreferences().requestFields(supported: false, dictation: true).isEmpty)
    XCTAssertEqual(try preferences.requestFields(supported: true, dictation: true), ["output_language": "es", "writing_style": "formal"])
    XCTAssertEqual(try preferences.requestFields(supported: true, dictation: false), ["writing_style": "formal"])
    XCTAssertFalse(preferences.applied(in: [:], dictation: true))
    var raw: [String: Any] = ["output_language_requested": "es", "output_language_applied": "es", "output_language_status": "applied",
      "writing_style_requested": "formal", "writing_style_applied": "formal", "writing_style_status": "applied"]
    XCTAssertTrue(preferences.applied(in: raw, dictation: true))
    raw["writing_style_status"] = "refinement_failed"
    XCTAssertFalse(preferences.applied(in: raw, dictation: true))
    raw["writing_style_status"] = "standalone"; raw["writing_style_applied"] = NSNull()
    raw["output_language_status"] = "standalone"; raw["output_language_applied"] = NSNull()
    raw["rewritten"] = false
    XCTAssertTrue(preferences.applied(in: raw, dictation: true))
    XCTAssertFalse(preferences.applied(in: raw, dictation: false))
    raw["rewritten"] = true
    XCTAssertFalse(preferences.applied(in: raw, dictation: true))
  }

  @MainActor private final class Fixture {
    let suite = "clarify.mobile.actions." + UUID().uuidString
    let defaults: UserDefaults
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let user = UUID().uuidString
    let computerID = UUID()
    var token: String? = "fixture-session"
    var requests: [URLRequest] = []
    var catalogStatus = 200
    var catalogFailure: Error?
    var supportsPreferences = false
    var dictateReady = false
    var computerCatalog: Any? = [["id": "summary", "revision": Int64.max, "name": "Summary", "kind": "custom", "enabled": true, "ready": true]]
    var hostedCatalog: [String: Any] = ["revision": 1, "actions": [["id": "summary", "revision": Int64.max, "name": "Summary", "kind": "custom", "enabled": true, "prompt": "Private prompt"]]]
    var provenance: [String: Any] = [:]
    var mismatch = false
    var postFailure: Error?
    var pausePath: String?
    var suspended: CheckedContinuation<Void, Never>?
    var onRequest: (() -> Void)?
    lazy var account = CloudAccount(defaults: defaults, transport: { try await self.send($0) },
      readCredential: { self.token }, saveCredential: { self.token = $0 })
    lazy var computer = ComputerConnection(read: {
      ComputerCredential(computerID: self.computerID, computerName: "Fixture", deviceID: UUID(), sessionToken: String(repeating: "x", count: 43),
        routes: [ComputerRoute(url: "https://192.168.1.12:47653", certificateSHA256: String(repeating: "a", count: 64))])
    }, save: { _ in }, transport: { request, _ in try await self.send(request) })
    lazy var destination = ProcessingDestination(defaults: defaults, computer: computer, account: account)
    init(computer: Bool = false) throws {
      defaults = UserDefaults(suiteName: suite)!
      var state = CloudAccountState(); state.endpoint = "https://account.example.test"; state.userID = user
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
      defaults.set(computer ? "computer" : "hosted", forKey: "clarify.processing.destination")
      try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
      requests.append(request)
      let path = request.url!.path
      if path == pausePath { await withCheckedContinuation { suspended = $0; onRequest?() } }
      var raw: [String: Any], status = 200
      if path == "/v1/account" { raw = ["id": user, "email": "fixture@example.test", "output_preferences_supported": supportsPreferences] }
      else if path == "/v1/text-actions" {
        if let catalogFailure { throw catalogFailure }; raw = hostedCatalog; status = catalogStatus
      } else if path == "/v1/computer/status" {
        if let catalogFailure { throw catalogFailure }
        raw = ["schema_version": 1, "computer_id": computerID.uuidString, "computer_name": "Fixture", "ready": dictateReady,
          "action_readiness": ["dictate": dictateReady, "rewrite": true, "translate": true], "output_preferences_supported": supportsPreferences]
        if let computerCatalog { raw["text_actions"] = computerCatalog }
      } else if request.httpMethod == "POST" {
        if let postFailure { throw postFailure }
        raw = ["text": "Changed", "transcript": "Original", "rewritten": true, "successful": true]
        if request.value(forHTTPHeaderField: "Content-Type") == "application/json" {
          let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
          raw["operation_id"] = body["operation_id"]
          if let id = body["action_id"] {
            raw["action_id"] = mismatch ? "other" : id; raw["action_revision"] = body["action_revision"]; raw["action_name"] = "Summary"
          }
        }
        raw.merge(provenance) { _, new in new }
      } else { raw = [:] }
      return (try JSONSerialization.data(withJSONObject: raw), HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
    }
    func resume() { pausePath = nil; suspended?.resume(); suspended = nil }
    func cleanup() { resume(); defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    func prepare(_ action: String = "text_action", language: String = "auto", preferences: OutputPreferences = OutputPreferences(),
      accountIdentity: TextAccountIdentity? = nil) async throws -> PreparedTextOperation {
      try await destination.prepareText(action, actionID: action == "text_action" ? "summary" : nil,
        revision: action == "text_action" ? "9223372036854775807" : nil, language: language, context: destination.historyContext,
        preferences: preferences, accountIdentity: accountIdentity)
    }
    var posts: [URLRequest] { requests.filter { $0.httpMethod == "POST" } }
  }

  @MainActor func testTextStartCanWaitForAutomaticAccountWorkButNotExplicitOrComputerWork() async throws {
    for command in ["auto", "refresh", "computer"] {
      let f = try Fixture(computer: command == "computer"); defer { f.cleanup() }
      let library = try LocalLibrary(root: f.root.appendingPathComponent("library"))
      f.pausePath = command == "computer" ? "/v1/computer/status" : "/v1/text-actions"
      let held = expectation(description: "Destination work suspended")
      f.onRequest = { held.fulfill() }
      let work = Task { @MainActor in
        if command == "computer" { try await f.computer.refresh() }
        else { _ = try await f.account.command(command, value: "", library: library) }
      }
      await fulfillment(of: [held], timeout: 2)
      XCTAssertTrue(f.destination.isBusy)
      XCTAssertEqual(f.destination.textStartBlocked, command != "auto")
      XCTAssertThrowsError(try f.destination.select("hosted"), "Text admission must not enable destination changes")
      f.resume(); try await work.value
      XCTAssertFalse(f.destination.textStartBlocked)
    }
  }

  @MainActor func testTextPreparationWaitsForAutomaticRefreshAndKeepsItsAcceptedIdentity() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    let library = try LocalLibrary(root: f.root.appendingPathComponent("library"))
    f.pausePath = "/v1/text-actions"
    let held = expectation(description: "Automatic catalog suspended")
    f.onRequest = { held.fulfill() }
    let automatic = Task { try await f.account.command("auto", value: "", library: library) }
    await fulfillment(of: [held], timeout: 2)
    let identity = try XCTUnwrap(f.destination.captureTextIdentity())
    let entered = expectation(description: "Text preparation entered")
    let preparing = Task { @MainActor in
      entered.fulfill(); return try await f.prepare(accountIdentity: identity)
    }
    await fulfillment(of: [entered], timeout: 2)
    XCTAssertTrue(f.account.isBusy); XCTAssertTrue(f.posts.isEmpty)
    XCTAssertEqual(f.requests.filter { $0.url?.path == "/v1/text-actions" }.count, 1)
    f.resume(); _ = try await automatic.value
    let prepared = try await preparing.value
    XCTAssertEqual(prepared.accountIdentity, identity)
    let result = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Retained draft")
    XCTAssertEqual(result.text, "Changed"); XCTAssertEqual(f.posts.count, 1)
  }

  @MainActor func testCancellingTextPreparationLeavesAutomaticRefreshRunningWithoutProcessing() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    let library = try LocalLibrary(root: f.root.appendingPathComponent("library"))
    f.pausePath = "/v1/text-actions"
    let held = expectation(description: "Automatic catalog suspended")
    f.onRequest = { held.fulfill() }
    let automatic = Task { try await f.account.command("auto", value: "", library: library) }
    await fulfillment(of: [held], timeout: 2)
    let identity = try XCTUnwrap(f.destination.captureTextIdentity())
    let entered = expectation(description: "Cancelable preparation entered")
    let preparing = Task { @MainActor in
      entered.fulfill(); return try await f.prepare(accountIdentity: identity)
    }
    await fulfillment(of: [entered], timeout: 2)
    preparing.cancel()
    do { _ = try await preparing.value; XCTFail("Cancelled preparation returned") } catch is CancellationError {}
    XCTAssertTrue(f.account.isBusy); XCTAssertNotNil(f.suspended)
    XCTAssertTrue(f.account.acceptsTextIdentity(identity)); XCTAssertTrue(f.posts.isEmpty)
    f.resume(); _ = try await automatic.value
    XCTAssertFalse(f.account.isBusy); XCTAssertTrue(f.posts.isEmpty)
  }

  @MainActor func testTextCannotAdoptAReplacedCredentialBeforePreparationOrDuringAutomaticRefresh() async throws {
    for stage in ["accepted", "waiting"] {
      let f = try Fixture(); defer { f.cleanup() }
      let identity = try XCTUnwrap(f.destination.captureTextIdentity())
      if stage == "accepted" {
        f.token = "replacement-session"
        do { _ = try await f.prepare(accountIdentity: identity); XCTFail("Replaced accepted identity adopted") }
        catch is CancellationError {}
        XCTAssertTrue(f.requests.isEmpty)
      } else {
        let library = try LocalLibrary(root: f.root.appendingPathComponent("library"))
        f.pausePath = "/v1/text-actions"
        let held = expectation(description: "Automatic catalog suspended")
        f.onRequest = { held.fulfill() }
        let automatic = Task { try await f.account.command("auto", value: "", library: library) }
        await fulfillment(of: [held], timeout: 2)
        let entered = expectation(description: "Bound preparation entered")
        let preparing = Task { @MainActor in
          entered.fulfill(); return try await f.prepare(accountIdentity: identity)
        }
        await fulfillment(of: [entered], timeout: 2)
        let discoveryPaths = ["/v1/account", "/v1/text-actions"]
        let before = f.requests.filter { discoveryPaths.contains($0.url!.path) }.count
        f.token = "replacement-session"
        f.resume(); _ = try await automatic.value
        do { _ = try await preparing.value; XCTFail("Waiting preparation adopted replacement credential") }
        catch is CancellationError {}
        XCTAssertEqual(f.requests.filter { discoveryPaths.contains($0.url!.path) }.count, before,
          "No text discovery may use the replacement session; automatic library sync retains its owner")
      }
      XCTAssertEqual(f.token, "replacement-session"); XCTAssertTrue(f.posts.isEmpty)
      XCTAssertFalse(f.account.isBusy)
    }
  }

  @MainActor func testSavedActionsFreezeDefinitionAndUseIntegerRevisionIndependentOfDictation() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      let prepared = try await f.prepare()
      XCTAssertEqual(prepared.savedAction?.revision, "9223372036854775807")
      XCTAssertFalse(computer && f.computer.ready)
      f.computerCatalog = []; f.hostedCatalog = ["revision": 2, "actions": []]
      let localID = UUID().uuidString
      let result = try await f.destination.processText(localID, prepared: prepared, text: "Original")
      XCTAssertTrue(result.successful); XCTAssertEqual(result.text, "Changed"); XCTAssertEqual(f.posts.count, 1)
      let request = try XCTUnwrap(f.posts.last)
      let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
      XCTAssertEqual(ComputerJSON.integer(body["action_revision"]), Int(Int64.max))
      XCTAssertEqual(body["action_id"] as? String, "summary")
      XCTAssertNil(body["prompt"]); XCTAssertNil(body["writing_style"])
      XCTAssertEqual(request.url!.path, computer ? "/v1/computer/text" : "/v1/text-actions/execute")
      if computer { XCTAssertNotEqual(body["operation_id"] as? String, localID) }
      else { XCTAssertEqual(body["operation_id"] as? String, localID) }
    }
  }

  @MainActor func testEmptyFailedAndMalformedCatalogsNeverEnableLegacyFallback() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      for state in 0..<3 {
        f.computerCatalog = state == 0 ? [] : NSNull()
        f.hostedCatalog = state == 0 ? ["revision": 0, "actions": []] : ["actions": []]
        f.catalogFailure = state == 2 ? URLError(.timedOut) : nil
        do { _ = try await f.prepare("rewrite"); XCTFail("Unavailable catalogs cannot select a fixed action") } catch {}
        XCTAssertTrue(f.posts.isEmpty)
        XCTAssertEqual(f.destination.textActions.status, state == 0 ? .ready : .unavailable)
      }
      f.catalogFailure = nil; f.computerCatalog = nil; f.catalogStatus = 404
      let prepared = try await f.prepare("rewrite", language: "pt")
      XCTAssertNil(prepared.savedAction); XCTAssertEqual(prepared.language, "auto")
      _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Original")
      XCTAssertEqual(f.posts.count, 1)
      let body = try JSONSerialization.jsonObject(with: f.posts[0].httpBody!) as! [String: Any]
      XCTAssertEqual(Set(body.keys), ["operation_id", "action", "text", "language"])
    }
  }

  @MainActor func testMismatchedIdentityAndUncertainPostAreNeverRetried() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      let prepared = try await f.prepare()
      f.mismatch = true
      do { _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Original"); XCTFail("Wrong action identity accepted") } catch {}
      XCTAssertEqual(f.posts.count, 1)
      f.mismatch = false; f.postFailure = URLError(.networkConnectionLost)
      do { _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Original"); XCTFail("Uncertain POST accepted") } catch {}
      XCTAssertEqual(f.posts.count, 2)
    }
  }

  @MainActor func testUnsupportedStyleRejectsBeforePostAndIncompleteMetadataReturnsOriginalAsError() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      let choice = OutputPreferences(language: .de, style: .formal)
      do { _ = try await f.prepare(preferences: choice); XCTFail("Old service accepted explicit style") } catch {}
      XCTAssertTrue(f.posts.isEmpty)
      f.supportsPreferences = true
      let prepared = try await f.prepare(preferences: choice)
      let store = SharedState(root: f.root)
      _ = try store.setOutputPreference("language", value: "ru")
      _ = try store.setOutputPreference("style", value: "casual")
      let result = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Original")
      XCTAssertFalse(result.successful); XCTAssertTrue(result.outputPreferenceFailed); XCTAssertEqual(result.text, "Original")
      let body = try JSONSerialization.jsonObject(with: f.posts[0].httpBody!) as! [String: Any]
      XCTAssertEqual(body["language"] as? String, "auto"); XCTAssertEqual(body["writing_style"] as? String, "formal")
      XCTAssertNil(body["output_language"], "Selected-text language is separate from dictation output")
      f.provenance = ["writing_style_requested": "formal", "writing_style_applied": "formal", "writing_style_status": "applied"]
      let applied = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Original")
      XCTAssertTrue(applied.successful); XCTAssertEqual(applied.text, "Changed")
    }
  }

  @MainActor func testPreparedAccountCannotAdoptAnotherCredentialAndDestinationLossClearsProjection() async throws {
    let f = try Fixture(); defer { f.cleanup() }
    let prepared = try await f.prepare()
    f.token = "another-session"
    do { _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Private text"); XCTFail("Changed account authority accepted") } catch is CancellationError {}
    XCTAssertTrue(f.posts.isEmpty)
    try f.destination.select("computer")
    XCTAssertEqual(f.account.textActions.status, .unavailable)
    XCTAssertEqual(f.destination.textActions.status, .unavailable)
  }

  @MainActor func testLateCatalogCannotPublishAfterScopeLoss() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      f.pausePath = computer ? "/v1/computer/status" : "/v1/text-actions"
      let paused = expectation(description: "Catalog suspended")
      f.onRequest = { paused.fulfill() }
      let task = Task { try await f.prepare() }
      await fulfillment(of: [paused], timeout: 2)
      if computer { f.computer.suspend() } else { f.token = nil }
      f.suspended?.resume(); f.suspended = nil
      do { _ = try await task.value; XCTFail("Late catalog accepted") } catch {}
      XCTAssertEqual(f.destination.textActions.status, .unavailable); XCTAssertTrue(f.posts.isEmpty)
    }
  }

  @MainActor func testDictationSeparatesOutputFromRecognitionAndReturnsOriginalOnMissingApplicationMetadata() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      f.supportsPreferences = true
      if computer { try await f.computer.refresh() } else { try await f.account.refreshTextActions() }
      let preferences = OutputPreferences(language: .es, style: .formal)
      let id = UUID().uuidString
      if computer {
        // Text readiness must not grant dictation. Advertising dictate=false
        // keeps the new output preference path behind the original admission.
        do {
          _ = try await f.computer.process(id, wav: ComputerWAV.wrapPCM16(Data(repeating: 0, count: 8000)), language: "auto", preferences: preferences)
          XCTFail("Preferences must not enable dictation")
        } catch ComputerFailure.notReady {}
        XCTAssertTrue(f.posts.isEmpty)
        f.dictateReady = true; try await f.computer.refresh()
        let result = try await f.computer.process(UUID().uuidString, wav: ComputerWAV.wrapPCM16(Data(repeating: 0, count: 8000)), language: "auto", preferences: preferences)
        XCTAssertFalse(result.successful); XCTAssertTrue(result.outputPreferenceFailed); XCTAssertEqual(result.text, "Original")
        let body = try JSONSerialization.jsonObject(with: f.posts[0].httpBody!) as! [String: Any]
        XCTAssertEqual(body["language"] as? String, "auto"); XCTAssertEqual(body["output_language"] as? String, "es")
        XCTAssertEqual(body["writing_style"] as? String, "formal")
      } else {
        let clip = f.root.appendingPathComponent("synthetic.m4a"); try Data([0, 1, 2]).write(to: clip)
        let library = try LocalLibrary(root: f.root.appendingPathComponent("library"))
        let result = try await f.account.dictate(clip, operationID: id, library: library, preferences: preferences)
        XCTAssertTrue(result.outputPreferenceFailed); XCTAssertFalse(result.successful); XCTAssertEqual(result.text, "Original")
        let body = String(decoding: try XCTUnwrap(f.posts.last?.httpBody), as: UTF8.self)
        XCTAssertTrue(body.contains("name=\"output_language\"\r\n\r\nes\r\n"))
        XCTAssertTrue(body.contains("name=\"writing_style\"\r\n\r\nformal\r\n"))
        XCTAssertFalse(body.contains("name=\"language\""), "The old hosted ASR auto default is unchanged")
        f.provenance = ["output_language_requested": "es", "output_language_applied": NSNull(), "output_language_status": "standalone",
          "writing_style_requested": "formal", "writing_style_applied": NSNull(), "writing_style_status": "standalone",
          "text": "Exact saved snippet", "rewritten": false, "snippet_expanded": true]
        let standalone = try await f.account.dictate(clip, operationID: UUID().uuidString, library: library, preferences: preferences)
        XCTAssertTrue(standalone.successful); XCTAssertEqual(standalone.text, "Exact saved snippet")
        XCTAssertEqual(f.posts.count, 2, "Standalone metadata must never start another provider request")
      }
    }
  }

  @MainActor func testControlledDictationFailureKeepsInlineSnippetFallbackForBothDestinations() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      f.supportsPreferences = true; f.dictateReady = true
      if computer { try await f.computer.refresh() } else { try await f.account.refreshTextActions() }
      let preferences = OutputPreferences(language: .es, style: .formal)
      let transcript = "send my address today", expanded = "send Rua X today"
      let clip = f.root.appendingPathComponent("synthetic.m4a"); try Data([0, 1, 2]).write(to: clip)
      let library = try LocalLibrary(root: f.root.appendingPathComponent("library"))
      @MainActor func process() async throws -> (String, Bool, Bool) {
        if computer {
          let result = try await f.computer.process(UUID().uuidString,
            wav: ComputerWAV.wrapPCM16(Data(repeating: 0, count: 8000)), language: "auto", preferences: preferences)
          return (result.text, result.successful, result.outputPreferenceFailed)
        }
        let result = try await f.account.dictate(clip, operationID: UUID().uuidString, library: library, preferences: preferences)
        return (result.text, result.successful, result.outputPreferenceFailed)
      }
      for status in ["refinement_failed", "refinement_not_allowed"] {
        f.provenance = ["transcript": transcript, "text": expanded, "rewritten": computer, "successful": false,
          "snippet_expanded": true, "output_language_requested": "es", "output_language_applied": NSNull(), "output_language_status": status,
          "writing_style_requested": "formal", "writing_style_applied": NSNull(), "writing_style_status": status]
        let result = try await process()
        XCTAssertEqual(result.0, expanded); XCTAssertFalse(result.1); XCTAssertTrue(result.2)
      }
      // Incomplete, inconsistent or contradictory provenance must recover the
      // transcript instead of trusting a possibly transformed result.
      f.provenance.removeValue(forKey: "writing_style_applied")
      let incomplete = try await process(); XCTAssertEqual(incomplete.0, transcript)
      f.provenance["writing_style_applied"] = NSNull(); f.provenance["writing_style_status"] = "refinement_failed"
      let inconsistent = try await process(); XCTAssertEqual(inconsistent.0, transcript)
      f.provenance["writing_style_status"] = "refinement_not_allowed"; f.provenance["writing_style_applied"] = "formal"
      let contradictory = try await process(); XCTAssertEqual(contradictory.0, transcript)
    }
  }

  @MainActor func testCancelledTextAndLateAccountLossNeverReturnAnotherOwnersResult() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      let prepared = try await f.prepare()
      f.pausePath = computer ? "/v1/computer/text" : "/v1/text-actions/execute"
      let paused = expectation(description: "Processing suspended")
      f.onRequest = { paused.fulfill() }
      let id = UUID().uuidString
      let task = Task { try await f.destination.processText(id, prepared: prepared, text: "Private source") }
      await fulfillment(of: [paused], timeout: 2)
      task.cancel()
      if computer { f.computer.cancelOperation(id) } else { f.token = nil }
      f.suspended?.resume(); f.suspended = nil
      do { _ = try await task.value; XCTFail("Cancelled result returned") } catch is CancellationError {}
      XCTAssertEqual(f.posts.count, 1)
      if computer {
        do { _ = try await f.destination.processText(id, prepared: prepared, text: "Private source"); XCTFail("Cancelled ID restarted") } catch is CancellationError {}
        XCTAssertEqual(f.posts.count, 1)
      }
    }
  }

  @MainActor func testTextRequestAndResultBoundsRemainDestinationSpecific() async throws {
    for computer in [false, true] {
      let f = try Fixture(computer: computer); defer { f.cleanup() }
      let prepared = try await f.prepare()
      let limit = computer ? 32_768 : 16_000
      _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: String(repeating: "é", count: limit / 2))
      XCTAssertEqual(f.posts.count, 1)
      do {
        _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: String(repeating: "é", count: limit / 2 + 1))
        XCTFail("Oversized UTF-8 input accepted")
      } catch {}
      XCTAssertEqual(f.posts.count, 1)
      f.provenance = ["text": String(repeating: "x", count: computer ? 32_769 : 64_001)]
      do { _ = try await f.destination.processText(UUID().uuidString, prepared: prepared, text: "Source"); XCTFail("Oversized output accepted") } catch {}
      XCTAssertEqual(f.posts.count, 2)
    }
  }
}

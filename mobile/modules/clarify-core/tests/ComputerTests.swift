import AVFoundation
import XCTest
@testable import ClarifyContracts

final class ComputerTests: XCTestCase {
  private static let now = Date(timeIntervalSince1970: 1_800_000_000)
  private static let computer = UUID(uuidString: "4BE646DB-0E41-41BE-8BD9-D72885FC1AAD")!
  private static let device = UUID(uuidString: "E9C7D24E-9E4F-416B-98AC-F065B69B79E3")!
  private static let token = String(repeating: "x", count: 43)
  private static let route = ComputerRoute(url: "https://192.168.1.12:47653", certificateSHA256: String(repeating: "a", count: 64))
  private static var invitation: [String: Any] {
    ["schema_version": 1, "computer_id": computer.uuidString, "computer_name": "Fixture PC",
      "routes": [["url": route.url, "certificate_sha256": route.certificateSHA256!]],
      "pairing_token": Data(repeating: 7, count: 32).base64EncodedString().replacingOccurrences(of: "=", with: ""),
      "expires_at": ISO8601DateFormatter().string(from: now.addingTimeInterval(60))]
  }
  private static func qr(_ json: [String: Any]) throws -> String {
    "clarify://computer?data=" + (try JSONSerialization.data(withJSONObject: json)).base64EncodedString()
      .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
  }
  private static var credential: ComputerCredential {
    ComputerCredential(computerID: computer, computerName: "Fixture PC", deviceID: device, sessionToken: token, routes: [route])
  }
  func testInvitationAcceptsExactVersionOneAndRejectsUntrustedQRForms() throws {
    let valid = try Self.qr(Self.invitation)
    let result = try ComputerInvitation.parse(valid, now: Self.now)
    XCTAssertEqual(result.computerID, Self.computer); XCTAssertEqual(result.routes, [Self.route])
    for value in [valid + "&data=x", valid + "=", valid.replacingOccurrences(of: "clarify://computer", with: "https://computer"),
      valid.replacingOccurrences(of: "clarify://computer", with: "clarify://computer/"), "clarify://computer?data=" + String(repeating: "a", count: 12_000)] {
      XCTAssertThrowsError(try ComputerInvitation.parse(value, now: Self.now))
    }
    for (key, value) in [("schema_version", 2 as Any), ("schema_version", true as Any), ("computer_id", "not-a-uuid" as Any),
      ("computer_name", "\nPC" as Any), ("pairing_token", "short" as Any), ("expires_at", "2027-01-15T08:00:00+00:00" as Any),
      ("unexpected", "field" as Any), ("routes", [] as Any)] {
      var json = Self.invitation; json[key] = value
      XCTAssertThrowsError(try ComputerInvitation.parse(Self.qr(json), now: Self.now), key)
    }
    for seconds in [-1.0, 0, 301] {
      var json = Self.invitation; json["expires_at"] = ISO8601DateFormatter().string(from: Self.now.addingTimeInterval(seconds))
      XCTAssertThrowsError(try ComputerInvitation.parse(Self.qr(json), now: Self.now))
    }
    let json = String(data: try JSONSerialization.data(withJSONObject: Self.invitation), encoding: .utf8)!
    for key in ["schema_version", #"schema_\u0076ersion"#] {
      let duplicate = "{\"" + key + "\":1," + json.dropFirst()
      let encoded = Data(duplicate.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
      XCTAssertThrowsError(try ComputerInvitation.parse("clarify://computer?data=" + encoded, now: Self.now))
    }
  }
  func testRoutePolicyRejectsLoopbackCredentialsPathsAndUnpinnedLAN() throws {
    for url in ["http://192.168.1.12:47653", "https://127.0.0.1:47653", "https://[::1]:47653", "https://localhost:47653",
      "https://192.168.1.12:47653/", "https://user@192.168.1.12:47653", "https://192.168.1.12:47653?x=1",
      "https://192.168.1.12:47653#fragment", "https://8.8.8.8:47653", "https://192.168.001.12:47653"] {
      XCTAssertThrowsError(try ComputerRoute(url: url, certificateSHA256: Self.route.certificateSHA256).validated(), url)
    }
    XCTAssertThrowsError(try ComputerRoute(url: Self.route.url, certificateSHA256: nil).validated())
    XCTAssertThrowsError(try ComputerRoute(url: Self.route.url, certificateSHA256: "short").validated())
    XCTAssertNoThrow(try ComputerRoute(url: "https://computer.example.com", certificateSHA256: nil).validated())
    XCTAssertThrowsError(try ComputerRoute(url: "https://computer.local", certificateSHA256: nil).validated())
    // The invitation has no subnet mask. These can both be interface addresses
    // on a /16 LAN; the last octet alone cannot identify network/broadcast IPs.
    for address in ["10.0.1.0", "10.0.0.255"] {
      let route = ComputerRoute(url: "https://\(address):47653", certificateSHA256: Self.route.certificateSHA256)
      XCTAssertNoThrow(try route.validated())
      var invitation = Self.invitation
      invitation["routes"] = [["url": route.url, "certificate_sha256": route.certificateSHA256!]]
      XCTAssertEqual(try ComputerInvitation.parse(Self.qr(invitation), now: Self.now).routes, [route])
    }
  }
  func testPinMatchesOnlyExactDERAndRedirectsNeverForwardCredentials() throws {
    let der = Data("abc".utf8)
    let knownHash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    XCTAssertTrue(ComputerHTTPS.matchesCertificate(der, pin: knownHash))
    XCTAssertTrue(ComputerHTTPS.matchesCertificate(der, pin: knownHash.uppercased()))
    XCTAssertFalse(ComputerHTTPS.matchesCertificate(Data("abd".utf8), pin: knownHash))
    XCTAssertFalse(ComputerHTTPS.matchesCertificate(der, pin: String(repeating: "0", count: 64)))
    let url = URL(string: Self.route.url + "/v1/computer/status")!
    let delegate = ComputerHTTPS(route: Self.route, url: url)
    let session = URLSession(configuration: .ephemeral)
    defer { session.invalidateAndCancel() }
    let task = session.dataTask(with: url)
    let response = HTTPURLResponse(url: url, statusCode: 307, httpVersion: nil, headerFields: ["Location": "https://unrelated.example.com"])!
    var request = URLRequest(url: URL(string: "https://unrelated.example.com")!)
    request.setValue("Bearer fixture", forHTTPHeaderField: "Authorization")
    var callbacks = 0
    delegate.urlSession(session, task: task, willPerformHTTPRedirection: response, newRequest: request) { forwarded in
      callbacks += 1; XCTAssertNil(forwarded)
    }
    XCTAssertEqual(callbacks, 1)
  }

  @MainActor private final class Fixture {
    var saved: ComputerCredential?
    var requests: [URLRequest] = []
    var status = 200
    var replyComputer = ComputerTests.computer
    var suspended: CheckedContinuation<Void, Never>?
    var onProcessing: (() -> Void)?
    var invalidations = 0
    var failure: Error?
    lazy var connection = ComputerConnection(read: { self.saved }, save: { self.saved = $0 }, transport: { request, route in
      XCTAssertEqual(request.url?.host, URL(string: route.url)?.host)
      self.requests.append(request)
      if let failure = self.failure { throw failure }
      let path = request.url!.path
      var json: [String: Any] = [:]
      if path.hasSuffix("/pair") {
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        json = ["schema_version": 1, "computer_id": self.replyComputer.uuidString, "computer_name": "Fixture PC",
          "device_id": ComputerTests.device.uuidString, "session_token": ComputerTests.token]
      } else {
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + ComputerTests.token)
        if path.hasSuffix("/status") {
          json = ["schema_version": 1, "computer_id": self.replyComputer.uuidString, "computer_name": "Fixture PC", "ready": true]
        } else if request.httpMethod == "POST" {
          let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
          await withCheckedContinuation { self.suspended = $0; self.onProcessing?() }
          json = ["operation_id": body["operation_id"]!, "transcript": "Original", "text": "Revised", "rewritten": true, "successful": true]
        }
      }
      return (try JSONSerialization.data(withJSONObject: json), HTTPURLResponse(url: request.url!, statusCode: self.status, httpVersion: nil, headerFields: nil)!)
    })
    init(paired: Bool = true) { saved = paired ? ComputerTests.credential : nil }
    func resume() { suspended?.resume(); suspended = nil }
  }
  @MainActor func testPairStoresOnlyDeviceCredentialAndVerifiesComputerIdentity() async throws {
    let f = Fixture(paired: false)
    try await f.connection.pair(Self.qr(Self.invitation), deviceName: "Fixture iPhone", now: Self.now)
    XCTAssertEqual(f.saved, Self.credential)
    let persisted = String(data: try JSONEncoder().encode(f.saved), encoding: .utf8)!
    XCTAssertFalse(persisted.contains("pairing_token")); XCTAssertFalse(persisted.contains("expires_at"))
    let safe = String(data: try JSONSerialization.data(withJSONObject: f.connection.snapshot()), encoding: .utf8)!
    XCTAssertFalse(safe.contains(Self.token)); XCTAssertFalse(safe.contains(Self.route.url)); XCTAssertFalse(safe.contains("certificate"))
    let other = Fixture(paired: false); other.replyComputer = UUID()
    do { try await other.connection.pair(Self.qr(Self.invitation), deviceName: "Fixture", now: Self.now); XCTFail("Wrong computer accepted") }
    catch { XCTAssertNil(other.saved) }
  }
  @MainActor func testStatusExpiryInvalidatesWithoutHostedFallbackAndWrongIdentityIsRejected() async throws {
    let f = Fixture()
    f.connection.setInvalidationHandler { f.invalidations += 1 }
    try await f.connection.refresh(); XCTAssertTrue(f.connection.ready)
    f.status = 401
    do { try await f.connection.refresh(); XCTFail("Expired session accepted") } catch {}
    XCTAssertNil(f.saved); XCTAssertFalse(f.connection.configured); XCTAssertFalse(f.connection.ready)
    XCTAssertEqual(f.connection.status, "revoked"); XCTAssertEqual(f.invalidations, 1)
    XCTAssertTrue(f.requests.allSatisfy { $0.url?.path == "/v1/computer/status" })
    let other = Fixture(); other.replyComputer = UUID()
    do { try await other.connection.refresh(); XCTFail("Wrong identity accepted") } catch {}
    XCTAssertFalse(other.connection.ready)
  }
  @MainActor func testSwitchRejectsLateResultAndCancelsOriginalOperation() async throws {
    let f = Fixture(); try await f.connection.refresh()
    let started = expectation(description: "processing started")
    f.onProcessing = { started.fulfill() }
    let id = UUID().uuidString
    let task = Task { try await f.connection.process(id, action: "rewrite", text: "Original") }
    await fulfillment(of: [started], timeout: 2)
    f.connection.suspend(); f.resume()
    do { _ = try await task.value; XCTFail("Late result escaped") } catch is CancellationError {} catch { XCTFail("Unexpected error") }
    await Task.yield()
    XCTAssertEqual(f.requests.filter { $0.httpMethod == "POST" }.count, 1)
    XCTAssertTrue(f.requests.contains { $0.httpMethod == "DELETE" && $0.url?.path == "/v1/computer/operations/" + id })
  }
  @MainActor func testCancellationSendsBoundedDeleteAndDoesNotRepeatExpensiveRequest() async throws {
    let f = Fixture(); try await f.connection.refresh()
    let started = expectation(description: "processing started")
    f.onProcessing = { started.fulfill() }
    let task = Task { try await f.connection.process(UUID().uuidString, action: "translate", text: "Original", language: "es") }
    await fulfillment(of: [started], timeout: 2)
    task.cancel(); f.resume()
    do { _ = try await task.value; XCTFail("Cancelled result escaped") } catch is CancellationError {} catch { XCTFail("Unexpected error") }
    await Task.yield()
    XCTAssertEqual(f.requests.filter { $0.httpMethod == "POST" }.count, 1)
    XCTAssertTrue(f.requests.contains { $0.httpMethod == "DELETE" && $0.timeoutInterval == 2 })
  }
  @MainActor func testHistoryOwnerIsIsolatedFromGuestAndHostedAccounts() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let guest = HistoryEntry(id: UUID().uuidString, createdAt: 1, transcript: "Guest", text: "Guest", rewritten: false)
    let computer = HistoryEntry(id: UUID().uuidString, createdAt: 2, transcript: "Computer", text: "Computer", rewritten: false)
    let scope = Self.credential.scope
    let other = ComputerCredential(computerID: UUID(), computerName: "Other", deviceID: Self.device, sessionToken: Self.token, routes: [Self.route]).scope
    try library.record(guest); try library.record(computer, scope: scope)
    XCTAssertEqual(try library.history(scope: scope, includeLocal: false).entries, [computer])
    XCTAssertTrue(try library.history(scope: other, includeLocal: false).entries.isEmpty)
    XCTAssertEqual(try library.history(scope: "https://account.example.com|" + UUID().uuidString).entries, [guest])
    XCTAssertTrue(try library.historyBatch(scope: "https://account.example.com|" + UUID().uuidString).upserts.isEmpty)
    try library.clearHistory(scope: scope, includeLocal: false)
    XCTAssertEqual(try library.history().entries, [guest])
  }
  @MainActor func testComputerActivationRejectsModeChangeDuringPermissionWait() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let f = Fixture()
    let account = CloudAccount(defaults: defaults, transport: { _ in throw ComputerFailure.invalidResponse }, readCredential: { nil }, saveCredential: { _ in })
    let destination = ProcessingDestination(defaults: defaults, computer: f.connection, account: account)
    try destination.select("computer")
    var activated = false
    do {
      try await destination.withActivation(prepare: { try destination.select("hosted") }, activate: { activated = true })
      XCTFail("Activation adopted another mode")
    } catch {}
    XCTAssertFalse(activated)
    XCTAssertTrue(f.requests.allSatisfy { $0.url?.path == "/v1/computer/status" })
  }
  @MainActor func testComputerSelectionWithSignedInAccountNeverUsesHostedProcessingOrSync() async throws {
    let suite = "ClarifyTests.\(UUID().uuidString)", root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    let user = UUID().uuidString
    var metadata = CloudAccountState(); metadata.endpoint = "https://account.example.com"; metadata.userID = user; metadata.hosted = true; metadata.sync = true
    defaults.set(try JSONEncoder().encode(metadata), forKey: "clarify.account.metadata")
    var hostedRequests: [URLRequest] = []
    let account = CloudAccount(defaults: defaults, transport: { request in hostedRequests.append(request); throw ComputerFailure.offline }, readCredential: { "hosted-fixture-session" }, saveCredential: { _ in })
    XCTAssertTrue(account.configured)
    let f = Fixture(), library = try LocalLibrary(root: root)
    try library.saveDictionary([VocabularyEntry(term: "Hosted word")], scope: user)
    let destination = ProcessingDestination(defaults: defaults, computer: f.connection, account: account)
    try destination.select("computer")
    let signedIn = destination.snapshot()["signedIn"] as? Bool
    XCTAssertEqual(signedIn, true); XCTAssertEqual(destination.snapshot()["syncEnabled"] as? Bool, false)
    XCTAssertEqual(destination.historyScope, Self.credential.scope)
    let capture = destination.captureHistory()
    try library.record(HistoryEntry(id: UUID().uuidString, createdAt: 1, transcript: "PC only", text: "PC only", rewritten: false), scope: capture.scope)
    _ = try await destination.automaticRefresh(library)
    let synchronized = await destination.syncHistory(library, force: true)
    XCTAssertFalse(synchronized); XCTAssertTrue(hostedRequests.isEmpty)
    XCTAssertEqual(try library.dictionary(scope: user).map(\.term), ["Hosted word"])
    XCTAssertTrue(try library.historyBatch(scope: account.historyScope!).upserts.isEmpty)
    f.failure = ComputerFailure.offline
    do { _ = try await destination.automaticRefresh(library); XCTFail("Offline computer accepted") } catch {}
    XCTAssertTrue(hostedRequests.isEmpty); XCTAssertTrue(destination.computerMode)
    XCTAssertFalse(f.connection.ready)
    try destination.select("hosted")
    XCTAssertFalse(destination.acceptsHistory(capture)); XCTAssertTrue(account.configured)
  }
  func testWAVEnforcesPCM16Mono16kHzAndDurationBeforeUpload() throws {
    let valid = try ComputerWAV.wrapPCM16(Data(repeating: 0, count: 32_000))
    XCTAssertNoThrow(try ComputerWAV.validate(valid))
    var stereo = valid; stereo[22] = 2
    XCTAssertThrowsError(try ComputerWAV.validate(stereo))
    var aac = valid; aac[20] = 255
    XCTAssertThrowsError(try ComputerWAV.validate(aac))
    XCTAssertThrowsError(try ComputerWAV.wrapPCM16(Data(repeating: 0, count: ComputerWAV.maximumSamples * 2 + 2)))
    XCTAssertThrowsError(try ComputerWAV.wrapPCM16(Data([0])))
  }
  func testResultRejectsAnotherOperationAndBoundsComputerText() throws {
    let id = UUID().uuidString
    var json: [String: Any] = ["operation_id": UUID().uuidString, "transcript": "Original", "text": "Revised", "rewritten": true, "successful": true]
    XCTAssertThrowsError(try ComputerResult.decode(JSONSerialization.data(withJSONObject: json), operationID: id))
    json["operation_id"] = id
    let valid = try ComputerResult.decode(JSONSerialization.data(withJSONObject: json), operationID: id)
    XCTAssertEqual(valid.text, "Revised")
    json["text"] = String(repeating: "x", count: 32_769)
    XCTAssertThrowsError(try ComputerResult.decode(JSONSerialization.data(withJSONObject: json), operationID: id))
  }
  func testAACConversionProducesValidatedWAVWithoutReadingMicrophone() async throws {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).m4a")
    defer { try? FileManager.default.removeItem(at: url) }
    let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 2))
    let writer = try AudioClipWriter(url: url, inputFormat: format)
    let input = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4_800)); input.frameLength = 4_800
    for channel in 0..<2 { for index in 0..<4_800 { input.floatChannelData![channel][index] = Float(sin(Double(index) * 0.05)) * 0.2 } }
    for _ in 0..<10 { try writer.write(input) }; try writer.finish()
    let result = try await ComputerAudio.convert(url)
    XCTAssertNoThrow(try ComputerWAV.validate(result))
    XCTAssertGreaterThan(result.count, 30_000); XCTAssertLessThan(result.count, 34_000)
  }
}

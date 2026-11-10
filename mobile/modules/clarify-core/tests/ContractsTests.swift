import XCTest
@testable import ClarifyContracts

final class ContractsTests: XCTestCase {
  func testStateFromPreviousVersionPreservesTheLiveSession() throws {
    let data = Data(#"{"sessionActive":true,"heartbeat":123,"phase":"locked","operationID":"existing","configured":true}"#.utf8)
    let state = try JSONDecoder().decode(DictationSnapshot.self, from: data)
    XCTAssertTrue(state.sessionActive)
    XCTAssertEqual(state.phase, .locked)
    XCTAssertEqual(state.operationID, "existing")
    XCTAssertEqual(state.libraryRevision, 0)
    XCTAssertNil(state.errorCode); XCTAssertNil(state.errorPhase); XCTAssertNil(state.errorStatus)
  }
  func testErrorDiagnosticsSurviveTheNonsecretKeyboardStateBridge() throws {
    var state = DictationSnapshot(); state.phase = .error; state.operationID = UUID().uuidString
    state.message = "Failure"; state.errorCode = "no_speech"; state.errorPhase = "transcription"; state.errorStatus = 422
    let decoded = try JSONDecoder().decode(DictationSnapshot.self, from: JSONEncoder().encode(state))
    XCTAssertEqual(decoded.message, state.message); XCTAssertEqual(decoded.operationID, state.operationID)
    XCTAssertEqual(decoded.errorCode, "no_speech"); XCTAssertEqual(decoded.errorPhase, "transcription"); XCTAssertEqual(decoded.errorStatus, 422)
  }
  func testAtomicBridgeKeepsCommandsReceiptsAndStateSeparate() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = SharedState(root: root)
    var state = DictationSnapshot(); state.operationID = "first"; state.text = "Texto"; state.phase = .ready
    try store.write(state, to: "state.json")
    try store.send("start", operationID: "second", context: nil)
    try store.acknowledge("first")
    XCTAssertEqual(store.snapshot().text, "Texto")
    XCTAssertEqual(store.receipt(), "first")
    try store.send("lock", operationID: "second", context: nil)
    try store.send("finish", operationID: "second", context: nil)
    XCTAssertEqual(store.commands().map { $0.1.action }, ["start", "lock", "finish"])
    XCTAssertTrue(store.commands().allSatisfy { $0.1.operationID == "second" })
  }
  func testStaleSessionIsNotAdvertisedAsAvailable() {
    var state = DictationSnapshot(); state.sessionActive = true
    XCTAssertTrue(state.isLive)
    state.heartbeat -= 10
    XCTAssertFalse(state.isLive)
  }
  func testTapStartsOneContinuousClipAndWaitsForAcknowledgement() {
    var request = RecordingRequest()
    let now = Date().timeIntervalSince1970
    XCTAssertTrue(request.submit("start", operationID: "clip", now: now))
    XCTAssertFalse(request.submit("start", operationID: "duplicate", now: now))
    XCTAssertFalse(request.submit("finish", operationID: "clip", now: now))
    var state = DictationSnapshot(); state.sessionActive = true
    XCTAssertFalse(request.observe(state, now: now + 1))
    XCTAssertEqual(request.action, "start")
    state.operationID = "clip"; state.phase = .recording
    XCTAssertFalse(request.observe(state, now: now + 1))
    XCTAssertNil(request.action)
    XCTAssertTrue(request.submit("finish", operationID: "clip", now: now + 1))
    XCTAssertFalse(request.submit("finish", operationID: "clip", now: now + 1))
    state.phase = .transcribing
    XCTAssertFalse(request.observe(state, now: now + 2))
    XCTAssertNil(request.action)
  }
  func testKeyboardCasingPagesAndPortugueseAccents() {
    var keyboard = KeyboardState()
    XCTAssertEqual(keyboard.rows[0][0], "Q")
    keyboard.didInsert("Q")
    XCTAssertEqual(keyboard.rows[0][0], "q")
    keyboard.toggleShift(caps: true); keyboard.didInsert("Q")
    XCTAssertEqual(keyboard.rows[0][0], "Q")
    keyboard.page = .numbers
    XCTAssertEqual(keyboard.rows[0].joined(), "1234567890")
    keyboard.page = .symbols
    XCTAssertTrue(keyboard.rows.flatMap { $0 }.contains("€"))
    keyboard.didInsert(" ")
    XCTAssertEqual(keyboard.page, .letters)
    XCTAssertTrue(KeyboardState.accents(for: "a").contains("ã"))
    XCTAssertEqual(KeyboardState.accents(for: "C"), ["C", "Ç"])
  }
}

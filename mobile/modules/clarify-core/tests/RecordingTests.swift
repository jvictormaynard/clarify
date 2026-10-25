import XCTest
@testable import ClarifyContracts

final class RecordingTests: XCTestCase {
  func testEnergyTracksSpeechAndReturnsZeroForSilenceAndInvalidSamples() {
    XCTAssertEqual(AudioLevel.measure([Float](repeating: 0, count: 2048)), 0)
    XCTAssertEqual(AudioLevel.measure([Float.nan, .infinity, -.infinity]), 0)
    XCTAssertEqual(AudioLevel.measure([Float](repeating: 0.0001, count: 2048)), 0)
    let quiet = AudioLevel.measure([Float](repeating: 0.01, count: 2048))
    let voice = AudioLevel.measure([Float](repeating: 0.1, count: 2048))
    XCTAssertGreaterThan(quiet, 0); XCTAssertGreaterThan(voice, quiet)
    XCTAssertEqual(AudioLevel.measure([Float](repeating: 10, count: 2048)), 1)
    XCTAssertEqual(AudioLevel.measure([Float]()), 0)
  }
  func testMeterOnlyBelongsToTheCurrentFreshOperation() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = SharedState(root: root)
    let reading = AudioMeterReading(operationID: "clip", measuredAt: 100, level: 0.8)
    try store.publishAudioMeter(reading)
    let decoded = try XCTUnwrap(store.audioMeter())
    XCTAssertEqual(decoded.level(for: "clip", now: 100.2), 0.8)
    XCTAssertEqual(decoded.level(for: "other", now: 100.2), 0)
    XCTAssertEqual(decoded.level(for: nil, now: 100.2), 0)
    XCTAssertEqual(decoded.level(for: "clip", now: 101), 0)
    XCTAssertEqual(decoded.level(for: "clip", now: 99), 0)
    XCTAssertEqual(AudioMeterReading(operationID: "clip", measuredAt: 100, level: .nan).level(for: "clip", now: 100), 0)
    try store.publishAudioMeter(.inactive(now: 100.3))
    XCTAssertEqual(store.audioMeter()?.level(for: "clip", now: 100.3), 0)
    XCTAssertNil(store.snapshot().operationID)
    XCTAssertNil(store.receipt())
  }
  func testCancelBeforeAcknowledgementCannotBeOvertakenByLateStart() {
    var cancelled = RecordingCancellations()
    cancelled.cancel("clip", now: 100)
    XCTAssertFalse(cancelled.acceptsStart("clip", now: 100.1))
    XCTAssertTrue(cancelled.acceptsStart("other", now: 100.1))
    XCTAssertTrue(cancelled.acceptsStart("clip", now: 111))
    var request = RecordingRequest()
    XCTAssertTrue(request.submit("start", operationID: "clip", now: 100))
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: 100.1))
    XCTAssertFalse(request.submit("start", operationID: "other", now: 100.2))
  }
  func testUnacknowledgedStartTimesOutAfterTheCommandDeliveryWindow() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    var state = DictationSnapshot(); state.sessionActive = true
    XCTAssertTrue(request.submit("start", operationID: "clip", now: now))
    XCTAssertFalse(request.observe(state, now: now + 5))
    XCTAssertEqual(request.action, "start")
    XCTAssertTrue(request.observe(state, now: now + 6))
    XCTAssertNil(request.action)
  }
  func testCancelOnlyCompletesAfterTheAppPublishesAnAcknowledgement() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    var state = DictationSnapshot(); state.sessionActive = true; state.heartbeat = now - 0.5
    XCTAssertTrue(request.submit("start", operationID: "clip", now: now))
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: now + 0.1))
    request.observe(state, now: now + 0.2)
    XCTAssertEqual(request.action, "cancel")
    state.heartbeat = now + 0.3
    request.observe(state, now: now + 0.4)
    XCTAssertNil(request.action)
  }
  func testCompletedSnapshotBeforeCancelDoesNotEraseCancellationIntent() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    var state = DictationSnapshot(); state.sessionActive = true
    state.operationID = "clip"; state.phase = .recording; state.heartbeat = now
    XCTAssertTrue(request.submit("finish", operationID: "clip", now: now))
    XCTAssertEqual(request.action, "finish")
    // Completion reaches the store between the last poll and the Cancel tap.
    state.phase = .ready; state.text = "Do not insert"; state.heartbeat = now + 0.1
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: now + 0.2))
    XCTAssertFalse(request.observe(state, now: now + 0.3))
    XCTAssertEqual(request.action, "cancel", "A snapshot from before the tap is not an acknowledgement")
    XCTAssertTrue(request.isCancelled("clip"))
    // AudioSession.cancel republishes ready if processing has already ended.
    state.heartbeat = now + 0.4
    XCTAssertFalse(request.observe(state, now: now + 0.5))
    XCTAssertNil(request.action)
    XCTAssertTrue(request.isCancelled("clip"), "Acknowledgement must not permit publication")
    XCTAssertFalse(request.isCancelled("other"))
  }
  func testAcknowledgedCancelSuppressesLateReadyWithoutBlockingTheNextOperation() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    var state = DictationSnapshot(); state.sessionActive = true
    XCTAssertTrue(request.submit("start", operationID: "clip", now: now))
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: now + 0.1))
    XCTAssertFalse(request.submit("cancel", operationID: "clip", now: now + 0.2))
    state.heartbeat = now + 0.3
    request.observe(state, now: now + 0.4)
    XCTAssertNil(request.action)
    state.operationID = "clip"; state.phase = .ready; state.text = "Late result"
    request.observe(state, now: now + 0.5)
    XCTAssertTrue(request.isCancelled("clip"))
    XCTAssertTrue(request.submit("start", operationID: "next", now: now + 0.6))
    state.operationID = "next"; state.phase = .recording
    request.observe(state, now: now + 0.7)
    XCTAssertTrue(request.submit("finish", operationID: "next", now: now + 0.8))
    state.phase = .ready; state.text = "Keep this result"
    request.observe(state, now: now + 0.9)
    XCTAssertNil(request.action)
    XCTAssertFalse(request.isCancelled("next"))
    XCTAssertTrue(request.isCancelled("clip"), "A new operation must not revive the cancelled result")
  }
  func testCancelTimeoutReleasesTheCommandButKeepsLateResultsSuppressed() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    var state = DictationSnapshot(); state.sessionActive = true
    state.operationID = "clip"; state.phase = .transcribing; state.heartbeat = now
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: now))
    XCTAssertFalse(request.observe(state, now: now + 5.9))
    XCTAssertEqual(request.action, "cancel")
    XCTAssertFalse(request.submit("start", operationID: "next", now: now + 5.9))
    XCTAssertTrue(request.observe(state, now: now + 6))
    XCTAssertNil(request.action)
    state.phase = .ready; state.text = "Expired command result"; state.heartbeat = now + 7
    XCTAssertFalse(request.observe(state, now: now + 7))
    XCTAssertTrue(request.isCancelled("clip"))
    XCTAssertTrue(request.submit("start", operationID: "next", now: now + 7))
    XCTAssertFalse(request.isCancelled("next"))
  }
  func testExpiredSessionAndResetDoNotReviveCancelledResults() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    var state = DictationSnapshot(); state.sessionActive = true; state.heartbeat = now - 4
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: now))
    XCTAssertFalse(request.observe(state, now: now))
    XCTAssertNil(request.action)
    request.reset()
    state.operationID = "clip"; state.phase = .ready; state.text = "Late result"; state.heartbeat = now
    request.observe(state, now: now)
    XCTAssertTrue(request.isCancelled("clip"))
    XCTAssertTrue(request.submit("cancel", operationID: "second", now: now))
    request.reset()
    XCTAssertTrue(request.isCancelled("clip"))
    XCTAssertTrue(request.isCancelled("second"))
    XCTAssertTrue(request.submit("start", operationID: "next", now: now))
    XCTAssertFalse(request.isCancelled("next"))
  }
  func testRejectedCommandsDoNotCreateCancellationIntent() {
    let now = Date().timeIntervalSince1970
    var request = RecordingRequest()
    XCTAssertFalse(request.submit("invalid", operationID: "invalid", now: now))
    XCTAssertTrue(request.submit("start", operationID: "clip", now: now))
    XCTAssertFalse(request.submit("cancel", operationID: "other", now: now))
    XCTAssertFalse(request.isCancelled("other"))
    XCTAssertFalse(request.isCancelled("clip"))
    XCTAssertTrue(request.submit("cancel", operationID: "clip", now: now))
    XCTAssertFalse(request.submit("cancel", operationID: "other", now: now))
    XCTAssertTrue(request.isCancelled("clip"))
    XCTAssertFalse(request.isCancelled("other"))
  }
  func testCancelledReadyResultCannotClaimAReceiptAfterStoreRecreation() throws {
    for delivery in ["pending", "acknowledged", "timeout", "expired"] {
      let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
      try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
      defer { try? FileManager.default.removeItem(at: root) }
      let store = SharedState(root: root)
      let now = Date().timeIntervalSince1970
      var state = DictationSnapshot(); state.sessionActive = true; state.configured = true
      state.operationID = "cancelled"; state.phase = .ready; state.text = "Do not insert"
      state.heartbeat = now - 0.1
      try store.write(state, to: "state.json"); try store.acknowledge("previous")
      var request = RecordingRequest()
      XCTAssertTrue(request.submit("cancel", operationID: "cancelled", now: now))
      try store.send("cancel", operationID: "cancelled")
      if delivery == "acknowledged" { state.heartbeat = now + 0.1 }
      if delivery == "expired" { state.heartbeat = now - 4 }
      request.observe(state, now: delivery == "timeout" ? now + 6 : now + 0.2)
      XCTAssertEqual(request.action, delivery == "pending" ? "cancel" : nil, delivery)
      if delivery != "pending" {
        for (url, _) in store.commands() { try FileManager.default.removeItem(at: url) }
      }
      // Recreated controllers must reject even an app's retained or late result.
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json")
      let recreated = SharedState(root: root)
      XCTAssertThrowsError(try recreated.acknowledge("cancelled"), delivery)
      XCTAssertEqual(recreated.receipt(), "previous", "Cancel is not an insertion receipt")
      state.operationID = "next"; state.text = "Keep this result"
      try recreated.write(state, to: "state.json"); try recreated.acknowledge("next")
      XCTAssertEqual(recreated.receipt(), "next", delivery)
      XCTAssertThrowsError(try SharedState(root: root).acknowledge("cancelled"), delivery)
      XCTAssertEqual(recreated.receipt(), "next", "A late cancelled result cannot replace a newer receipt")
    }
  }
  func testCancellationMarkersPreserveOtherCancellationsAndLegacySharedData() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let legacy = Data(#"{"sessionActive":true,"heartbeat":123,"phase":"ready","operationID":"legacy","text":"Preserved text","configured":true}"#.utf8)
    try legacy.write(to: root.appendingPathComponent("state.json"), options: .atomic)
    let first = SharedState(root: root), second = SharedState(root: root)
    try first.acknowledge("previous")
    try first.send("cancel", operationID: "../cancelled/ação")
    try first.send("cancel", operationID: "aaa")
    try second.send("cancel", operationID: "another")
    for (url, _) in first.commands() { try FileManager.default.removeItem(at: url) }
    let recreated = SharedState(root: root)
    XCTAssertThrowsError(try recreated.acknowledge("../cancelled/ação"))
    XCTAssertThrowsError(try recreated.acknowledge("another"))
    XCTAssertEqual(recreated.receipt(), "previous")
    XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("state.json")), legacy)
    XCTAssertEqual(recreated.snapshot().text, "Preserved text")
    try recreated.acknowledge("aaG")
    XCTAssertEqual(recreated.receipt(), "aaG", "Legacy IDs stay distinct on case-insensitive storage")
    try recreated.acknowledge("legacy")
    XCTAssertEqual(recreated.receipt(), "legacy", "Completed legacy text remains explicitly insertable")
  }
}

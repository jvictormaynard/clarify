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
}

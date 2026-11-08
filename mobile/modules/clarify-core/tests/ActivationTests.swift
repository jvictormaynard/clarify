import XCTest
@testable import ClarifyContracts

final class ActivationTests: XCTestCase {
  func testOnlyTheMatchingFreshHandoffCanBeConsumedOnce() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = SharedState(root: root)
    let request = ActivationRequest(sourceBundleID: "net.whatsapp.WhatsApp", now: 100)
    try store.write(request, to: "activation.json")
    XCTAssertNil(store.consumeActivation("net.whatsapp.WhatsApp", now: 101))
    XCTAssertNil(store.consumeActivation(UUID().uuidString, now: 101))
    XCTAssertEqual(store.consumeActivation(request.token, now: 102)?.sourceBundleID, "net.whatsapp.WhatsApp")
    XCTAssertNil(store.consumeActivation(request.token, now: 103))
    let notes = ActivationRequest(sourceBundleID: "com.apple.mobilenotes", now: 110)
    try store.write(notes, to: "activation.json")
    XCTAssertNil(store.consumeActivation(request.token, now: 111))
    XCTAssertEqual(store.consumeActivation(notes.token, now: 111)?.sourceBundleID, "com.apple.mobilenotes")
  }
  func testExpiredAndFutureHandoffsAreDiscardedWithoutReturning() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = SharedState(root: root)
    for now in [99.0, 221.0] {
      let request = ActivationRequest(sourceBundleID: "net.whatsapp.WhatsApp", now: 100)
      try store.write(request, to: "activation.json")
      XCTAssertNil(store.consumeActivation(request.token, now: now))
      XCTAssertNil(store.read("activation.json", as: ActivationRequest.self))
    }
  }
}

import XCTest
@testable import ClarifyContracts

final class AudioRecoveryTests: XCTestCase {
  func testStoppedAudioSurvivesFailureRestartAndSuccessUntilExplicitDeletion() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let temporary = directory.appendingPathComponent("tmp")
    let root = directory.appendingPathComponent("saved")
    try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let id = UUID().uuidString
    let source = temporary.appendingPathComponent("clarify-\(id).m4a")
    let audio = Data(repeating: 0x51, count: 24_000)
    try audio.write(to: source)
    let store = AudioRecoveryStore(root: root, temporary: temporary)
    XCTAssertTrue(store.recordings(excluding: source).isEmpty)
    let retained = try store.retain(source, createdAt: 100, duration: 181)
    XCTAssertFalse(FileManager.default.fileExists(atPath: source.path))
    store.mark(id, status: .failed)
    let restarted = AudioRecoveryStore(root: root, temporary: temporary)
    let row = try XCTUnwrap(restarted.recordings().first)
    XCTAssertEqual(row.id, id); XCTAssertEqual(row.duration, 181); XCTAssertEqual(row.createdAt, 100)
    XCTAssertEqual(row.status, .failed)
    XCTAssertEqual(try Data(contentsOf: restarted.audioURL(id)), audio)
    restarted.mark(id, status: .complete, historyID: "history-item")
    try restarted.showOriginal(id)
    _ = try restarted.retain(retained, createdAt: 100, duration: 181)
    XCTAssertEqual(restarted.recordings().first?.historyID, "history-item")
    XCTAssertEqual(restarted.recordings().first?.useOriginal, true)
    restarted.mark(id, status: .complete)
    XCTAssertEqual(try Data(contentsOf: retained), audio)
    XCTAssertEqual(restarted.recordings().first?.status, .complete)
    try restarted.remove(id)
    XCTAssertTrue(restarted.recordings().isEmpty)
    XCTAssertThrowsError(try restarted.audioURL(id))
  }

  func testFailedArchiveWriteKeepsSourceDiscoverableAndRejectsForeignPaths() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let temporary = directory.appendingPathComponent("tmp")
    let blocked = directory.appendingPathComponent("blocked")
    try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    try Data([0]).write(to: blocked)
    let id = UUID().uuidString
    let source = temporary.appendingPathComponent("clarify-\(id).m4a")
    let audio = Data(repeating: 0x12, count: 1024)
    try audio.write(to: source)
    let store = AudioRecoveryStore(root: blocked, temporary: temporary)
    XCTAssertThrowsError(try store.retain(source, createdAt: 100, duration: 181))
    XCTAssertEqual(store.recordings().map(\.id), [id])
    XCTAssertEqual(try Data(contentsOf: store.audioURL(id)), audio)
    XCTAssertThrowsError(try store.audioURL("../secret"))
    XCTAssertThrowsError(try store.remove("../secret"))
    let foreign = directory.appendingPathComponent("foreign.m4a")
    try audio.write(to: foreign)
    try FileManager.default.removeItem(at: source)
    try FileManager.default.createSymbolicLink(at: source, withDestinationURL: foreign)
    XCTAssertTrue(store.recordings().isEmpty)
    XCTAssertThrowsError(try store.audioURL(id))
    XCTAssertEqual(try Data(contentsOf: foreign), audio)
  }
}

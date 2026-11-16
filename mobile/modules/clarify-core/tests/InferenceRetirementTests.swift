import XCTest
import Foundation
@testable import ClarifyContracts

final class InferenceRetirementTests: XCTestCase {
  @MainActor func testLegacyHostedSelectionRequiresComputerAndNeverSendsInference() async throws {
    let suite = "clarify.retirement." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState(); state.userID = UUID().uuidString; state.hosted = true
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    defaults.set("hosted", forKey: "clarify.processing.destination")
    var requests = 0
    let account = CloudAccount(defaults: defaults, transport: { _ in
      requests += 1; throw ComputerFailure.invalidResponse
    }, readCredential: { "fixture-only" }, saveCredential: { _ in })
    let computer = ComputerConnection(read: { nil }, save: { _ in })
    let destination = ProcessingDestination(defaults: defaults, computer: computer, account: account)
    XCTAssertTrue(account.configured)
    XCTAssertFalse(account.hosted); XCTAssertFalse(account.managed)
    XCTAssertTrue(destination.computerMode); XCTAssertFalse(destination.configured)
    XCTAssertNil(destination.historyScope); XCTAssertNotNil(account.historyScope)
    XCTAssertEqual(defaults.string(forKey: "clarify.processing.destination"), "computer")
    XCTAssertThrowsError(try destination.select("hosted"))
    let library = try LocalLibrary(root: root)
    do {
      _ = try await account.dictate(root.appendingPathComponent("must-not-be-read"), operationID: UUID().uuidString, library: library)
      XCTFail("Retired dictation accepted")
    } catch let error as ClarifyError { XCTAssertEqual(error.code, "inference_retired") }
    do {
      _ = try await account.processText(UUID().uuidString, action: "rewrite", text: "Source", language: "auto")
      XCTFail("Retired text accepted")
    } catch let error as ClarifyError { XCTAssertEqual(error.code, "inference_retired") }
    XCTAssertEqual(requests, 0)
  }
}

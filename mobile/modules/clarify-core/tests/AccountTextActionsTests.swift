import XCTest
import Foundation
@testable import ClarifyContracts

final class AccountTextActionsTests: XCTestCase {
  func testFullLibraryKeepsInt64RevisionsAndDescriptorBoundary() throws {
    let raw: [String: Any] = ["revision": Int64.max, "actions": [["id": "custom", "revision": Int64.max, "name": "Custom", "prompt": "Private instructions", "kind": "custom", "enabled": true]]]
    let library = try AccountTextActions(raw)
    let snapshot = library.snapshot(lease: "opaque", context: "generation")
    XCTAssertEqual(snapshot["revision"] as? String, String(Int64.max))
    XCTAssertEqual((snapshot["actions"] as? [[String: Any]])?.first?["revision"] as? String, String(Int64.max))
    XCTAssertFalse(String(describing: library.catalog.snapshot).contains("Private instructions"))
    XCTAssertThrowsError(try AccountTextActions.replacement(raw["actions"] as! [[String: Any]]))
  }

  @MainActor func testManagementCASConflictAndStaleLeaseNeverRetryOrAdoptCredentials() async throws {
    let suite = "clarify.actions." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    var metadata = CloudAccountState(); metadata.endpoint = "https://fixture.example"; metadata.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(metadata), forKey: "clarify.account.metadata")
    var credential: String? = "fixture-token"
    var requests: [URLRequest] = []
    let account = CloudAccount(defaults: defaults, transport: { request in
      requests.append(request)
      XCTAssertEqual(request.url?.path, "/v1/text-actions")
      let put = request.httpMethod == "PUT"
      if put {
        let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
        XCTAssertEqual((body["expected_revision"] as? NSNumber)?.stringValue, "9007199254740993")
      }
      let raw: [String: Any] = ["revision": Int64(9007199254740993), "actions": []]
      return (try JSONSerialization.data(withJSONObject: raw), HTTPURLResponse(url: request.url!, statusCode: put ? 409 : 200, httpVersion: nil, headerFields: nil)!)
    }, readCredential: { credential }, saveCredential: { credential = $0 })
    let library = try await account.getAccountTextActions(context: "context")
    let revision = library["revision"] as! String, lease = library["lease"] as! String
    do { _ = try await account.saveAccountTextActions([], revision: revision, lease: lease, context: "context"); XCTFail("Conflict accepted") } catch {}
    XCTAssertEqual(requests.count, 2)
    credential = "replacement-session"
    do { _ = try await account.saveAccountTextActions([], revision: revision, lease: lease, context: "context"); XCTFail("Stale session accepted") } catch {}
    XCTAssertEqual(requests.count, 2)
    account.clearTextCapabilities()
    do { _ = try await account.saveAccountTextActions([], revision: revision, lease: lease, context: "context"); XCTFail("Invalid lease accepted") } catch {}
    XCTAssertEqual(requests.count, 2)
  }
}

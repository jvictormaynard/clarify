import Foundation

// Full definitions are returned only to the containing app. SharedState stores
// TextActionCatalog descriptors and must never store this library or its lease.
struct AccountTextActions {
  let revision: Int64
  let actions: [[String: Any]]
  let catalog: TextActionCatalog

  init(_ raw: [String: Any]) throws {
    catalog = try TextActionCatalog.hosted(raw)
    guard let revision = ComputerJSON.integer(raw["revision"]),
      let actions = raw["actions"] as? [[String: Any]] else { throw ComputerFailure.invalidResponse }
    self.revision = Int64(revision); self.actions = actions
  }

  func snapshot(lease: String, context: String) -> [String: Any] {
    let rows = actions.map { row -> [String: Any] in
      var result = row
      result["revision"] = String(ComputerJSON.integer(row["revision"])!)
      return result
    }
    return ["revision": String(revision), "actions": rows, "lease": lease, "context": context]
  }

  static func replacement(_ rows: [[String: Any]]) throws -> [[String: Any]] {
    // Reuse the strict hosted parser before stripping server-owned revisions.
    let _: AccountTextActions = try .init(["revision": 0, "actions": rows.map { row in
      var value = row; value["revision"] = 1; return value
    }])
    guard rows.allSatisfy({ Set($0.keys) == ["id", "name", "prompt", "kind", "enabled"] }) else {
      throw ComputerFailure.invalidResponse
    }
    return rows
  }
}

import Foundation
import Security

struct ComputerCredential: Codable, Equatable {
  let computerID: UUID
  let computerName: String
  let deviceID: UUID
  let sessionToken: String
  let routes: [ComputerRoute]
  // All routes in one invitation name the same host. Sorting prevents route
  // order from changing the local owner after pairing again.
  var scope: String { "computer|" + computerID.uuidString.lowercased() + "|" + routes.map(\.url).sorted().joined(separator: "|") }
  func validate() throws {
    guard ComputerInvitation.validName(computerName), (1...4).contains(routes.count),
      Set(routes.map(\.url)).count == routes.count, Self.validToken(sessionToken) else { throw ComputerFailure.invalidResponse }
    for route in routes { _ = try route.validated() }
  }
  static func validToken(_ token: String) -> Bool {
    // Bearer credentials cannot contain header controls or whitespace.
    (32...512).contains(token.utf8.count) && token.utf8.allSatisfy { (33...126).contains($0) }
  }
}

// This item has no access group. Neither the keyboard nor React can read it.
enum ComputerKeychain {
  private static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "clarify.computer", kSecAttrAccount as String: "paired-device"]
  static func read() -> ComputerCredential? {
    var lookup = query
    lookup[kSecReturnData as String] = true; lookup[kSecMatchLimit as String] = kSecMatchLimitOne
    var item: CFTypeRef?
    guard SecItemCopyMatching(lookup as CFDictionary, &item) == errSecSuccess, let data = item as? Data,
      data.count <= 12_000, let credential = try? JSONDecoder().decode(ComputerCredential.self, from: data),
      (try? credential.validate()) != nil else { return nil }
    return credential
  }
  static func save(_ value: ComputerCredential?) throws {
    guard let value else {
      let status = SecItemDelete(query as CFDictionary)
      guard status == errSecSuccess || status == errSecItemNotFound else { throw ComputerFailure.authentication }
      return
    }
    try value.validate()
    let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(value),
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
    let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      guard SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else { throw ComputerFailure.authentication }
    } else if status != errSecSuccess { throw ComputerFailure.authentication }
  }
}

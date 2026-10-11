import Foundation
import Security

// Containing app Keychain only. Never add an app-group/keychain sharing group.
enum AccountCredential {
  private static let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "clarify.account", kSecAttrAccount as String: "session"
  ]
  static func read() -> String? {
    var q = query
    q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
    var item: CFTypeRef?
    guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
    return String(data: data, encoding: .utf8)
  }
  static func save(_ value: String?) throws {
    guard let value, !value.isEmpty else {
      let status = SecItemDelete(query as CFDictionary)
      guard status == errSecSuccess || status == errSecItemNotFound else { throw ClarifyError("Não foi possível remover a sessão.") }
      return
    }
    let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8),
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
    let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      guard SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else {
        throw ClarifyError("Não foi possível salvar a sessão.")
      }
    } else if status != errSecSuccess { throw ClarifyError("Não foi possível salvar a sessão.") }
  }
}

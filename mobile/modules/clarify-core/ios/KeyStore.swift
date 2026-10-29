import Foundation
import Security

enum KeyStore {
  private static var query: [String: Any] {
    [kSecClass as String: kSecClassGenericPassword,
     kSecAttrService as String: "clarify.groq", kSecAttrAccount as String: "api-key"]
  }
  static func read() -> String? {
    var q = query
    q[kSecReturnData as String] = true
    q[kSecMatchLimit as String] = kSecMatchLimitOne
    var item: CFTypeRef?
    guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
    return String(data: data, encoding: .utf8)
  }
  static func save(_ value: String) throws {
    let key = value.trimmingCharacters(in: .whitespacesAndNewlines)
    if key.isEmpty { SecItemDelete(query as CFDictionary); return }
    guard key.hasPrefix("gsk_"), !key.contains(where: { $0.isWhitespace }) else {
      throw ClarifyError(L("Informe uma chave válida do Groq."))
    }
    let attributes: [String: Any] = [
      kSecValueData as String: Data(key.utf8),
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    ]
    let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      guard SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else {
        throw ClarifyError(L("Não foi possível salvar a chave."))
      }
    } else if status != errSecSuccess { throw ClarifyError(L("Não foi possível salvar a chave.")) }
  }
}

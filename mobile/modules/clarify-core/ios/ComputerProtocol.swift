import Foundation

struct ComputerActionReadiness: Decodable, Equatable {
  let dictate: Bool
  let rewrite: Bool
  let translate: Bool
  static let unavailable = Self(dictate: false, rewrite: false, translate: false)
  var available: Bool { dictate || rewrite || translate }
  func allows(_ action: String) -> Bool {
    switch action {
    case "dictate": return dictate
    case "rewrite": return rewrite
    case "translate": return translate
    default: return false
    }
  }
  var snapshot: [String: Bool] { ["dictate": dictate, "rewrite": rewrite, "translate": translate] }
}

enum ComputerProtocolLimits {
  static let maximumResponseBytes = 512 * 1024
}

enum ComputerOperationID {
  // RFC 9562 UUIDv7: 48 timestamp bits, version 7, variant 10, 74 random bits.
  // Local recording, history, computer and device IDs keep their UUIDv4 format.
  static func make(now: Date = Date(), random: UUID = UUID()) throws -> UUID {
    let milliseconds = (now.timeIntervalSince1970 * 1000).rounded(.down)
    guard milliseconds.isFinite, milliseconds >= 0, milliseconds < 281_474_976_710_656 else { throw ComputerFailure.invalidResponse }
    let timestamp = UInt64(milliseconds)
    var bytes = random.uuid
    withUnsafeMutableBytes(of: &bytes) { bytes in
      for index in 0..<6 { bytes[index] = UInt8(truncatingIfNeeded: timestamp >> (8 * (5 - index))) }
      bytes[6] = (bytes[6] & 0x0f) | 0x70
      bytes[8] = (bytes[8] & 0x3f) | 0x80
    }
    return UUID(uuid: bytes)
  }
}

// JSONSerialization and JSONDecoder both accept duplicate object keys. Reject
// that ambiguity before interpreting a trust invitation, including escaped keys.
private struct ComputerJSONKeys {
  let bytes: [UInt8]
  var index = 0
  mutating func whitespace() { while index < bytes.count, [9, 10, 13, 32].contains(bytes[index]) { index += 1 } }
  mutating func string() -> String? {
    guard index < bytes.count, bytes[index] == 34 else { return nil }
    let start = index; index += 1
    while index < bytes.count {
      if bytes[index] == 92 { index += 2; continue }
      if bytes[index] == 34 {
        index += 1
        return try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index]))
      }
      index += 1
    }
    return nil
  }
  mutating func value(depth: Int = 0) -> Bool {
    whitespace()
    guard depth <= 8, index < bytes.count else { return false }
    if bytes[index] == 34 { return string() != nil }
    let opening = bytes[index]
    if opening == 123 || opening == 91 {
      let closing: UInt8 = opening == 123 ? 125 : 93
      index += 1; whitespace()
      if index < bytes.count, bytes[index] == closing { index += 1; return true }
      var keys = Set<String>()
      while index < bytes.count {
        if opening == 123 {
          whitespace()
          guard let key = string(), keys.insert(key).inserted else { return false }
          whitespace(); guard index < bytes.count, bytes[index] == 58 else { return false }; index += 1
        }
        guard value(depth: depth + 1) else { return false }
        whitespace(); guard index < bytes.count else { return false }
        if bytes[index] == closing { index += 1; return true }
        guard bytes[index] == 44 else { return false }; index += 1
      }
      return false
    }
    let start = index
    while index < bytes.count, ![9, 10, 13, 32, 44, 93, 125].contains(bytes[index]) { index += 1 }
    return index > start
  }
  static func unique(_ data: Data) -> Bool {
    var scanner = Self(bytes: Array(data))
    guard scanner.value() else { return false }
    scanner.whitespace(); return scanner.index == scanner.bytes.count
  }
}

struct ComputerRoute: Codable, Equatable {
  let url: String
  let certificateSHA256: String?
  enum CodingKeys: String, CodingKey { case url; case certificateSHA256 = "certificate_sha256" }

  func validated() throws -> Self {
    guard url.utf8.count <= 512, let parts = URLComponents(string: url), parts.scheme == "https",
      let host = parts.host, parts.user == nil, parts.password == nil, parts.path.isEmpty,
      parts.query == nil, parts.fragment == nil, !url.contains("%"),
      parts.port == nil || (1...65535).contains(parts.port!), parts.string == url else { throw ComputerFailure.invalidQR }
    let octets = host.split(separator: ".", omittingEmptySubsequences: false)
    let ipv4 = octets.count == 4 && octets.allSatisfy { part in
      guard let number = Int(part), (0...255).contains(number) else { return false }
      return String(number) == part
    }
    if let pin = certificateSHA256 {
      guard pin.count == 64, pin.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) || (65...70).contains($0) }), ipv4 else { throw ComputerFailure.invalidQR }
      let ip = octets.map { Int($0)! }
      guard ip[0] == 10 || (ip[0] == 172 && (16...31).contains(ip[1])) || (ip[0] == 192 && ip[1] == 168) else { throw ComputerFailure.invalidQR }
    } else {
      // Managed routes use public CA validation. IP literals, local names and
      // ambiguous numeric hosts cannot opt out of the LAN certificate pin.
      let labels = host.split(separator: ".", omittingEmptySubsequences: false)
      guard !ipv4, labels.count >= 2, host == host.lowercased(), host.count <= 253,
        !["local", "localhost", "internal", "test", "invalid"].contains(String(labels.last!)),
        labels.last!.contains(where: { $0.isASCII && $0.isLetter }),
        labels.allSatisfy({ label in
          !label.isEmpty && label.count <= 63 && label.first != "-" && label.last != "-" &&
            label.utf8.allSatisfy { (97...122).contains($0) || (48...57).contains($0) || $0 == 45 }
        }) else { throw ComputerFailure.invalidQR }
    }
    return self
  }
}

struct ComputerInvitation: Decodable {
  let schemaVersion: Int
  let computerID: UUID
  let computerName: String
  let routes: [ComputerRoute]
  let pairingToken: String
  let expiresAt: String
  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version", computerID = "computer_id", computerName = "computer_name"
    case routes, pairingToken = "pairing_token", expiresAt = "expires_at"
  }
  static func base64URL(_ value: String, bytes: Int? = nil) -> Data? {
    guard !value.isEmpty, value.utf8.allSatisfy({ (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95 }), value.count % 4 != 1 else { return nil }
    let padded = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/") + String(repeating: "=", count: (4 - value.count % 4) % 4)
    guard let data = Data(base64Encoded: padded), bytes == nil || data.count == bytes,
      data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") == value else { return nil }
    return data
  }
  static func parse(_ value: String, now: Date = Date()) throws -> Self {
    let prefix = "clarify://computer?data="
    guard value.utf8.count <= 12_000, value.hasPrefix(prefix),
      let data = base64URL(String(value.dropFirst(prefix.count))), data.count <= 8_192,
      let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
      ComputerJSONKeys.unique(data),
      Set(raw.keys) == Set(["schema_version", "computer_id", "computer_name", "routes", "pairing_token", "expires_at"]),
      let routes = raw["routes"] as? [[String: Any]], routes.allSatisfy({ Set($0.keys) == Set(["url", "certificate_sha256"]) }),
      let invitation = try? JSONDecoder().decode(Self.self, from: data), invitation.schemaVersion == 1,
      validName(invitation.computerName), (1...4).contains(invitation.routes.count),
      Set(invitation.routes.map(\.url)).count == invitation.routes.count,
      base64URL(invitation.pairingToken, bytes: 32) != nil,
      invitation.expiresAt.range(of: #"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z\z"#, options: .regularExpression) != nil else { throw ComputerFailure.invalidQR }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let fractional = formatter.date(from: invitation.expiresAt)
    formatter.formatOptions = [.withInternetDateTime]
    guard let expiry = fractional ?? formatter.date(from: invitation.expiresAt), expiry > now,
      expiry.timeIntervalSince(now) <= 300 else { throw ComputerFailure.expiredQR }
    for route in invitation.routes { _ = try route.validated() }
    return invitation
  }
  static func validName(_ name: String) -> Bool {
    !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && name.utf8.count <= 128 &&
      !name.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
  }
}

enum ComputerFailure: Error, LocalizedError, Equatable {
  case invalidQR, expiredQR, deviceLimit, offline, authentication, invalidResponse, notReady, cancelled, cameraDenied, cameraUnavailable, busy, invalidAudio
  var errorDescription: String? { L(message) }
  var message: String {
    switch self {
    case .invalidQR: return "O QR do computador é inválido. Gere outro QR no Clarify."
    case .expiredQR: return "O QR expirou. Gere outro QR no computador."
    case .deviceLimit: return "O computador atingiu o limite de celulares. No computador, revogue o acesso de um celular pareado antes de gerar um novo QR."
    case .authentication: return "A conexão foi revogada. Leia outro QR no computador."
    case .invalidResponse: return "O computador retornou uma resposta inválida."
    case .notReady: return "Configure o processamento no Clarify do computador."
    case .cancelled: return "Leitura do QR cancelada."
    case .cameraDenied: return "Permita o acesso à câmera em Ajustes > Clarify."
    case .cameraUnavailable: return "A câmera está indisponível. Tente novamente."
    case .busy: return "Aguarde a conexão com o computador."
    case .invalidAudio: return "Grave um áudio válido de até 5 minutos."
    case .offline: return "Não foi possível acessar o computador. Verifique se ele está ligado e na mesma rede Wi-Fi."
    }
  }
}

struct ComputerResult: Decodable {
  let operationID: UUID
  let transcript: String
  let text: String
  let rewritten: Bool
  let successful: Bool
  enum CodingKeys: String, CodingKey { case operationID = "operation_id", transcript, text, rewritten, successful }
  static func decode(_ data: Data, operationID: String) throws -> Self {
    guard let result = try? JSONDecoder().decode(Self.self, from: data), result.operationID == UUID(uuidString: operationID),
      !result.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      result.text.utf8.count <= 32_768, result.transcript.utf8.count <= 32_768 else { throw ComputerFailure.invalidResponse }
    return result
  }
}

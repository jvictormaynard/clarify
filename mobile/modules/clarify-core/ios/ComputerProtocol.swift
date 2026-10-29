import Foundation
import CryptoKit
import CoreFoundation

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
  static let maximumSealedResponseBytes = 704 * 1024
  static let maximumRequestBytes = 16 * 1024 * 1024 + 4096
  static let maximumSealedRequestBytes = 24 * 1024 * 1024
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

enum ComputerJSON {
  static func object(_ data: Data, maximum: Int, keys: Set<String>? = nil) throws -> [String: Any] {
    guard data.count <= maximum, ComputerJSONKeys.unique(data),
      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
      keys == nil || Set(object.keys) == keys else { throw ComputerFailure.invalidResponse }
    return object
  }
  static func integer(_ value: Any?) -> Int? {
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
      !["f", "d"].contains(String(cString: number.objCType)),
      let result = Int(number.stringValue) else { return nil }
    return result
  }
  static func base64URL(_ data: Data) -> String {
    data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
      .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
  }
}

struct ComputerCloudflareConfiguration: Equatable {
  let controlURL: String
  let domain: String
  static func current() throws -> Self? {
    try validate(controlURL: Bundle.main.object(forInfoDictionaryKey: "ClarifyConnectCloudflareControlURL"),
      domain: Bundle.main.object(forInfoDictionaryKey: "ClarifyConnectCloudflareDomain"))
  }
  static func validate(controlURL: Any?, domain: Any?) throws -> Self? {
    if controlURL == nil && domain == nil { return nil }
    guard let control = controlURL as? String, let domain = domain as? String,
      domain.utf8.count <= 198, ComputerRoute.validDNSHost(domain),
      let parts = URLComponents(string: control), parts.scheme == "https", let host = parts.host,
      ComputerRoute.validDNSHost(host), host == domain || host.hasSuffix("." + domain),
      parts.port == nil, parts.user == nil, parts.password == nil, parts.path.isEmpty,
      parts.query == nil, parts.fragment == nil, control == "https://" + host else { throw ComputerFailure.invalidQR }
    return Self(controlURL: control, domain: domain)
  }
  func contains(_ host: String) -> Bool { host == domain || host.hasSuffix("." + domain) }
  func hostname(publicKey: String) throws -> String {
    guard let key = ComputerInvitation.base64URL(publicKey, bytes: 32) else { throw ComputerFailure.invalidQR }
    let digest = SHA256.hash(data: key).map { String(format: "%02x", $0) }.joined()
    guard let label = ComputerRelayConfiguration.namespace(pin: digest) else { throw ComputerFailure.invalidQR }
    return "c-" + label + "." + domain
  }
}

struct ComputerRemoteRegistration {
  let controlURL: String
  let originPort: Int
  let certificateSHA256: String
  let hpkePublicKey: String
  static func parse(_ raw: Any, route: ComputerRoute, configuration: ComputerCloudflareConfiguration) throws -> Self {
    _ = try route.validated(relayHost: ComputerRelayConfiguration.host(), cloudflare: configuration)
    guard route.isLAN, let object = raw as? [String: Any],
      Set(object.keys) == Set(["control_url", "origin_port", "certificate_sha256", "hpke_public_key"]),
      let control = object["control_url"] as? String, control == configuration.controlURL,
      let port = ComputerJSON.integer(object["origin_port"]), (1...65535).contains(port),
      let pin = object["certificate_sha256"] as? String, ComputerRoute.validPin(pin),
      pin.lowercased() == route.certificateSHA256?.lowercased(),
      let key = object["hpke_public_key"] as? String, ComputerInvitation.base64URL(key, bytes: 32) != nil else { throw ComputerFailure.invalidResponse }
    return Self(controlURL: control, originPort: port, certificateSHA256: pin, hpkePublicKey: key)
  }
}

struct ComputerConnectGrant {
  let grant: String
  let expiresAt: Int
  let controlURL: String
  let hostname: String
  // Captured account authority never leaves the containing app.
  let accountIsCurrent: () -> Bool
  static func parse(_ data: Data, registration: ComputerRemoteRegistration,
    configuration: ComputerCloudflareConfiguration, now: Date, accountIsCurrent: @escaping () -> Bool) throws -> Self {
    let raw = try ComputerJSON.object(data, maximum: 4096,
      keys: ["schema_version", "grant", "expires_at", "control_url", "hostname"])
    guard ComputerJSON.integer(raw["schema_version"]) == 1,
      let grant = raw["grant"] as? String, ComputerInvitation.base64URL(grant, bytes: 32) != nil,
      let expires = ComputerJSON.integer(raw["expires_at"]), Double(expires) > now.timeIntervalSince1970,
      Double(expires) - now.timeIntervalSince1970 <= 300,
      let control = raw["control_url"] as? String, control == configuration.controlURL,
      control == registration.controlURL, let hostname = raw["hostname"] as? String,
      hostname == (try configuration.hostname(publicKey: registration.hpkePublicKey)) else { throw ComputerFailure.invalidResponse }
    return Self(grant: grant, expiresAt: expires, controlURL: control, hostname: hostname, accountIsCurrent: accountIsCurrent)
  }
}

enum ComputerRelayConfiguration {
  static func host() throws -> String? { try validate(Bundle.main.object(forInfoDictionaryKey: "ClarifyConnectRelayHost")) }
  static func validate(_ value: Any?) throws -> String? {
    guard let value else { return nil }
    // A namespace needs 52 ASCII bytes plus a dot within DNS's 253 byte limit.
    guard let host = value as? String, host.utf8.count <= 200, ComputerRoute.validDNSHost(host) else { throw ComputerFailure.invalidQR }
    return host
  }
  static func namespace(pin: String) -> String? {
    guard ComputerRoute.validPin(pin) else { return nil }
    let hex = Array(pin.utf8)
    func nibble(_ value: UInt8) -> UInt8 { value <= 57 ? value - 48 : (value | 32) - 97 + 10 }
    let alphabet = Array("abcdefghijklmnopqrstuvwxyz234567".utf8)
    var result = [UInt8](), buffer: UInt16 = 0, bits = 0
    for index in stride(from: 0, to: hex.count, by: 2) {
      buffer = (buffer << 8) | UInt16(nibble(hex[index]) << 4 | nibble(hex[index + 1])); bits += 8
      while bits >= 5 { bits -= 5; result.append(alphabet[Int((buffer >> bits) & 31)]) }
    }
    if bits > 0 { result.append(alphabet[Int((buffer << (5 - bits)) & 31)]) }
    return String(decoding: result, as: UTF8.self)
  }
}

struct ComputerRoute: Codable, Equatable {
  let url: String
  let certificateSHA256: String?
  var hpkePublicKey: String? = nil
  enum CodingKeys: String, CodingKey { case url; case certificateSHA256 = "certificate_sha256", hpkePublicKey = "hpke_public_key" }
  var isLAN: Bool {
    hpkePublicKey == nil && certificateSHA256 != nil &&
      URLComponents(string: url)?.host?.split(separator: ".").last?.allSatisfy(\.isNumber) == true
  }
  static func parse(_ raw: Any, cloudflare: ComputerCloudflareConfiguration?) throws -> Self {
    guard let raw = raw as? [String: Any],
      Set(raw.keys) == Set(["url", "certificate_sha256"]) ||
        Set(raw.keys) == Set(["url", "certificate_sha256", "hpke_public_key"]),
      let data = try? JSONSerialization.data(withJSONObject: raw),
      let route = try? JSONDecoder().decode(Self.self, from: data),
      raw["hpke_public_key"] == nil || route.hpkePublicKey != nil else { throw ComputerFailure.invalidQR }
    return try route.validated(relayHost: ComputerRelayConfiguration.host(), cloudflare: cloudflare)
  }

  static func validPin(_ pin: String) -> Bool {
    pin.utf8.count == 64 && pin.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) || (65...70).contains($0) }
  }
  static func validDNSHost(_ host: String) -> Bool {
    let labels = host.split(separator: ".", omittingEmptySubsequences: false)
    return labels.count >= 2 && host.utf8.count <= 253 &&
      !["local", "localhost", "internal", "test", "invalid"].contains(String(labels.last!)) &&
      labels.last!.utf8.contains(where: { (97...122).contains($0) }) &&
      labels.allSatisfy { label in
        !label.isEmpty && label.utf8.count <= 63 && label.first != "-" && label.last != "-" &&
          label.utf8.allSatisfy { (97...122).contains($0) || (48...57).contains($0) || $0 == 45 }
      }
  }
  var statusTimeout: TimeInterval {
    // Sequential discovery stays short on cellular even with three LAN routes.
    // Only validated pinned RFC1918 literals can contain a numeric final label.
    (URLComponents(string: url)?.host?.split(separator: ".").last?.allSatisfy(\.isNumber) == true) ? 1.5 : 5
  }
  func validated() throws -> Self { try validated(relayHost: ComputerRelayConfiguration.host(), cloudflare: ComputerCloudflareConfiguration.current()) }
  func validated(relayHost: String?) throws -> Self {
    try validated(relayHost: relayHost, cloudflare: ComputerCloudflareConfiguration.current())
  }
  func validated(relayHost: String?, cloudflare: ComputerCloudflareConfiguration?) throws -> Self {
    let relayHost = try ComputerRelayConfiguration.validate(relayHost)
    guard url.utf8.count <= 512, let parts = URLComponents(string: url), parts.scheme == "https",
      let host = parts.host, parts.user == nil, parts.password == nil, parts.path.isEmpty,
      parts.query == nil, parts.fragment == nil, !url.contains("%"),
      parts.port == nil || (1...65535).contains(parts.port!), parts.string == url else { throw ComputerFailure.invalidQR }
    // Preserve valid explicit ports exactly, including existing zero padding.
    // Reject empty/nondecimal ports and any change to the scanned authority.
    let authority = "https://" + host
    let suffix = url.dropFirst(authority.count)
    guard url.hasPrefix(authority), suffix.isEmpty ? parts.port == nil :
      suffix.first == ":" && parts.port != nil && !suffix.dropFirst().isEmpty &&
        suffix.dropFirst().utf8.allSatisfy({ (48...57).contains($0) }) else { throw ComputerFailure.invalidQR }
    if hpkePublicKey != nil || cloudflare?.contains(host) == true {
      guard let cloudflare, let key = hpkePublicKey, certificateSHA256 == nil,
        host == (try cloudflare.hostname(publicKey: key)),
        url == "https://" + host || url == "https://" + host + ":443" else { throw ComputerFailure.invalidQR }
      return self
    }
    let octets = host.split(separator: ".", omittingEmptySubsequences: false)
    let ipv4 = octets.count == 4 && octets.allSatisfy { part in
      guard let number = Int(part), (0...255).contains(number) else { return false }
      return String(number) == part
    }
    if let pin = certificateSHA256, !Self.validPin(pin) { throw ComputerFailure.invalidQR }
    if ipv4 {
      guard certificateSHA256 != nil else { throw ComputerFailure.invalidQR }
      let ip = octets.map { Int($0)! }
      guard ip[0] == 10 || (ip[0] == 172 && (16...31).contains(ip[1])) || (ip[0] == 192 && ip[1] == 168) else { throw ComputerFailure.invalidQR }
    } else {
      guard Self.validDNSHost(host) else { throw ComputerFailure.invalidQR }
      if let relayHost, host == relayHost || host.hasSuffix("." + relayHost) {
        // One lowercase RFC4648 label, bound to the QR's exact leaf DER pin.
        // This also forbids CA-only routes anywhere in the ATS exception scope.
        guard let pin = certificateSHA256, let namespace = ComputerRelayConfiguration.namespace(pin: pin),
          host == namespace + "." + relayHost else { throw ComputerFailure.invalidQR }
      }
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
  static func parse(_ value: String, now: Date = Date(), cloudflare: ComputerCloudflareConfiguration? = nil) throws -> Self {
    let cloudflare = try cloudflare ?? ComputerCloudflareConfiguration.current()
    let prefix = "clarify://computer?data="
    guard value.utf8.count <= 12_000, value.hasPrefix(prefix),
      let data = base64URL(String(value.dropFirst(prefix.count))), data.count <= 8_192,
      let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
      ComputerJSONKeys.unique(data),
      Set(raw.keys) == Set(["schema_version", "computer_id", "computer_name", "routes", "pairing_token", "expires_at"]),
      let routes = raw["routes"] as? [[String: Any]],
      routes.allSatisfy({ (try? ComputerRoute.parse($0, cloudflare: cloudflare)) != nil }),
      let invitation = try? JSONDecoder().decode(Self.self, from: data),
      ComputerJSON.integer(raw["schema_version"]) == invitation.schemaVersion,
      invitation.schemaVersion == (invitation.routes.contains(where: { $0.hpkePublicKey != nil }) ? 2 : 1),
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
    for route in invitation.routes { _ = try route.validated(relayHost: ComputerRelayConfiguration.host(), cloudflare: cloudflare) }
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
    case .offline: return "Não foi possível acessar o computador. Verifique se ele está ligado e conectado à rede."
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

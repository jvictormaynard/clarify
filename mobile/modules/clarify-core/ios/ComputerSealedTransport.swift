import Foundation
import CryptoKit
import Security

enum ComputerSealedTransport {
  static let info = Data("clarify-computer-http-v1".utf8)
  static let responseLabel = Data("clarify-computer-response-v1".utf8)
  struct Prepared {
    let request: URLRequest
    let originalURL: URL
    let requestID: String
    let replyKey: SymmetricKey
    let associatedData: Data
  }
  static func random(_ count: Int) throws -> Data {
    var data = Data(count: count)
    let result = data.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, count, $0.baseAddress!) }
    guard result == errSecSuccess else { throw ComputerFailure.invalidResponse }
    return data
  }
  @available(iOS 17.0, macOS 14.0, *)
  static func prepare(_ request: URLRequest, route: ComputerRoute, now: Date = Date(),
    cloudflare: ComputerCloudflareConfiguration? = nil) throws -> Prepared {
    _ = try route.validated(relayHost: ComputerRelayConfiguration.host(), cloudflare: cloudflare ?? ComputerCloudflareConfiguration.current())
    guard let key = route.hpkePublicKey.flatMap({ ComputerInvitation.base64URL($0, bytes: 32) }),
      let url = request.url, let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
      let method = request.httpMethod, ["GET", "POST", "DELETE"].contains(method),
      url.absoluteString == route.url + parts.path, parts.path.hasPrefix("/v1/computer/"),
      !parts.path.contains("%"), !parts.path.contains(".."), !parts.path.contains("//"),
      parts.path != "/v1/computer/sealed", parts.query == nil, parts.fragment == nil,
      request.httpBodyStream == nil, request.value(forHTTPHeaderField: "Cookie") == nil,
      request.value(forHTTPHeaderField: "X-Session-Token") == nil,
      request.timeoutInterval.isFinite, request.timeoutInterval > 0, request.timeoutInterval <= 300,
      now.timeIntervalSince1970.isFinite, now.timeIntervalSince1970 >= 0,
      now.timeIntervalSince1970 < Double(Int.max) - 301 else { throw ComputerFailure.invalidResponse }
    let authorization = request.value(forHTTPHeaderField: "Authorization")
    if let authorization {
      guard authorization.hasPrefix("Bearer "), ComputerCredential.validToken(String(authorization.dropFirst(7))) else { throw ComputerFailure.authentication }
    }
    let body = try request.httpBody.map { try ComputerJSON.object($0, maximum: ComputerProtocolLimits.maximumRequestBytes) }
    let replyBytes = try random(32), requestID = ComputerJSON.base64URL(try random(16))
    let clear = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "method": method,
      "path": parts.path, "authorization": authorization as Any? ?? NSNull(), "body": body as Any? ?? NSNull(),
      "reply_key": ComputerJSON.base64URL(replyBytes), "request_id": requestID,
      // Leave one minute below the host's five-minute admission bound so a
      // small difference between device clocks does not reject every request.
      "expires_at": Int(now.timeIntervalSince1970.rounded(.down)) + 240])
    guard clear.count <= ComputerProtocolLimits.maximumRequestBytes else { throw ComputerFailure.invalidResponse }
    var sender = try HPKE.Sender(recipientKey: Curve25519.KeyAgreement.PublicKey(rawRepresentation: key),
      ciphersuite: .Curve25519_SHA256_ChachaPoly, info: info)
    let encrypted = try sender.seal(clear)
    let ciphertext = sender.encapsulatedKey + encrypted
    let envelope = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "ciphertext": ComputerJSON.base64URL(ciphertext)])
    guard envelope.count <= ComputerProtocolLimits.maximumSealedRequestBytes,
      let outerURL = URL(string: route.url + "/v1/computer/sealed") else { throw ComputerFailure.invalidResponse }
    var outer = URLRequest(url: outerURL)
    outer.httpMethod = "POST"; outer.timeoutInterval = request.timeoutInterval; outer.httpBody = envelope
    outer.setValue("application/json", forHTTPHeaderField: "Accept")
    outer.setValue("application/json", forHTTPHeaderField: "Content-Type")
    outer.setValue("no-store", forHTTPHeaderField: "Cache-Control")
    return Prepared(request: outer, originalURL: url, requestID: requestID, replyKey: SymmetricKey(data: replyBytes),
      associatedData: responseLabel + Data(SHA256.hash(data: ciphertext)))
  }
  static func open(_ data: Data, response: HTTPURLResponse, prepared: Prepared) throws -> (Data, HTTPURLResponse) {
    guard response.url == prepared.request.url, response.statusCode == 200,
      response.value(forHTTPHeaderField: "Content-Type")?.split(separator: ";").first?.trimmingCharacters(in: .whitespaces).lowercased() == "application/json" else { throw ComputerFailure.invalidResponse }
    let envelope = try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumSealedResponseBytes, keys: ["schema_version", "ciphertext"])
    guard ComputerJSON.integer(envelope["schema_version"]) == 1, let encoded = envelope["ciphertext"] as? String,
      let encrypted = ComputerInvitation.base64URL(encoded), encrypted.count >= 28,
      encrypted.count <= ComputerProtocolLimits.maximumResponseBytes + 28 else { throw ComputerFailure.invalidResponse }
    let clear: Data
    do {
      clear = try ChaChaPoly.open(ChaChaPoly.SealedBox(combined: encrypted), using: prepared.replyKey, authenticating: prepared.associatedData)
    } catch { throw ComputerFailure.invalidResponse }
    let inner = try ComputerJSON.object(clear, maximum: ComputerProtocolLimits.maximumResponseBytes,
      keys: ["schema_version", "request_id", "status", "body"])
    guard ComputerJSON.integer(inner["schema_version"]) == 1, inner["request_id"] as? String == prepared.requestID,
      let code = ComputerJSON.integer(inner["status"]), (100...599).contains(code), let body = inner["body"] as? [String: Any],
      let response = HTTPURLResponse(url: prepared.originalURL, statusCode: code, httpVersion: nil,
        headerFields: ["Content-Type": "application/json", "Cache-Control": "no-store"]) else { throw ComputerFailure.invalidResponse }
    return (try JSONSerialization.data(withJSONObject: body), response)
  }
  static func send(_ request: URLRequest, route: ComputerRoute) async throws -> (Data, HTTPURLResponse) {
    try await send(request, route: route, transport: ComputerHTTPS.send)
  }
  static func send(_ request: URLRequest, route: ComputerRoute,
    transport: (URLRequest, ComputerRoute) async throws -> (Data, HTTPURLResponse)) async throws -> (Data, HTTPURLResponse) {
    guard route.hpkePublicKey != nil else { return try await transport(request, route) }
    guard #available(iOS 17.0, macOS 14.0, *) else { throw ComputerFailure.notReady }
    try Task.checkCancellation()
    let prepared = try prepare(request, route: route)
    // Each API call has one envelope and one network attempt. In particular,
    // a failed processing POST never falls back to another route.
    let (data, response) = try await transport(prepared.request, route)
    try Task.checkCancellation()
    return try open(data, response: response, prepared: prepared)
  }
}

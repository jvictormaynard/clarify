import Foundation
import Security
import CryptoKit

// One ephemeral session per request and exact route. Its delegate cannot apply
// a certificate trust exception, cookies or a credential to another destination.
final class ComputerHTTPS: NSObject, URLSessionDataDelegate, @unchecked Sendable {
  private let route: ComputerRoute?
  private let expectedURL: URL
  private let maximumResponseBytes: Int
  private let lock = NSLock()
  private var session: URLSession?
  private var continuation: CheckedContinuation<(Data, HTTPURLResponse), Error>?
  private var response: HTTPURLResponse?
  private var body = Data()
  private var cancelled = false

  init(route: ComputerRoute, url: URL) {
    self.route = route; expectedURL = url
    maximumResponseBytes = route.hpkePublicKey == nil ? ComputerProtocolLimits.maximumResponseBytes : ComputerProtocolLimits.maximumSealedResponseBytes
  }
  private init(url: URL, maximumResponseBytes: Int) {
    route = nil; expectedURL = url; self.maximumResponseBytes = maximumResponseBytes
  }
  static func matchesCertificate(_ der: Data, pin: String) -> Bool {
    let fingerprint = SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
    return fingerprint == pin.lowercased()
  }
  static func validatedURL(_ request: URLRequest, route: ComputerRoute) throws -> URL {
    _ = try route.validated()
    guard let base = URL(string: route.url), let url = request.url, url.scheme == "https",
      url.host == base.host, url.port == base.port, url.user == nil, url.password == nil,
      url.query == nil, url.fragment == nil,
      url.absoluteString.hasPrefix(route.url + "/v1/computer/") else { throw ComputerFailure.invalidResponse }
    if route.hpkePublicKey != nil {
      guard url.absoluteString == route.url + "/v1/computer/sealed", request.httpMethod == "POST",
        request.value(forHTTPHeaderField: "Authorization") == nil,
        request.value(forHTTPHeaderField: "X-Session-Token") == nil,
        request.value(forHTTPHeaderField: "Cookie") == nil,
        request.value(forHTTPHeaderField: "Content-Type") == "application/json",
        let body = request.httpBody else { throw ComputerFailure.invalidResponse }
      let raw = try ComputerJSON.object(body, maximum: ComputerProtocolLimits.maximumSealedRequestBytes, keys: ["schema_version", "ciphertext"])
      guard ComputerJSON.integer(raw["schema_version"]) == 1, let value = raw["ciphertext"] as? String,
        let ciphertext = ComputerInvitation.base64URL(value), ciphertext.count >= 48 else { throw ComputerFailure.invalidResponse }
    }
    return url
  }
  static func configuration(for request: URLRequest) -> URLSessionConfiguration {
    let config = URLSessionConfiguration.ephemeral
    config.httpCookieStorage = nil; config.httpShouldSetCookies = false; config.urlCache = nil
    config.urlCredentialStorage = nil; config.requestCachePolicy = .reloadIgnoringLocalCacheData
    // The resource limit bounds the complete discovery, including a slow body.
    config.timeoutIntervalForResource = request.timeoutInterval
    config.tlsMinimumSupportedProtocolVersion = .TLSv12
    return config
  }
  static func send(_ request: URLRequest, route: ComputerRoute) async throws -> (Data, HTTPURLResponse) {
    let url = try validatedURL(request, route: route)
    let transport = ComputerHTTPS(route: route, url: url)
    return try await transport.perform(request)
  }
  // Account and grant requests use system TLS at an exact URL selected by the
  // caller's fixed public configuration, with the same bounded session policy.
  static func validatedFixedURL(_ request: URLRequest, expectedURL: URL, maximumResponseBytes: Int) throws -> URL {
    guard request.url == expectedURL, expectedURL.scheme == "https", expectedURL.user == nil,
      expectedURL.password == nil, expectedURL.query == nil, expectedURL.fragment == nil,
      ["GET", "POST"].contains(request.httpMethod ?? ""), request.httpBodyStream == nil,
      (request.httpBody?.count ?? 0) <= 4096,
      request.value(forHTTPHeaderField: "Cookie") == nil, request.value(forHTTPHeaderField: "Authorization") == nil,
      request.timeoutInterval.isFinite, request.timeoutInterval > 0, request.timeoutInterval <= 15,
      maximumResponseBytes > 0, maximumResponseBytes <= ComputerProtocolLimits.maximumResponseBytes else { throw ComputerFailure.invalidResponse }
    return expectedURL
  }
  static func sendFixed(_ request: URLRequest, expectedURL: URL, maximumResponseBytes: Int) async throws -> (Data, HTTPURLResponse) {
    _ = try validatedFixedURL(request, expectedURL: expectedURL, maximumResponseBytes: maximumResponseBytes)
    return try await ComputerHTTPS(url: expectedURL, maximumResponseBytes: maximumResponseBytes).perform(request)
  }
  private func perform(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
    try Task.checkCancellation()
    return try await withTaskCancellationHandler(operation: {
      try await withCheckedThrowingContinuation { continuation in self.start(request, continuation: continuation) }
    }, onCancel: { self.cancel() })
  }
  private func start(_ request: URLRequest, continuation: CheckedContinuation<(Data, HTTPURLResponse), Error>) {
    lock.lock(); defer { lock.unlock() }
    guard !cancelled else { continuation.resume(throwing: CancellationError()); return }
    self.continuation = continuation
    let config = Self.configuration(for: request)
    let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    self.session = session
    session.dataTask(with: request).resume()
  }
  private func cancel() {
    lock.lock(); cancelled = true; let session = session; lock.unlock()
    session?.invalidateAndCancel()
  }
  func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
    let space = challenge.protectionSpace
    guard space.authenticationMethod == NSURLAuthenticationMethodServerTrust, !space.isProxy(), challenge.previousFailureCount == 0,
      space.host == expectedURL.host, space.port == (expectedURL.port ?? 443), space.protocol == "https" else {
      completionHandler(.cancelAuthenticationChallenge, nil); return
    }
    guard let route else { completionHandler(.performDefaultHandling, nil); return }
    let bound = route.hpkePublicKey == nil ? (try? Self.validatedURL(URLRequest(url: expectedURL), route: route)) == expectedURL :
      expectedURL.absoluteString == route.url + "/v1/computer/sealed"
    guard bound, (try? route.validated()) != nil else { completionHandler(.cancelAuthenticationChallenge, nil); return }
    guard let pin = route.certificateSHA256 else { completionHandler(.performDefaultHandling, nil); return }
    guard let trust = space.serverTrust, let cert = SecTrustGetCertificateAtIndex(trust, 0) else {
      completionHandler(.cancelAuthenticationChallenge, nil); return
    }
    guard Self.matchesCertificate(SecCertificateCopyData(cert) as Data, pin: pin) else { completionHandler(.cancelAuthenticationChallenge, nil); return }
    completionHandler(.useCredential, URLCredential(trust: trust))
  }
  func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
    // Do not respond to Basic, Digest, proxy or client-certificate challenges.
    completionHandler(.cancelAuthenticationChallenge, nil)
  }
  func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
  func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
    guard let response = response as? HTTPURLResponse, response.url == expectedURL,
      response.expectedContentLength <= maximumResponseBytes else { completionHandler(.cancel); return }
    self.response = response; completionHandler(.allow)
  }
  func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
    guard body.count + data.count <= maximumResponseBytes else { dataTask.cancel(); return }
    body.append(data)
  }
  func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
    lock.lock(); let continuation = continuation; self.continuation = nil; self.session = nil; let cancelled = cancelled; lock.unlock()
    session.finishTasksAndInvalidate()
    if cancelled { continuation?.resume(throwing: CancellationError()) }
    else if error != nil { continuation?.resume(throwing: ComputerFailure.offline) }
    else if let response { continuation?.resume(returning: (body, response)) }
    else { continuation?.resume(throwing: ComputerFailure.invalidResponse) }
  }
}

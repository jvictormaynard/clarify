import Foundation
import Security
import CryptoKit

// One ephemeral session per request and exact route. Its delegate cannot apply
// a LAN trust exception, cookies or a credential to another destination.
final class ComputerHTTPS: NSObject, URLSessionDataDelegate, @unchecked Sendable {
  private let route: ComputerRoute
  private let expectedURL: URL
  private let lock = NSLock()
  private var session: URLSession?
  private var continuation: CheckedContinuation<(Data, HTTPURLResponse), Error>?
  private var response: HTTPURLResponse?
  private var body = Data()
  private var cancelled = false
  private static let maxResponse = 128 * 1024

  init(route: ComputerRoute, url: URL) { self.route = route; expectedURL = url }
  static func matchesCertificate(_ der: Data, pin: String) -> Bool {
    let fingerprint = SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
    return fingerprint == pin.lowercased()
  }
  static func send(_ request: URLRequest, route: ComputerRoute) async throws -> (Data, HTTPURLResponse) {
    _ = try route.validated()
    guard let url = request.url, url.absoluteString.hasPrefix(route.url + "/v1/computer/") else { throw ComputerFailure.invalidResponse }
    let transport = ComputerHTTPS(route: route, url: url)
    return try await withTaskCancellationHandler(operation: {
      try await withCheckedThrowingContinuation { continuation in transport.start(request, continuation: continuation) }
    }, onCancel: { transport.cancel() })
  }
  private func start(_ request: URLRequest, continuation: CheckedContinuation<(Data, HTTPURLResponse), Error>) {
    lock.lock(); defer { lock.unlock() }
    guard !cancelled else { continuation.resume(throwing: CancellationError()); return }
    self.continuation = continuation
    let config = URLSessionConfiguration.ephemeral
    config.httpCookieStorage = nil; config.httpShouldSetCookies = false; config.urlCache = nil
    config.urlCredentialStorage = nil; config.requestCachePolicy = .reloadIgnoringLocalCacheData
    config.timeoutIntervalForResource = request.timeoutInterval + 5
    config.tlsMinimumSupportedProtocolVersion = .TLSv12
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
    guard space.authenticationMethod == NSURLAuthenticationMethodServerTrust,
      space.host == expectedURL.host, space.port == (expectedURL.port ?? 443), space.protocol == "https" else {
      completionHandler(.cancelAuthenticationChallenge, nil); return
    }
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
      response.expectedContentLength <= Self.maxResponse else { completionHandler(.cancel); return }
    self.response = response; completionHandler(.allow)
  }
  func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
    guard body.count + data.count <= Self.maxResponse else { dataTask.cancel(); return }
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

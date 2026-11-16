#if canImport(WebKit)
import Foundation
import WebKit

/// App-only data channels. Audio capture remains with AudioSession.
@MainActor final class ComputerWebRTCEngine: NSObject, ComputerWebRTCTransport, WKNavigationDelegate, WKScriptMessageHandlerWithReply, URLSessionTaskDelegate {
  let computerID: UUID
  private let binding: ComputerWebRTCBinding
  private let identity: TextAccountIdentity
  private var view: WKWebView?
  private var loaded: CheckedContinuation<Void, Error>?
  private var closed = false
  private var connectedAt: Date?
  // TURN credentials last 15 minutes. Renew before a new operation once this
  // connection is five minutes old, leaving room for capture and finalization.
  var canStartOperation: Bool { !closed && connectedAt.map { Date().timeIntervalSince($0) < 300 } == true }
  private let onClose: () -> Void
  private var tasks: [UUID: Task<Any, Error>] = [:]
  private var session: URLSession!
  private static var resources: Bundle {
    #if SWIFT_PACKAGE
    return Bundle.module
    #else
    let owner = Bundle(for: ComputerWebRTCEngine.self)
    if let url = owner.url(forResource: "ClarifyWebRTC", withExtension: "bundle"), let bundle = Bundle(url: url) { return bundle }
    return owner
    #endif
  }
  init(computerID: UUID, binding: ComputerWebRTCBinding, onClose: @escaping () -> Void = {}) throws {
    try binding.validate()
    self.computerID = computerID; self.binding = binding; self.onClose = onClose
    identity = CloudAccount.shared.captureTextIdentity()
    guard CloudAccount.shared.acceptsTextIdentity(identity), identity.credential != nil else { throw ComputerFailure.authentication }
    super.init()
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .nonPersistent()
    config.mediaTypesRequiringUserActionForPlayback = .all
    config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "signal")
    let view = WKWebView(frame: .zero, configuration: config)
    view.navigationDelegate = self; self.view = view
    let network = URLSessionConfiguration.ephemeral
    network.httpCookieStorage = nil; network.urlCache = nil; network.timeoutIntervalForRequest = 10
    session = URLSession(configuration: network, delegate: self, delegateQueue: .main)
  }
  func connect() async throws {
    guard let view, let url = Self.resources.url(forResource: "computer-webrtc", withExtension: "html", subdirectory: "ComputerWebRTC") ?? Self.resources.url(forResource: "computer-webrtc", withExtension: "html") else { throw ComputerFailure.offline }
    try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
      loaded = continuation; view.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
    }
    let args: [String: Any] = ["host": computerID.uuidString.lowercased(), "key": binding.public_key]
    _ = try await view.callAsyncJavaScript("await window.clarifyRTC.connect(host, key)", arguments: args, in: nil, contentWorld: .page)
    guard !closed, CloudAccount.shared.acceptsTextIdentity(identity) else { close(); throw ComputerFailure.authentication }
    connectedAt = Date()
  }
  private func invoke(_ value: [String: Any], timeout: Int) async throws -> Any? {
    guard !closed, let view else { throw ComputerFailure.offline }
    do {
      return try await view.callAsyncJavaScript("return await window.clarifyRTC.send(value, timeout)",
        arguments: ["value": value, "timeout": timeout], in: nil, contentWorld: .page)
    } catch {
      // End this uncertain connection. A later explicit preparation may connect
      // again, but this request is never replayed.
      close(); throw error
    }
  }
  func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
    guard !closed, view != nil, let url = request.url, url.path.hasPrefix("/v1/computer/"),
      !["/v1/computer/pair", "/v1/computer/remote"].contains(url.path),
      let token = request.value(forHTTPHeaderField: "Authorization"), token.hasPrefix("Bearer "),
      (request.httpBody?.count ?? 0) <= ComputerProtocolLimits.maximumRequestBytes,
      CloudAccount.shared.acceptsTextIdentity(identity) else { throw ComputerFailure.authentication }
    var value: [String: Any] = ["method": request.httpMethod ?? "GET", "path": url.path, "authorization": token]
    if let body = request.httpBody { value["body"] = try ComputerJSON.object(body, maximum: ComputerProtocolLimits.maximumRequestBytes) }
    // A transport error retires the connection; it never replays this request.
    let timeout = Int(max(1, min(120000, request.timeoutInterval * 1000)))
    let raw = try await invoke(value, timeout: timeout)
    guard !closed, let reply = raw as? [String: Any], let code = ComputerJSON.integer(reply["status"]),
      (200...599).contains(code), let body = reply["body"],
      let data = try? JSONSerialization.data(withJSONObject: body), data.count <= ComputerProtocolLimits.maximumResponseBytes,
      let response = HTTPURLResponse(url: url, statusCode: code, httpVersion: "HTTP/1.1", headerFields: [:]) else { throw ComputerFailure.invalidResponse }
    return (data, response)
  }
  func recognition(_ action: String, operationID: UUID, token: String, body: [String: Any]) async throws -> (Data, Int) {
    guard !closed, view != nil, CloudAccount.shared.acceptsTextIdentity(identity),
      ComputerCredential.validToken(token), ["start", "feed", "partial", "finish", "cancel"].contains(action) else { throw ComputerFailure.authentication }
    let value: [String: Any] = ["recognition": action, "operation_id": operationID.uuidString,
      "authorization": "Bearer " + token, "body": body]
    guard try JSONSerialization.data(withJSONObject: value).count <= (action == "feed" ? 32768 : 8192) else { throw ComputerFailure.invalidResponse }
    let raw = try await invoke(value, timeout: action == "finish" ? 100000 : 15000)
    guard !closed, let reply = raw as? [String: Any], let code = ComputerJSON.integer(reply["status"]),
      (200...599).contains(code), let body = reply["body"] else { throw ComputerFailure.invalidResponse }
    let data = try JSONSerialization.data(withJSONObject: body)
    _ = try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumResponseBytes)
    return (data, code)
  }
  func close() {
    guard !closed else { return }; closed = true
    onClose()
    loaded?.resume(throwing: ComputerFailure.offline); loaded = nil
    for task in tasks.values { task.cancel() }; tasks.removeAll()
    session?.invalidateAndCancel()
    view?.evaluateJavaScript("window.clarifyRTC?.close()", completionHandler: nil)
    view?.configuration.userContentController.removeScriptMessageHandler(forName: "signal")
    view?.stopLoading(); view?.navigationDelegate = nil; view = nil
  }
  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded?.resume(); loaded = nil }
  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { close() }
  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { close() }
  func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { close() }
  func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
    let url = navigationAction.request.url
    decisionHandler(navigationAction.targetFrame?.isMainFrame == true && url?.isFileURL == true && url?.lastPathComponent == "computer-webrtc.html" ? .allow : .cancel)
  }
  nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
  func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage, replyHandler: @escaping (Any?, String?) -> Void) {
    guard !closed, message.frameInfo.isMainFrame, message.webView === view,
      let value = message.body as? [String: Any] else { replyHandler(nil, "unauthorized"); return }
    if value.count == 1, value["event"] as? String == "closed" {
      replyHandler(true, nil); close(); return
    }
    guard tasks.count < 8, let action = value["action"] as? String, ["create", "turn", "offer", "poll", "close"].contains(action),
      CloudAccount.shared.acceptsTextIdentity(identity), let token = identity.credential else { replyHandler(nil, "unauthorized"); return }
    let id = UUID()
    let task = Task<Any, Error> {
      defer { tasks.removeValue(forKey: id) }
      do {
        var body = value; body["host"] = computerID.uuidString.lowercased()
        let data = try JSONSerialization.data(withJSONObject: body)
        guard data.count <= 131072 else { throw ComputerFailure.invalidResponse }
        var request = URLRequest(url: URL(string: binding.signal_url)!)
        request.httpMethod = "POST"; request.httpBody = data
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (stream, response) = try await session.bytes(for: request)
        var bytes = Data()
        for try await byte in stream {
          guard bytes.count < 131072 else { throw ComputerFailure.invalidResponse }
          bytes.append(byte)
        }
        guard !closed, CloudAccount.shared.acceptsTextIdentity(identity), (response as? HTTPURLResponse)?.statusCode == 200 else { throw ComputerFailure.authentication }
        let object = try ComputerJSON.object(bytes, maximum: 131072)
        replyHandler(object, nil); return object
      } catch { replyHandler(nil, "signaling_unavailable"); throw error }
    }
    tasks[id] = task
  }
}
#endif

import Foundation

struct ActivationRequest: Codable {
  let token: String
  let createdAt: TimeInterval
  let sourceBundleID: String?
  init(sourceBundleID: String?, now: TimeInterval = Date().timeIntervalSince1970) {
    token = UUID().uuidString; createdAt = now; self.sourceBundleID = sourceBundleID
  }
}

extension SharedState {
  // Origin information stays on this device and is discarded after one use.
  // The URL carries only a nonce, never a caller-selected launch destination.
  func consumeActivation(_ token: String, now: TimeInterval = Date().timeIntervalSince1970) -> ActivationRequest? {
    guard UUID(uuidString: token) != nil, let request = read("activation.json", as: ActivationRequest.self),
          request.token == token else { return nil }
    do { try FileManager.default.removeItem(at: root.appendingPathComponent("activation.json")) }
    catch { return nil }
    guard now >= request.createdAt, now - request.createdAt <= 120 else { return nil }
    return request
  }
}

import Foundation

/// The containing app injects an authenticated WebRTC engine. The keyboard does
/// not receive this engine, its signaling session, or computer credentials.
@MainActor protocol ComputerWebRTCTransport: AnyObject {
  var computerID: UUID { get }
  /// Status preparation can replace an aging connection before new work.
  var canStartOperation: Bool { get }
  /// Verify the host's signed SDP against the key saved at explicit pairing.
  /// Send the original URLRequest over the ordered clarify-computer-v1 channel.
  /// Never reconnect or replay a request after an uncertain response.
  func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
  func recognition(_ action: String, operationID: UUID, token: String, body: [String: Any]) async throws -> (Data, Int)
  func close()
}

@MainActor extension ComputerWebRTCTransport {
  var canStartOperation: Bool { true }
  func recognition(_ action: String, operationID: UUID, token: String, body: [String: Any]) async throws -> (Data, Int) { throw ComputerFailure.notReady }
}

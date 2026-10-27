import Foundation

final class ComputerConnection {
  static let shared = ComputerConnection()
  typealias Transport = (URLRequest, ComputerRoute) async throws -> (Data, HTTPURLResponse)
  private let transport: Transport
  private let save: (ComputerCredential?) throws -> Void
  private let newOperationID: () throws -> UUID
  private(set) var credential: ComputerCredential?
  private(set) var generation: UInt64 = 0
  private(set) var busy = false
  private(set) var ready = false
  private(set) var actionReadiness = ComputerActionReadiness.unavailable
  private(set) var status = "unpaired"
  private var activeRoute: ComputerRoute?
  private var invalidated: (() -> Void)?
  private var operations: [String: (credential: ComputerCredential, route: ComputerRoute, wireID: UUID)] = [:]
  // Keep local action tombstones for this connection's lifetime. A delayed
  // command or uncertain response cannot mint a new remote operation.
  private var retiredOperations = Set<String>()

  init(read: () -> ComputerCredential? = ComputerKeychain.read,
    save: @escaping (ComputerCredential?) throws -> Void = ComputerKeychain.save,
    transport: @escaping Transport = ComputerHTTPS.send,
    newOperationID: @escaping () throws -> UUID = { try ComputerOperationID.make() }) {
    self.save = save; self.transport = transport; self.newOperationID = newOperationID
    credential = read()
    if let credential, (try? credential.validate()) == nil { self.credential = nil }
    if self.credential != nil { status = "offline" }
  }
  var configured: Bool { credential != nil }
  var scope: String? { credential?.scope }
  func setInvalidationHandler(_ handler: @escaping () -> Void) { invalidated = handler }
  func snapshot() -> [String: Any] {
    ["paired": configured, "computerID": credential?.computerID.uuidString ?? "",
      "computerName": credential?.computerName ?? "", "status": status, "ready": ready, "busy": busy,
      "actionReadiness": actionReadiness.snapshot]
  }
  func isReady(for action: String) -> Bool { actionReadiness.allows(action) }
  func accepts(_ owner: UInt64) -> Bool { generation == owner && configured }
  @MainActor private func send(_ method: String, path: String, route: ComputerRoute, token: String? = nil,
    json: [String: Any]? = nil, timeout: TimeInterval = 15) async throws -> (Data, Int) {
    _ = try route.validated()
    guard path.hasPrefix("/v1/computer/"), let url = URL(string: route.url + path) else { throw ComputerFailure.invalidResponse }
    var request = URLRequest(url: url); request.httpMethod = method; request.timeoutInterval = timeout
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    if let token {
      guard ComputerCredential.validToken(token) else { throw ComputerFailure.authentication }
      request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
    }
    if let json {
      request.httpBody = try JSONSerialization.data(withJSONObject: json)
      request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    try Task.checkCancellation()
    let data: Data, response: HTTPURLResponse
    do { (data, response) = try await transport(request, route) }
    catch is CancellationError { throw CancellationError() }
    catch { throw ComputerFailure.offline }
    try Task.checkCancellation()
    guard response.url == url, data.count <= ComputerProtocolLimits.maximumResponseBytes, !(300...399).contains(response.statusCode) else { throw ComputerFailure.invalidResponse }
    return (data, response.statusCode)
  }
  @MainActor func pair(_ qr: String, deviceName: String, now: Date = Date()) async throws {
    guard !busy else { throw ComputerFailure.busy }
    let invitation = try ComputerInvitation.parse(qr, now: now)
    guard ComputerInvitation.validName(deviceName) else { throw ComputerFailure.invalidResponse }
    busy = true; let owner = generation; let previous = credential
    defer { busy = false }
    for route in invitation.routes {
      do {
        let (data, code) = try await send("POST", path: "/v1/computer/pair", route: route,
          json: ["pairing_token": invitation.pairingToken, "device_name": deviceName])
        guard generation == owner else { throw CancellationError() }
        if code == 429, let reply = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          reply["error"] as? String == "device_limit" { throw ComputerFailure.deviceLimit }
        guard code == 200 || code == 201 else { throw [401, 403, 410].contains(code) ? ComputerFailure.expiredQR : ComputerFailure.invalidResponse }
        struct Reply: Decodable {
          let schema_version: Int; let computer_id: UUID; let computer_name: String; let device_id: UUID; let session_token: String
        }
        guard let reply = try? JSONDecoder().decode(Reply.self, from: data), reply.schema_version == 1,
          reply.computer_id == invitation.computerID else { throw ComputerFailure.invalidResponse }
        let credential = ComputerCredential(computerID: reply.computer_id, computerName: reply.computer_name,
          deviceID: reply.device_id, sessionToken: reply.session_token, routes: invitation.routes)
        try credential.validate(); try save(credential)
        self.credential = credential; generation &+= 1; activeRoute = route; ready = false; status = "offline"
        actionReadiness = .unavailable
        if let previous, let previousRoute = previous.routes.first {
          Task { @MainActor in _ = try? await self.send("DELETE", path: "/v1/computer/session", route: previousRoute, token: previous.sessionToken, timeout: 2) }
        }
        // Readiness is separate from successful pairing. A configured host can
        // be offline immediately after it issued the device credential.
        return
      } catch ComputerFailure.offline { continue }
    }
    throw ComputerFailure.offline
  }
  @MainActor func refresh() async throws {
    guard let credential else { throw ComputerFailure.authentication }
    guard !busy else { throw ComputerFailure.busy }
    let owner = generation; busy = true; ready = false; activeRoute = nil; status = "offline"
    actionReadiness = .unavailable
    defer { busy = false }
    for route in credential.routes {
      do {
        let (data, code) = try await send("GET", path: "/v1/computer/status", route: route, token: credential.sessionToken, timeout: 5)
        guard accepts(owner) else { throw CancellationError() }
        if [401, 403].contains(code) { try invalidate(); throw ComputerFailure.authentication }
        guard code == 200 else { throw ComputerFailure.invalidResponse }
        struct Reply: Decodable {
          let schema_version: Int; let computer_id: UUID; let computer_name: String; let ready: Bool
          let action_readiness: ComputerActionReadiness?
        }
        guard let reply = try? JSONDecoder().decode(Reply.self, from: data), reply.schema_version == 1,
          reply.computer_id == credential.computerID, ComputerInvitation.validName(reply.computer_name),
          reply.action_readiness == nil || reply.action_readiness?.dictate == reply.ready else { throw ComputerFailure.invalidResponse }
        // Older hosts advertise only dictation. Text needs an explicit capability.
        actionReadiness = reply.action_readiness ?? ComputerActionReadiness(dictate: reply.ready, rewrite: false, translate: false)
        activeRoute = route; ready = reply.ready; status = actionReadiness.available ? "ready" : "not_ready"; return
      } catch ComputerFailure.offline { continue }
    }
    guard accepts(owner) else { throw CancellationError() }
    ready = false; status = "offline"; throw ComputerFailure.offline
  }
  private func invalidate() throws {
    // Clear in-memory authority even if Keychain deletion fails. The mode stays
    // computer, so expiry never enables hosted processing.
    credential = nil; activeRoute = nil; ready = false; status = "revoked"; generation &+= 1
    actionReadiness = .unavailable
    invalidated?()
    try save(nil)
  }
  @MainActor func disconnect() {
    let previous = credential, route = activeRoute ?? credential?.routes.first
    suspend()
    try? invalidate()
    if let previous, let route {
      Task { @MainActor in _ = try? await self.send("DELETE", path: "/v1/computer/session", route: route, token: previous.sessionToken, timeout: 2) }
    }
  }
  @MainActor func suspend() {
    for id in Array(operations.keys) { cancelOperation(id) }
    generation &+= 1; ready = false; activeRoute = nil
    actionReadiness = .unavailable
    if configured { status = "offline" }
  }
  @MainActor func cancelOperation(_ id: String) {
    guard let localID = UUID(uuidString: id) else { return }
    let key = localID.uuidString
    retiredOperations.insert(key)
    guard let operation = operations.removeValue(forKey: key) else { return }
    Task { @MainActor in _ = try? await self.send("DELETE", path: "/v1/computer/operations/" + operation.wireID.uuidString, route: operation.route, token: operation.credential.sessionToken, timeout: 2) }
  }
  @MainActor func process(_ operationID: String, action: String? = nil, text: String? = nil, wav: Data? = nil,
    language: String = ClarifyLocale.language) async throws -> ComputerResult {
    try Task.checkCancellation()
    guard let localID = UUID(uuidString: operationID) else { throw ComputerFailure.notReady }
    let key = localID.uuidString
    guard !retiredOperations.contains(key) else { throw CancellationError() }
    guard let credential, let route = activeRoute, isReady(for: action ?? "dictate") else { throw ComputerFailure.notReady }
    guard !language.isEmpty, language.utf8.count <= 32,
      language.utf8.allSatisfy({ (65...90).contains($0) || (97...122).contains($0) || $0 == 45 }) else { throw ComputerFailure.invalidResponse }
    guard operations[key] == nil else { throw ComputerFailure.busy }
    let owner = generation
    var json: [String: Any] = ["language": language]
    if let action, let text {
      guard ["rewrite", "translate"].contains(action), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        text.utf8.count <= 32_768 else { throw ComputerFailure.invalidResponse }
      json["action"] = action; json["text"] = text
    } else if let wav { try ComputerWAV.validate(wav); json["audio_wav"] = wav.base64EncodedString() }
    else { throw ComputerFailure.invalidAudio }
    let wireID = try newOperationID()
    json["operation_id"] = wireID.uuidString
    operations[key] = (credential, route, wireID)
    defer { operations.removeValue(forKey: key); retiredOperations.insert(key) }
    do {
      let (data, code) = try await send("POST", path: action == nil ? "/v1/computer/dictations" : "/v1/computer/text", route: route,
        token: credential.sessionToken, json: json, timeout: 100)
      guard accepts(owner), operations[key]?.wireID == wireID else { throw CancellationError() }
      if [401, 403].contains(code) { try invalidate(); throw ComputerFailure.authentication }
      guard code == 200 else {
        // Only stable local messages are exposed. Provider error bodies remain
        // outside snapshots, logs and the keyboard extension.
        let raw = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let messages = ["invalid_audio": "Grave um áudio válido de até 5 minutos.",
          "not_ready": "Configure o processamento no Clarify do computador.",
          "busy": "Já existe um processamento em andamento.", "operation_in_progress": "Já existe um processamento em andamento.",
          "processing_failed": "Não foi possível concluir o processamento. Tente novamente.",
          "operation_cancelled": "Esta solicitação foi cancelada.",
          "operation_conflict": "Esta solicitação não pode ser repetida. Inicie uma nova ação.",
          "operation_expired": "Esta solicitação não pode ser repetida. Inicie uma nova ação.",
          "operation_in_future": "Verifique a data e a hora do iPhone e do computador. Depois, inicie uma nova ação.",
          "operation_limit": "O computador atingiu o limite temporário de solicitações. Aguarde e inicie uma nova ação.",
          "operation_history_full": "Limite atingido. Revogue no computador o acesso de um celular ou deste iPhone. Leia outro QR.",
          "result_unavailable": "Esta solicitação não pode ser repetida. Inicie uma nova ação."]
        let message = (raw?["error"] as? String).flatMap { messages[$0] } ?? (code == 429 ? "Muitas solicitações. Aguarde um momento." : "Não foi possível concluir o processamento. Tente novamente.")
        throw ClarifyError(message, code: "computer_processing_failed", phase: action == nil ? "transcribing" : "rewriting", operationID: operationID, status: code)
      }
      let result = try ComputerResult.decode(data, operationID: wireID.uuidString)
      return ComputerResult(operationID: localID, transcript: result.transcript, text: result.text,
        rewritten: result.rewritten, successful: result.successful)
    } catch {
      if Task.isCancelled { cancelOperation(operationID); throw CancellationError() }
      guard accepts(owner), operations[key]?.wireID == wireID else { throw CancellationError() }
      if error as? ComputerFailure == .offline { ready = false; actionReadiness = .unavailable; status = "offline" }
      throw error
    }
  }
}

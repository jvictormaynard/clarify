import Foundation

final class ComputerConnection {
  static let shared = ComputerConnection()
  typealias Transport = (URLRequest, ComputerRoute) async throws -> (Data, HTTPURLResponse)
  typealias GrantRequest = @MainActor (ComputerRemoteRegistration, UUID) async throws -> ComputerConnectGrant
  private var webRTC: ComputerWebRTCTransport?
  private var webRTCIdentity = UUID()
  private let transport: Transport
  private let requestGrant: GrantRequest
  private let cloudflareConfiguration: () throws -> ComputerCloudflareConfiguration?
  private let clock: () -> Date
  private let save: (ComputerCredential?) throws -> Void
  private let newOperationID: () throws -> UUID
  private(set) var credential: ComputerCredential?
  private(set) var generation: UInt64 = 0
  private(set) var busy = false
  private(set) var ready = false
  private(set) var actionReadiness = ComputerActionReadiness.unavailable
  private(set) var textActions = TextActionCatalog.unavailable
  private(set) var outputPreferencesSupported = false
  private(set) var processingCapabilities = ProcessingCapabilities.unavailable
  private(set) var status = "unpaired"
  private(set) var remoteStatus = "unavailable"
  private var liveAdvertised = false
  @MainActor var liveRecognitionAvailable: Bool { liveAdvertised && ready && webRTC?.canStartOperation == true }
  private var activeRoute: ComputerRoute?
  private var invalidated: (() -> Void)?
  private var operations: [String: (credential: ComputerCredential, route: ComputerRoute, wireID: UUID, live: ComputerLiveCapture?)] = [:]
  // Keep local action tombstones for this connection's lifetime. A delayed
  // command or uncertain response cannot mint a new remote operation.
  private var retiredOperations = Set<String>()

  init(read: () -> ComputerCredential? = ComputerKeychain.read,
    save: @escaping (ComputerCredential?) throws -> Void = ComputerKeychain.save,
    transport: @escaping Transport = ComputerSealedTransport.send,
    newOperationID: @escaping () throws -> UUID = { try ComputerOperationID.make() },
    cloudflareConfiguration: @escaping () throws -> ComputerCloudflareConfiguration? = ComputerCloudflareConfiguration.current,
    requestGrant: @escaping GrantRequest = { try await CloudAccount.shared.requestComputerGrant($0, computerID: $1) },
    clock: @escaping () -> Date = Date.init) {
    self.save = save; self.transport = transport; self.newOperationID = newOperationID
    self.cloudflareConfiguration = cloudflareConfiguration; self.requestGrant = requestGrant; self.clock = clock
    credential = read()
    if let credential, (try? credential.validate()) == nil { self.credential = nil }
    if self.credential != nil { status = "offline" }
    if self.credential?.routes.contains(where: { $0.hpkePublicKey != nil }) == true { remoteStatus = "registered" }
  }
  @MainActor func configureWebRTC(_ connection: ComputerWebRTCTransport?) throws {
    guard !busy && operations.isEmpty else { throw ComputerFailure.busy }
    guard connection == nil || connection?.computerID == credential?.computerID else {
      throw ComputerFailure.authentication
    }
    webRTCIdentity = UUID()
    webRTC?.close(); webRTC = connection
    remoteStatus = connection == nil ? "unavailable" : "connected"
  }
  var configured: Bool { credential != nil }
  var scope: String? { credential?.scope }
  func setInvalidationHandler(_ handler: @escaping () -> Void) { invalidated = handler }
  func snapshot() -> [String: Any] {
    var result: [String: Any] = ["paired": configured, "computerID": credential?.computerID.uuidString ?? "",
      "computerName": credential?.computerName ?? "", "status": status, "ready": ready, "busy": busy,
      "actionReadiness": actionReadiness.snapshot, "remoteStatus": remoteStatus,
      "remoteAvailable": webRTC != nil || credential?.routes.contains(where: { $0.hpkePublicKey != nil }) == true,
      "outputPreferencesSupported": outputPreferencesSupported, "processingContract": processingCapabilities.value]
    result.merge(textActions.snapshot) { _, new in new }; return result
  }
  func isReady(for action: String) -> Bool { actionReadiness.allows(action) }
  func accepts(_ owner: UInt64) -> Bool { generation == owner && configured }
  @MainActor private func send(_ method: String, path: String, route: ComputerRoute, token: String? = nil,
    json: [String: Any]? = nil, timeout: TimeInterval = 15, owner: UInt64? = nil, via retainedPeer: ComputerWebRTCTransport? = nil) async throws -> (Data, Int) {
    _ = try route.validated(relayHost: ComputerRelayConfiguration.host(), cloudflare: cloudflareConfiguration())
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
    do {
      if let peer = retainedPeer ?? (token == credential?.sessionToken ? webRTC : nil), !["/v1/computer/pair", "/v1/computer/remote"].contains(path) { (data, response) = try await peer.send(request) }
      else { (data, response) = try await transport(request, route) }
    }
    catch is CancellationError { throw CancellationError() }
    catch {
      try Task.checkCancellation()
      if let owner, generation != owner { throw CancellationError() }
      throw ComputerFailure.offline
    }
    try Task.checkCancellation()
    if let owner, generation != owner { throw CancellationError() }
    guard response.url == url, data.count <= ComputerProtocolLimits.maximumResponseBytes, !(300...399).contains(response.statusCode) else { throw ComputerFailure.invalidResponse }
    return (data, response.statusCode)
  }
  @MainActor func pair(_ qr: String, deviceName: String, now: Date = Date()) async throws {
    guard !busy else { throw ComputerFailure.busy }
    let invitation = try ComputerInvitation.parse(qr, now: now, cloudflare: cloudflareConfiguration())
    guard ComputerInvitation.validName(deviceName) else { throw ComputerFailure.invalidResponse }
    busy = true; let owner = generation; let previous = credential
    defer { busy = false }
    var selected: ComputerRoute?
    for route in invitation.routes {
      try Task.checkCancellation()
      guard generation == owner else { throw CancellationError() }
      do {
        // Only connectivity discovery may try another QR-trusted route. No
        // bootstrap token is sent until a route has completed its TLS check.
        let (_, code) = try await send("GET", path: "/v1/computer/status", route: route, timeout: route.statusTimeout, owner: owner)
        guard generation == owner else { throw CancellationError() }
        guard [200, 401, 403].contains(code) else { throw ComputerFailure.invalidResponse }
        selected = route; break
      } catch ComputerFailure.offline {
        try Task.checkCancellation()
        guard generation == owner else { throw CancellationError() }
      }
    }
    guard let route = selected else { throw ComputerFailure.offline }
    let (data, code) = try await send("POST", path: "/v1/computer/pair", route: route,
      json: ["pairing_token": invitation.pairingToken, "device_name": deviceName], owner: owner)
    guard generation == owner else { throw CancellationError() }
    if code == 429, let reply = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
      reply["error"] as? String == "device_limit" { throw ComputerFailure.deviceLimit }
    guard code == 200 || code == 201 else { throw [401, 403, 410].contains(code) ? ComputerFailure.expiredQR : ComputerFailure.invalidResponse }
    struct Reply: Decodable {
      let schema_version: Int; let computer_id: UUID; let computer_name: String; let device_id: UUID; let session_token: String
    }
    let raw = try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumResponseBytes)
    guard let reply = try? JSONDecoder().decode(Reply.self, from: data), ComputerJSON.integer(raw["schema_version"]) == 1,
      reply.computer_id == invitation.computerID else { throw ComputerFailure.invalidResponse }
    var credential = ComputerCredential(computerID: reply.computer_id, computerName: reply.computer_name,
      deviceID: reply.device_id, sessionToken: reply.session_token, routes: invitation.routes)
    credential.webrtc = invitation.webrtc
    try credential.validate(); try save(credential)
    self.credential = credential; generation &+= 1; activeRoute = route; ready = false; status = "offline"
    actionReadiness = .unavailable
    textActions = .unavailable; outputPreferencesSupported = false; processingCapabilities = .unavailable
    remoteStatus = credential.routes.contains(where: { $0.hpkePublicKey != nil }) ? "registered" : "unavailable"
    if let previous, let previousRoute = previous.routes.first {
      Task { @MainActor in _ = try? await self.send("DELETE", path: "/v1/computer/session", route: previousRoute, token: previous.sessionToken, timeout: 2) }
    }
    // Readiness is separate from successful pairing. A configured host can be
    // offline immediately after it issued the device credential.
    if let registration = raw["remote_registration"] {
      try await registerRemote(registration, paired: credential, route: route, owner: generation)
    }
  }
  @MainActor private func registerRemote(_ raw: Any, paired: ComputerCredential, route: ComputerRoute,
    owner: UInt64) async throws {
    var requestingGrant = false
    func checkOwner() throws {
      try Task.checkCancellation()
      guard accepts(owner), credential == paired else { throw CancellationError() }
    }
    do {
      try checkOwner()
      guard let configuration = try cloudflareConfiguration() else { remoteStatus = "disabled"; return }
      guard #available(iOS 17.0, macOS 14.0, *) else { remoteStatus = "unsupported"; return }
      let registration = try ComputerRemoteRegistration.parse(raw, route: route, configuration: configuration)
      remoteStatus = "registering"
      requestingGrant = true
      let grant = try await requestGrant(registration, paired.computerID)
      requestingGrant = false
      try checkOwner()
      guard grant.accountIsCurrent() else { throw CancellationError() }
      guard grant.controlURL == configuration.controlURL,
        ComputerInvitation.base64URL(grant.grant, bytes: 32) != nil,
        grant.hostname == (try configuration.hostname(publicKey: registration.hpkePublicKey)),
        Double(grant.expiresAt) > clock().timeIntervalSince1970,
        Double(grant.expiresAt) - clock().timeIntervalSince1970 <= 300 else { throw ComputerFailure.invalidResponse }
      // This is the paired, pinned LAN route. Neither an account session nor
      // a provider key is sent to the desktop. Never repeat this POST.
      let (data, code) = try await send("POST", path: "/v1/computer/remote", route: route, token: paired.sessionToken,
        json: ["control_url": configuration.controlURL, "grant": grant.grant], timeout: 60, owner: owner)
      try checkOwner()
      guard grant.accountIsCurrent(), try cloudflareConfiguration() == configuration else { throw CancellationError() }
      let reply = try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumResponseBytes, keys: ["schema_version", "route"])
      guard code == 200, ComputerJSON.integer(reply["schema_version"]) == 1,
        let routeObject = reply["route"] else { throw ComputerFailure.invalidResponse }
      let remote = try ComputerRoute.parse(routeObject, cloudflare: configuration)
      guard remote.hpkePublicKey == registration.hpkePublicKey,
        URLComponents(string: remote.url)?.host == grant.hostname else { throw ComputerFailure.invalidResponse }
      let routes = Array(paired.routes.filter { $0.isLAN && $0.url != remote.url }.prefix(3)) + [remote]
      var updated = ComputerCredential(computerID: paired.computerID, computerName: paired.computerName,
        deviceID: paired.deviceID, sessionToken: paired.sessionToken, routes: routes)
      updated.webrtc = paired.webrtc
      try checkOwner(); try save(updated)
      credential = updated; remoteStatus = "registered"
    } catch {
      // LAN authority is already saved. A remote failure cannot trigger a
      // second pairing, change the destination or revoke this LAN session.
      guard accepts(owner), credential == paired else { throw CancellationError() }
      if Task.isCancelled || error is CancellationError {
        remoteStatus = "cancelled"; throw CancellationError()
      }
      remoteStatus = requestingGrant && (error as? ComputerFailure == .authentication) ? "account_required" : "failed"
    }
  }
  @MainActor private func acceptRemoteRoute(_ raw: Any, paired: ComputerCredential, owner: UInt64) throws {
    guard accepts(owner), credential == paired, let configuration = try cloudflareConfiguration() else { throw CancellationError() }
    let remote = try ComputerRoute.parse(raw, cloudflare: configuration)
    guard remote.hpkePublicKey != nil,
      paired.routes.compactMap(\.hpkePublicKey).allSatisfy({ $0 == remote.hpkePublicKey }) else { throw ComputerFailure.invalidResponse }
    var updated = ComputerCredential(computerID: paired.computerID, computerName: paired.computerName,
      deviceID: paired.deviceID, sessionToken: paired.sessionToken,
      routes: Array(paired.routes.filter(\.isLAN).prefix(3)) + [remote])
    updated.webrtc = paired.webrtc
    try save(updated); credential = updated; remoteStatus = "registered"
  }
  @MainActor func resumeRemoteRegistration() async throws {
    guard ["account_required", "authorization_required"].contains(remoteStatus) else { return }
    try await refresh(registerRemote: true)
  }
  @MainActor func refresh(registerRemote: Bool = false) async throws {
    guard let credential else { throw ComputerFailure.authentication }
    guard !busy else { throw ComputerFailure.busy }
    let owner = generation; busy = true; ready = false; activeRoute = nil; status = "offline"
    actionReadiness = .unavailable
    textActions = .loading; outputPreferencesSupported = false; processingCapabilities = .unavailable
    defer { busy = false }
    var refreshed = false
    defer {
      if !refreshed { textActions = .unavailable; outputPreferencesSupported = false; processingCapabilities = .unavailable; actionReadiness = .unavailable; ready = false; activeRoute = nil }
    }
    if let current = webRTC, !current.canStartOperation {
      webRTCIdentity = UUID(); webRTC = nil; current.close()
    }
    #if canImport(WebKit)
    if webRTC == nil, let binding = credential.webrtc, CloudAccount.shared.configured {
      let connectionID = UUID(); webRTCIdentity = connectionID
      let engine = try ComputerWebRTCEngine(computerID: credential.computerID, binding: binding) { [weak self] in
        guard let self, self.generation == owner, self.webRTCIdentity == connectionID else { return }
        for operation in self.operations.values { operation.live?.cancel() }
        self.webRTC = nil; self.remoteStatus = "unavailable"; self.ready = false
        self.actionReadiness = .unavailable
      }
      do { try await engine.connect(); guard accepts(owner) else { engine.close(); throw CancellationError() }; webRTC = engine; remoteStatus = "connected" }
      catch { engine.close(); remoteStatus = "failed" }
    }
    #endif
    for route in credential.routes {
      try Task.checkCancellation()
      guard accepts(owner) else { throw CancellationError() }
      do {
        let (data, code) = try await send("GET", path: "/v1/computer/status", route: route, token: credential.sessionToken, timeout: route.statusTimeout, owner: owner)
        guard accepts(owner) else { throw CancellationError() }
        if [401, 403].contains(code) { try invalidate(); throw ComputerFailure.authentication }
        guard code == 200 else { throw ComputerFailure.invalidResponse }
        struct Reply: Decodable {
          let schema_version: Int; let computer_id: UUID; let computer_name: String; let ready: Bool
          let action_readiness: ComputerActionReadiness?
        }
        let raw = try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumResponseBytes)
        let catalog = try TextActionCatalog.computer(raw["text_actions"])
        if raw["output_preferences_supported"] != nil, ComputerJSON.boolean(raw["output_preferences_supported"]) == nil { throw ComputerFailure.invalidResponse }
        guard let reply = try? JSONDecoder().decode(Reply.self, from: data), reply.schema_version == 1,
          reply.computer_id == credential.computerID, ComputerInvitation.validName(reply.computer_name),
          reply.action_readiness == nil || reply.action_readiness?.dictate == reply.ready else { throw ComputerFailure.invalidResponse }
        // Older hosts advertise only dictation. Text needs an explicit capability.
        actionReadiness = reply.action_readiness ?? ComputerActionReadiness(dictate: reply.ready, rewrite: false, translate: false)
        liveAdvertised = ComputerJSON.boolean(raw["live_recognition"]) == true && webRTC != nil
        processingCapabilities = try ProcessingCapabilities(raw["processing_contract"])
        textActions = catalog; outputPreferencesSupported = ComputerJSON.boolean(raw["output_preferences_supported"]) == true
        activeRoute = route; ready = reply.ready; status = (actionReadiness.available || catalog.actions.contains { $0.enabled && $0.ready }) ? "ready" : "not_ready"
        if route.isLAN {
          if let remote = raw["remote_route"], !credential.routes.contains(where: { $0.hpkePublicKey != nil }) {
            // A lost POST reply is recovered by an authenticated read. Never
            // repeat its one-use claim or another processing request.
            try acceptRemoteRoute(remote, paired: credential, owner: owner)
          } else if let registration = raw["remote_registration"], registerRemote {
            try await self.registerRemote(registration, paired: credential, route: route, owner: owner)
          } else if raw["remote_registration"] != nil, remoteStatus == "unavailable" {
            remoteStatus = "authorization_required"
          }
        }
        refreshed = true; return
      } catch ComputerFailure.offline {
        try Task.checkCancellation()
        guard accepts(owner) else { throw CancellationError() }
      }
    }
    guard accepts(owner) else { throw CancellationError() }
    ready = false; status = "offline"; throw ComputerFailure.offline
  }
  @MainActor private func invalidate() throws {
    // Clear in-memory authority even if Keychain deletion fails. The mode stays
    // computer, so expiry never enables hosted processing.
    for operation in operations.values { operation.live?.cancel() }
    webRTC?.close(); webRTC = nil
    if credential?.webrtc != nil { remoteStatus = "unavailable" }
    credential = nil; activeRoute = nil; ready = false; status = "revoked"; generation &+= 1
    remoteStatus = "unavailable"
    actionReadiness = .unavailable
    textActions = .unavailable; outputPreferencesSupported = false; processingCapabilities = .unavailable
    invalidated?()
    try save(nil)
  }
  @MainActor func disconnect() { retireConnection(revoke: true) }
  @MainActor func suspend() { retireConnection(revoke: false) }
  @MainActor private func retireConnection(revoke: Bool) {
    // Local authority ends now. Keep only this old transport alive long enough
    // to cancel/revoke; a new pairing never supplies its credential or route.
    let peer = webRTC, previous = credential, route = activeRoute ?? credential?.routes.first
    webRTCIdentity = UUID(); webRTC = nil
    let pending = Array(operations.values)
    for operation in pending { operation.live?.cancel() }
    retiredOperations.formUnion(operations.keys); operations.removeAll()
    generation &+= 1; ready = false; activeRoute = nil
    if credential?.webrtc != nil { remoteStatus = "unavailable" }
    if remoteStatus == "registering" { remoteStatus = "cancelled" }
    actionReadiness = .unavailable
    textActions = .unavailable; outputPreferencesSupported = false; processingCapabilities = .unavailable
    if configured { status = "offline" }
    if revoke { try? invalidate() }
    Task { @MainActor in
      defer { peer?.close() }
      if revoke, let previous, let route {
        _ = try? await self.send("DELETE", path: "/v1/computer/session", route: route,
          token: previous.sessionToken, timeout: 2, via: peer)
      } else {
        await withTaskGroup(of: Void.self) { group in
          for operation in pending.prefix(8) {
            group.addTask { @MainActor in
              _ = try? await self.send("DELETE", path: "/v1/computer/operations/" + operation.wireID.uuidString,
                route: operation.route, token: operation.credential.sessionToken, timeout: 2, via: peer)
            }
          }
        }
      }
    }
  }
  @MainActor func cancelOperation(_ id: String) {
    guard let localID = UUID(uuidString: id) else { return }
    let key = localID.uuidString
    retiredOperations.insert(key)
    guard let operation = operations.removeValue(forKey: key) else { return }
    operation.live?.cancel()
    let peer = webRTC
    Task { @MainActor in _ = try? await self.send("DELETE", path: "/v1/computer/operations/" + operation.wireID.uuidString,
      route: operation.route, token: operation.credential.sessionToken, timeout: 2, via: peer) }
  }
  // Claim before capture. The existing registry owns cancellation and retirement.
  @MainActor func prepareLive(_ operationID: String, preferences: OutputPreferences,
    policy: DictationPolicy, partial: @escaping (String) -> Void) throws -> ComputerLiveCapture? {
    guard liveRecognitionAvailable else { return nil }
    guard let localID = UUID(uuidString: operationID), let credential, let route = activeRoute,
      let peer = webRTC, !busy else { throw ComputerFailure.notReady }
    let key = localID.uuidString
    guard !retiredOperations.contains(key) else { throw CancellationError() }
    guard operations[key] == nil else { throw ComputerFailure.busy }
    let frozen = policy.frozenPreferences(preferences, capabilities: processingCapabilities, catalog: textActions, computer: true)
    try processingCapabilities.validate(frozen)
    var metadata: [String: Any] = ["language": "auto"]
    metadata.merge(try frozen.requestFields(supported: outputPreferencesSupported, dictation: true)) { _, new in new }
    metadata.merge(try policy.fields(capabilities: processingCapabilities, catalog: textActions, computer: true)) { _, new in new }
    let wireID = try newOperationID(), owner = generation
    let requireOriginal = processingCapabilities.available
    let capture = ComputerLiveCapture()
    operations[key] = (credential, route, wireID, capture)
    @MainActor func request(_ action: String, _ body: [String: Any]) async throws -> (Data, [String: Any]) {
      try Task.checkCancellation()
      guard self.accepts(owner), self.operations[key]?.wireID == wireID else { throw CancellationError() }
      let (data, code) = try await peer.recognition(action, operationID: wireID, token: credential.sessionToken, body: body)
      try Task.checkCancellation()
      guard self.accepts(owner), self.operations[key]?.wireID == wireID else { throw CancellationError() }
      if [401, 403].contains(code) { try self.invalidate(); throw ComputerFailure.authentication }
      guard code == 200 else { throw ComputerFailure.notReady }
      return (data, try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumResponseBytes))
    }
    capture.start(admit: {
      let (_, reply) = try await request("start", metadata)
      guard ComputerJSON.boolean(reply["started"]) == true,
        reply["format"] as? String == "pcm16_mono_16000",
        ComputerJSON.integer(reply["max_frame_bytes"]) == 2560 else { throw ComputerFailure.invalidResponse }
    }, feed: { sequence, frames in
      let batch: [[String: Any]] = frames.enumerated().map { ["sequence": sequence + $0.offset, "data": $0.element.base64EncodedString()] }
      let (_, reply) = try await request("feed", ["frames": batch])
      guard ComputerJSON.integer(reply["accepted"]) == sequence + frames.count - 1 else { throw ComputerFailure.invalidResponse }
      if let value = reply["partial"] {
        guard let text = value as? String, text.utf8.count <= 32768 else { throw ComputerFailure.invalidResponse }
        partial(text)
      }
    }, finish: { bytes, hash in
      let (data, raw) = try await request("finish", ["bytes": bytes, "sha256": hash])
      let result = try ComputerResult.decode(data, operationID: wireID.uuidString)
      guard policy.accepts(raw) else { throw ComputerFailure.invalidResponse }
      let applied = frozen.applied(in: raw, dictation: true, requireOriginalConfirmation: requireOriginal)
      let fallback = !result.successful && frozen.hasDictationFallback(in: raw) ? result.text : result.transcript
      self.operations.removeValue(forKey: key); self.retiredOperations.insert(key)
      return ComputerResult(operationID: localID, transcript: result.transcript, text: result.text,
        rewritten: result.rewritten, successful: result.successful).checkingPreferences(applied, original: fallback)
    }, abort: { self.cancelOperation(operationID) })
    return capture
  }
  @MainActor func process(_ operationID: String, action: String? = nil, text: String? = nil, wav: Data? = nil,
    language: String = ClarifyLocale.language, savedAction: TextActionDescriptor? = nil,
    preferences: OutputPreferences = OutputPreferences(), policy: DictationPolicy = .legacy) async throws -> ComputerResult {
    let effectivePreferences = action == nil
      ? policy.frozenPreferences(preferences, capabilities: processingCapabilities, catalog: textActions, computer: true) : preferences
    try Task.checkCancellation()
    guard let localID = UUID(uuidString: operationID) else { throw ComputerFailure.notReady }
    let key = localID.uuidString
    guard !retiredOperations.contains(key) else { throw CancellationError() }
    guard let credential, let route = activeRoute,
      savedAction.map({ $0.valid && $0.enabled && $0.ready }) ?? isReady(for: action ?? "dictate") else { throw ComputerFailure.notReady }
    guard !language.isEmpty, language.utf8.count <= 32,
      language.utf8.allSatisfy({ (65...90).contains($0) || (97...122).contains($0) || $0 == 45 }) else { throw ComputerFailure.invalidResponse }
    guard operations[key] == nil else { throw ComputerFailure.busy }
    let owner = generation
    try processingCapabilities.validate(effectivePreferences)
    var json: [String: Any] = ["language": language]
    for (key, value) in try effectivePreferences.requestFields(supported: outputPreferencesSupported, dictation: action == nil) { json[key] = value }
    if let action, let text {
      guard ["rewrite", "translate", "text_action"].contains(action), (action == "text_action") == (savedAction != nil),
        !text.contains("\0"), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.utf8.count <= ProcessingContractData.computerTextInputBytes else { throw ComputerFailure.invalidResponse }
      json["action"] = action; json["text"] = text
      if let savedAction {
        guard let revision = TextActionDescriptor.wireRevision(savedAction.revision),
          OutputLanguage(rawValue: language) != nil else { throw ComputerFailure.invalidResponse }
        json["action_id"] = savedAction.id; json["action_revision"] = revision
      }
    } else if let wav { try ComputerWAV.validate(wav); json["audio_wav"] = wav.base64EncodedString() }
    else { throw ComputerFailure.invalidAudio }
    if action == nil {
      for (key, value) in try policy.fields(capabilities: processingCapabilities, catalog: textActions, computer: true) { json[key] = value }
    }
    let custom = savedAction?.kind == "custom"
    let requiresOriginalConfirmation = processingCapabilities.available
    let wireID = try newOperationID()
    json["operation_id"] = wireID.uuidString
    operations[key] = (credential, route, wireID, nil)
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
        let messages = ["action_changed": "A ação mudou. Atualize as ações.",
          "text_action_missing": "A ação não existe. Atualize as ações.",
          "text_action_stale": "A ação mudou. Atualize as ações.",
          "text_action_disabled": "A ação está desativada.",
          "invalid_audio": "Grave um áudio válido de até 5 minutos.",
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
        let wireCode = raw?["error"] as? String
        let known = ProcessingContractData.value["errors"] as? [String: String] ?? [:]
        let stableCode = wireCode.flatMap { known[$0] != nil ? $0 : nil } ?? "computer_processing_failed"
        throw ClarifyError(message, code: stableCode, phase: action == nil ? "transcribing" : "rewriting", operationID: operationID, status: code)
      }
      let result = try ComputerResult.decode(data, operationID: wireID.uuidString)
      let raw = try ComputerJSON.object(data, maximum: ComputerProtocolLimits.maximumResponseBytes)
      if let savedAction {
        guard raw["action_id"] as? String == savedAction.id,
          ComputerJSON.integer(raw["action_revision"]).map({ String($0) }) == savedAction.revision else { throw ComputerFailure.invalidResponse }
      }
      if action == nil, !policy.accepts(raw) { throw ComputerFailure.invalidResponse }
      let retained = action == nil || custom || TextRetention.accepts(source: text ?? result.transcript, output: result.text)
      let applied = retained && (action == nil || result.successful) && effectivePreferences.applied(in: raw, dictation: action == nil, requireOriginalConfirmation: requiresOriginalConfirmation)
      let fallback = retained && action == nil && !result.successful && effectivePreferences.hasDictationFallback(in: raw)
        ? result.text : text ?? result.transcript
      return ComputerResult(operationID: localID, transcript: result.transcript, text: result.text,
        rewritten: result.rewritten, successful: result.successful).checkingPreferences(applied, original: fallback)
    } catch {
      if Task.isCancelled { cancelOperation(operationID); throw CancellationError() }
      guard accepts(owner), operations[key]?.wireID == wireID else { throw CancellationError() }
      if error as? ComputerFailure == .offline {
        ready = false; actionReadiness = .unavailable; textActions = .unavailable; outputPreferencesSupported = false; processingCapabilities = .unavailable; status = "offline"
      }
      throw error
    }
  }
}

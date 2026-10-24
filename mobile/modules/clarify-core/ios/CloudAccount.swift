import Foundation

private final class CloudTransport: NSObject, URLSessionTaskDelegate {
  func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
    completionHandler(nil) // Never forward a session to a redirect destination.
  }
}

struct CloudAccountState: Codable {
  var endpoint = ""
  var userID: String?
  var email = ""
  var pending = ""
  var hosted = false
  var sync = false
  var historyUserID: String?
}

struct HistoryCapture: Equatable {
  let scope: String?
  let generation: UInt64
}

struct CloudDictation: Codable {
  let transcript: String
  let text: String
  let rewritten: Bool
}

private struct VocabularyConflict: Error {}

// Mutations are initiated on the containing app's main queue. The short lock
// also protects snapshots during async work. No credential reaches JavaScript.
final class CloudAccount {
  static let shared = CloudAccount()
  private let defaults: UserDefaults
  private let lock = NSRecursiveLock()
  private var state: CloudAccountState
  private var lastRefreshAttempt = -Double.infinity
  private var lastSyncAttempt = -Double.infinity
  private var usage: [String: Any] = [:]
  private var busy = false
  private var automatic = false
  private var syncError = ""
  private var dictionaryConflict = false
  private var generation: UInt64 = 0
  private var historyBusy = false
  private var historyQueued = false
  private var lastHistoryAttempt = -Double.infinity
  private var historyFailed = false
  private let transport: ((URLRequest) async throws -> (Data, HTTPURLResponse))?
  private let readCredential: () -> String?
  private let saveCredential: (String?) throws -> Void
  private let historyClock: () -> TimeInterval
  private var sessionInvalidated: (() -> Void)?
  private let delegate = CloudTransport()
  private lazy var session: URLSession = {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.httpCookieStorage = nil
    configuration.urlCache = nil
    configuration.timeoutIntervalForRequest = 100
    configuration.timeoutIntervalForResource = 110
    return URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
  }()

  init(defaults: UserDefaults = .standard,
       transport: ((URLRequest) async throws -> (Data, HTTPURLResponse))? = nil,
       readCredential: @escaping () -> String? = AccountCredential.read,
       saveCredential: @escaping (String?) throws -> Void = AccountCredential.save,
       historyClock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
       sessionInvalidated: (() -> Void)? = nil) {
    self.defaults = defaults
    self.transport = transport; self.readCredential = readCredential; self.saveCredential = saveCredential
    self.historyClock = historyClock
    self.sessionInvalidated = sessionInvalidated
    state = defaults.data(forKey: "clarify.account.metadata").flatMap { try? JSONDecoder().decode(CloudAccountState.self, from: $0) } ?? CloudAccountState()
    if state.endpoint.isEmpty { state.endpoint = Bundle.main.object(forInfoDictionaryKey: "ClarifyCloudURL") as? String ?? "" }
    if state.userID != nil { state.hosted = true }
    if state.historyUserID == nil { state.historyUserID = state.userID }
  }
  private func locked<T>(_ body: () throws -> T) rethrows -> T {
    lock.lock(); defer { lock.unlock() }; return try body()
  }
  private func persist() throws { defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata") }
  func setSessionInvalidationHandler(_ handler: @escaping () -> Void) { locked { sessionInvalidated = handler } }
  var hosted: Bool { locked { state.userID != nil } }
  var managed: Bool { locked { state.userID != nil || state.hosted } }
  var scope: String? { locked { state.userID } }
  var historyScope: String? {
    locked {
      guard let user = state.historyUserID ?? state.userID, UUID(uuidString: user) != nil,
        let endpoint = try? Self.validateEndpoint(state.endpoint), !endpoint.isEmpty else { return nil }
      return endpoint + "|" + user
    }
  }
  func captureHistory() -> HistoryCapture { locked { HistoryCapture(scope: historyScope, generation: generation) } }
  func acceptsHistory(_ capture: HistoryCapture) -> Bool { locked { capture == captureHistory() } }
  var historyContext: String { locked { String(generation) } }
  func dictionaryChanged() {
    // A keyboard edit must reach the server before the next hosted clip, even
    // when the previous automatic synchronization happened less than a minute ago.
    locked { lastSyncAttempt = -.infinity; lastRefreshAttempt = -.infinity }
  }
  var isBusy: Bool { locked { busy } }
  var configured: Bool { locked { hosted && readCredential() != nil } }
  func snapshot() -> [String: Any] {
    locked { ["endpoint": state.endpoint, "signedIn": configured, "managed": managed, "email": state.email,
      "pending": state.pending, "hosted": hosted, "syncEnabled": state.sync,
      "busy": busy, "error": syncError, "dictionaryConflict": dictionaryConflict, "usage": usage, "historyAccount": historyScope != nil, "historyContext": historyContext] }
  }
  static func validateEndpoint(_ value: String) throws -> String {
    let value = value.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    if value.isEmpty { return "" }
    guard var url = URLComponents(string: value), let host = url.host, !host.isEmpty,
      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil, url.path.isEmpty,
      url.scheme?.lowercased() == "https" || (url.scheme?.lowercased() == "http" && ["localhost", "127.0.0.1", "::1"].contains(host.lowercased())) else {
      throw ClarifyError(L("Use um endereço HTTPS, sem caminho, usuário ou senha."))
    }
    url.scheme = url.scheme?.lowercased(); url.host = host.lowercased()
    if (url.scheme == "https" && url.port == 443) || (url.scheme == "http" && url.port == 80) { url.port = nil }
    guard let canonical = url.string else { throw ClarifyError(L("Use um endereço HTTPS, sem caminho, usuário ou senha.")) }
    return canonical
  }
  private func begin() throws {
    try locked {
      guard !busy else { throw ClarifyError(L("Aguarde a operação da conta.")) }
      busy = true; syncError = ""
    }
  }
  private func end() { locked { busy = false; automatic = false } }
  private func waitForAutomaticRefresh() async throws {
    while locked({ busy && automatic }) {
      try await Task.sleep(nanoseconds: 50_000_000)
    }
    try Task.checkCancellation()
  }
  @MainActor private func perform(_ method: String, _ path: String, json: [String: Any]? = nil, body: Data? = nil,
    contentType: String? = nil) async throws -> (Int, [String: Any]) {
    try Task.checkCancellation()
    let identity = locked { (state.endpoint, generation, readCredential()) }
    let base = try Self.validateEndpoint(identity.0)
    guard !base.isEmpty, let url = URL(string: base + path) else { throw ClarifyError(L("O serviço Clarify ainda não foi configurado nesta versão.")) }
    var request = URLRequest(url: url)
    request.timeoutInterval = path == "/v1/dictations" ? 100 : 15
    request.httpMethod = method
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    request.setValue(ClarifyLocale.language, forHTTPHeaderField: "Accept-Language")
    if let token = identity.2 { request.setValue(token, forHTTPHeaderField: "X-Session-Token") }
    if let json {
      request.httpBody = try JSONSerialization.data(withJSONObject: json)
      if path == "/v1/history/sync", (request.httpBody?.count ?? 0) > 400 * 1024 { throw ClarifyError(L("Resposta inválida do Clarify.")) }
      request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    } else if let body {
      request.httpBody = body
      request.setValue(contentType, forHTTPHeaderField: "Content-Type")
    }
    let data: Data, response: URLResponse
    if let transport { (data, response) = try await transport(request) }
    else { (data, response) = try await session.data(for: request) }
    guard let response = response as? HTTPURLResponse, data.count <= 512 * 1024 else { throw ClarifyError(L("Resposta inválida do Clarify.")) }
    // A proxy can return HTML or malformed JSON for an HTTP failure. Preserve
    // the status recovery (especially session revocation) without exposing it.
    let decoded: [String: Any]? = data.isEmpty ? [:] : (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    let result = decoded ?? [:]
    let invalidation = try locked { () -> (() -> Void)? in
      guard state.endpoint == identity.0, generation == identity.1, readCredential() == identity.2 else { throw CancellationError() }
      let expired = [401, 403].contains(response.statusCode) && path.hasPrefix("/v1/")
      if expired {
        try saveCredential(nil)
        state.historyUserID = state.historyUserID ?? state.userID
        state.userID = nil; state.sync = false; usage = [:]; generation &+= 1; try persist()
      }
      if !expired, let meta = result["meta"] as? [String: Any], let token = meta["session_token"] as? String { try saveCredential(token) }
      if !expired, let updatedUsage = result["usage"] as? [String: Any] { usage = updatedUsage }
      return expired ? sessionInvalidated : nil
    }
    // perform runs on the main actor. Resource owners observe the revoked
    // identity after persistence and outside the account lock.
    invalidation?()
    try Task.checkCancellation()
    if response.statusCode == 200, decoded == nil { throw ClarifyError(L("Resposta inválida do Clarify.")) }
    return (response.statusCode, result)
  }
  @MainActor private func refresh() async throws {
    lastRefreshAttempt = ProcessInfo.processInfo.systemUptime
    let (code, result) = try await perform("GET", "/v1/account")
    guard code == 200, let userID = result["id"] as? String, UUID(uuidString: userID) != nil,
      let email = result["email"] as? String else { throw ClarifyError(L("A sessão expirou. Entre na conta novamente.")) }
    try locked {
      if state.userID != userID { generation &+= 1; lastHistoryAttempt = -.infinity; historyFailed = false }
      state.userID = userID; state.email = email; state.pending = ""; state.hosted = true
      state.historyUserID = userID
      usage = result["usage"] as? [String: Any] ?? [:]
      try persist()
    }
  }
  @MainActor func command(_ action: String, value: String, library: LocalLibrary) async throws -> Bool {
    if action == "auto", scope == nil || isBusy || ProcessInfo.processInfo.systemUptime - lastRefreshAttempt < 60 { return false }
    if action != "auto" { try await waitForAutomaticRefresh() }
    try begin(); defer { end() }
    locked { automatic = action == "auto" }
    switch action {
    case "configure":
      guard locked({ state.userID == nil }) else { throw ClarifyError(L("Saia da conta antes de alterar o servidor.")) }
      let endpoint = try Self.validateEndpoint(value)
      try saveCredential(nil)
      try locked { generation &+= 1; state = CloudAccountState(); state.endpoint = endpoint; lastHistoryAttempt = -.infinity; historyFailed = false; try persist() }
    case "login", "signup":
      guard !configured else { throw ClarifyError(L("Saia da conta atual primeiro.")) }
      // Old metadata must not turn an unauthenticated login-code session into
      // an active account. Keep its cache scope for a later confirmed sign-in.
      try locked {
        if state.userID != nil {
          state.historyUserID = state.historyUserID ?? state.userID
          state.userID = nil; state.sync = false; usage = [:]; generation &+= 1; try persist()
        }
      }
      let path = action == "signup" ? "/auth/signup" : "/auth/continue"
      let (code, _) = try await perform("POST", "/_allauth/app/v1" + path, json: ["email": value.trimmingCharacters(in: .whitespacesAndNewlines)])
      guard code == 200 || code == 401 else { throw ClarifyError(L("Não foi possível enviar o código. Confira o e-mail ou aguarde antes de tentar novamente.")) }
      try locked { state.pending = action; state.email = value; try persist() }
    case "confirm":
      let signup = locked { state.pending == "signup" }
      let path = signup ? "/auth/email/verify" : "/auth/code/confirm"
      let (code, result) = try await perform("POST", "/_allauth/app/v1" + path, json: [signup ? "key" : "code": value])
      guard code == 200, (result["meta"] as? [String: Any])?["is_authenticated"] as? Bool == true else {
        throw ClarifyError(L("O código é inválido ou expirou. Solicite um novo código."))
      }
      try await refresh()
      try prepareLibrary(library)
      await syncQuietly(library)
    case "refresh": try await refresh()
    case "auto":
      do { try await refresh(); try prepareLibrary(library); await syncQuietly(library) }
      catch { locked { syncError = L("Não foi possível atualizar a conta. Os dados locais foram preservados.") } }
    case "sync", "sync-local", "sync-remote":
      try await syncImpl(library, prefer: action == "sync-local" ? "local" : action == "sync-remote" ? "remote" : nil)
    case "logout", "delete":
      let userID = locked { state.userID }
      let oldHistoryScope = historyScope
      // Invalidate in-flight history before the first suspension. It must not
      // restore a token, quota or cache after this explicit account transition.
      locked { generation &+= 1 }
      if action == "delete" {
        let (code, _) = try await perform("DELETE", "/v1/account", json: ["confirm": true])
        guard code == 204 else { throw ClarifyError(L("Não foi possível excluir a conta. Finalize o ditado e tente novamente.")) }
      } else { _ = try? await perform("DELETE", "/_allauth/app/v1/auth/session") }
      try saveCredential(nil)
      try locked { generation &+= 1; let endpoint = state.endpoint; state = CloudAccountState(); state.endpoint = endpoint; usage = [:]; dictionaryConflict = false; lastHistoryAttempt = -.infinity; historyFailed = false; try persist() }
      // End the local session even if the atomic cache purge fails.
      if action == "delete" { try library.deleteCloudAccount(dictionaryScope: userID, historyScope: oldHistoryScope) }
    default: throw ClarifyError(L("Ação de conta inválida."))
    }
    return true
  }
  // Main-queue owner, separate from account/dictation busy state. Offline work
  // is durable in SQLite; at most four bounded pages are sent in each burst.
  @MainActor func syncHistory(_ library: LocalLibrary, force: Bool = false) async -> Bool {
    guard hosted, !isBusy, let owner = historyScope else { return false }
    if historyBusy { historyQueued = historyQueued || force; return false }
    let now = historyClock()
    guard now - lastHistoryAttempt >= 60 || (force && !historyFailed) else { return false }
    historyBusy = true; historyQueued = false; lastHistoryAttempt = now
    let capture = captureHistory()
    defer { historyBusy = false }
    var changed = false
    do {
      for _ in 0..<4 {
        guard acceptsHistory(capture), hosted else { return changed }
        let batch = try library.historyBatch(scope: owner)
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(batch)) as? [String: Any] ?? [:]
        let (code, raw) = try await perform("POST", "/v1/history/sync", json: json)
        guard acceptsHistory(capture), hosted else { return changed }
        guard code == 200 else { throw ClarifyError(L("Não foi possível sincronizar o histórico.")) }
        let response = try HistorySyncResponse.decode(raw)
        try library.applyHistory(response, batch: batch, scope: owner)
        changed = changed || !response.entries.isEmpty || !response.deleted.isEmpty
        historyFailed = false
        let pending = try library.historyBatch(scope: owner).hasWork
        if !response.hasMore && !pending && !historyQueued { break }
        historyQueued = false
      }
    } catch { if acceptsHistory(capture) { historyFailed = true } }
    return changed
  }
  static func merge(base: [VocabularyEntry], local: [VocabularyEntry], remote: [VocabularyEntry], prefer: String? = nil) throws -> [VocabularyEntry] {
    func index(_ values: [VocabularyEntry]) throws -> [String: VocabularyEntry] {
      Dictionary(uniqueKeysWithValues: try VocabularyEntry.validate(values).map { ($0.term.lowercased(), $0) })
    }
    let b = try index(base), a = try index(local), c = try index(remote)
    var keys: [String] = []; var seen = Set<String>()
    for item in remote + local + base { if seen.insert(item.term.lowercased()).inserted { keys.append(item.term.lowercased()) } }
    var result: [VocabularyEntry] = []
    for key in keys {
      let chosen: VocabularyEntry?
      if a[key] == b[key] { chosen = c[key] }
      else if c[key] == b[key] || a[key] == c[key] { chosen = a[key] }
      else if prefer == "local" { chosen = a[key] }
      else if prefer == "remote" { chosen = c[key] }
      else { throw VocabularyConflict() }
      if let chosen { result.append(chosen) }
    }
    return try VocabularyEntry.validate(result)
  }
  @MainActor private func syncImpl(_ library: LocalLibrary, prefer: String? = nil) async throws {
    lastSyncAttempt = ProcessInfo.processInfo.systemUptime
    guard let userID = locked({ state.userID }) else { throw ClarifyError(L("Entre na sua conta primeiro.")) }
    let cached = try library.cloudDictionary(userID)
    let local = cached.revision == nil ? try library.dictionary() : cached.entries
    var (code, remote) = try await perform("GET", "/v1/dictionary")
    guard code == 200, let revision = remote["revision"] as? Int, let raw = remote["entries"] else { throw ClarifyError(L("Não foi possível carregar o dicionário da conta.")) }
    let remoteEntries = try JSONDecoder().decode([VocabularyEntry].self, from: JSONSerialization.data(withJSONObject: raw))
    let merged: [VocabularyEntry]
    do { merged = try Self.merge(base: cached.base, local: local, remote: remoteEntries, prefer: prefer) }
    catch is VocabularyConflict {
      locked { dictionaryConflict = true }
      throw ClarifyError(L("A mesma palavra mudou nos dois dispositivos. Escolha qual versão manter nas palavras em conflito."))
    }
    if merged != remoteEntries {
      let values = try JSONSerialization.jsonObject(with: JSONEncoder().encode(merged))
      (code, remote) = try await perform("PUT", "/v1/dictionary", json: ["revision": revision, "entries": values])
      guard code == 200 else { throw ClarifyError(L("O dicionário mudou em outro dispositivo. As cópias foram preservadas. Sincronize novamente.")) }
    }
    guard let updated = remote["revision"] as? Int else { throw ClarifyError(L("Resposta inválida do Clarify.")) }
    try library.saveCloudDictionary(CloudDictionary(entries: merged, base: merged, revision: updated), scope: userID)
    try locked { state.sync = true; dictionaryConflict = false; syncError = ""; try persist() }
  }
  @MainActor func syncAfterSave(_ library: LocalLibrary) async {
    do { _ = try await command("sync", value: "", library: library) }
    catch { locked { syncError = L("As palavras foram salvas neste iPhone. A sincronização será tentada novamente ao abrir o aplicativo.") } }
  }
  func saveDictionaryDraft(_ entries: [VocabularyEntry], base: [VocabularyEntry], library: LocalLibrary) throws {
    guard !managed || scope != nil else { throw ClarifyError(L("Entre na conta novamente.")) }
    let merged: [VocabularyEntry]
    do { merged = try Self.merge(base: base, local: entries, remote: library.dictionary(scope: scope)) }
    catch is VocabularyConflict {
      throw ClarifyError(L("A mesma palavra mudou nos dois dispositivos. Escolha qual versão manter nas palavras em conflito."))
    }
    try library.saveDictionary(merged, scope: scope)
  }
  func prepareLibrary(_ library: LocalLibrary) throws {
    guard let userID = scope else { return }
    let cached = try library.cloudDictionary(userID)
    if cached.revision == nil {
      try library.saveCloudDictionary(CloudDictionary(entries: library.dictionary(), base: [], revision: -1), scope: userID)
    }
  }
  @MainActor private func syncQuietly(_ library: LocalLibrary) async {
    guard !locked({ dictionaryConflict }) else { return }
    do { try await syncImpl(library) }
    catch { locked { syncError = L("Não foi possível sincronizar. As palavras salvas neste dispositivo foram preservadas.") } }
  }
  static func processingFailure(_ status: Int, result: [String: Any], operationID: String) -> ClarifyError {
    let messages = [
      "authentication_required": "Entre na conta novamente.",
      "no_speech": "Nenhuma fala foi reconhecida. Tente falar novamente.",
      "transcription_failed": "Não foi possível transcrever o áudio. Tente novamente.",
      "text_processing_failed": "Não foi possível processar o texto. Tente novamente.",
      "processing_failed": "Não foi possível concluir o processamento. Tente novamente.",
      "invalid_audio": "Grave um áudio válido de até 5 minutos.",
      "invalid_duration": "Grave um áudio válido de até 5 minutos.",
      "invalid_audio_request": "Grave um áudio válido de até 5 minutos.",
      "invalid_text_request": "Selecione um texto válido para processar.",
      "allowance_exhausted": "Sua cota foi atingida.",
      "rate_limited": "Muitas solicitações. Aguarde um momento.",
      "account_busy": "Já existe um processamento em andamento.",
      "operation_pending": "Já existe um processamento em andamento.",
      "service_busy": "O Clarify está ocupado. Aguarde um momento.",
      "hosted_unavailable": "O processamento do Clarify está indisponível no momento.",
      "service_budget_exhausted": "O processamento do Clarify está indisponível no momento.",
      "operation_conflict": "Esta solicitação não pode ser repetida. Inicie uma nova ação.",
      "operation_expired": "Esta solicitação não pode ser repetida. Inicie uma nova ação."
    ]
    // HTTP authentication failures override a contradictory payload. The
    // perform boundary has already invalidated the expired session.
    let rawCode = [401, 403].contains(status) ? "authentication_required" : result["code"] as? String
    let code = rawCode.flatMap { messages[$0] == nil ? nil : $0 }
    let fallback: String
    switch status {
    case 401, 403: fallback = "Entre na conta novamente."
    case 429: fallback = "Muitas solicitações. Aguarde um momento."
    case 503: fallback = "O processamento do Clarify está indisponível no momento."
    case 400: fallback = "Grave um áudio válido de até 5 minutos."
    default: fallback = "Não foi possível concluir o processamento. Tente novamente."
    }
    let phase = (result["phase"] as? String).flatMap { ["validation", "admission", "transcription", "processing", "text"].contains($0) ? $0 : nil }
    let receivedOperation = (result["operation_id"] as? String).flatMap(UUID.init(uuidString:))
    let expectedOperation = UUID(uuidString: operationID)
    let diagnosticOperation = receivedOperation != nil && receivedOperation == expectedOperation ? receivedOperation?.uuidString : nil
    return ClarifyError(code.flatMap { messages[$0] } ?? fallback, code: code, phase: phase,
      operationID: diagnosticOperation, status: status)
  }
  @MainActor func dictate(_ audio: URL, operationID: String, library: LocalLibrary) async throws -> CloudDictation {
    guard configured else { throw ClarifyError(L("Entre na conta novamente.")) }
    try await waitForAutomaticRefresh()
    try begin(); defer { end() }
    if scope != nil && ProcessInfo.processInfo.systemUptime - lastSyncAttempt >= 60 {
      do { try await syncImpl(library) }
      catch { try Task.checkCancellation(); locked { syncError = L("O ditado usou a última versão do dicionário da conta. Há palavras pendentes de sincronização.") } }
    }
    guard configured else { throw ClarifyError(L("Entre na conta novamente.")) }
    let bytes = try Data(contentsOf: audio)
    guard bytes.count <= 24 * 1024 * 1024, UUID(uuidString: operationID) != nil else { throw ClarifyError(L("Grave um trecho menor.")) }
    let boundary = "Clarify-\(UUID().uuidString)"
    var body = Data()
    func append(_ value: String) { body.append(Data(value.utf8)) }
    append("--\(boundary)\r\nContent-Disposition: form-data; name=\"operation_id\"\r\n\r\n\(operationID)\r\n")
    append("--\(boundary)\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"clip.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n")
    body.append(bytes); append("\r\n--\(boundary)--\r\n")
    let (code, result) = try await perform("POST", "/v1/dictations", body: body, contentType: "multipart/form-data; boundary=\(boundary)")
    guard code == 200 else {
      throw Self.processingFailure(code, result: result, operationID: operationID)
    }
    guard let outcome = try? JSONDecoder().decode(CloudDictation.self, from: JSONSerialization.data(withJSONObject: result)),
      !outcome.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      !outcome.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw ClarifyError(L("O Clarify retornou um resultado inválido.")) }
    return outcome
  }
}

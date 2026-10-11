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
  private var usage: [String: Any] = [:]
  private var busy = false
  private var syncError = ""
  private var dictionaryConflict = false
  private let delegate = CloudTransport()
  private lazy var session: URLSession = {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.httpCookieStorage = nil
    configuration.urlCache = nil
    configuration.timeoutIntervalForRequest = 100
    configuration.timeoutIntervalForResource = 110
    return URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
  }()

  init(defaults: UserDefaults = .standard) {
    self.defaults = defaults
    state = defaults.data(forKey: "clarify.account.metadata").flatMap { try? JSONDecoder().decode(CloudAccountState.self, from: $0) } ?? CloudAccountState()
    if state.endpoint.isEmpty { state.endpoint = Bundle.main.object(forInfoDictionaryKey: "ClarifyCloudURL") as? String ?? "" }
  }
  private func locked<T>(_ body: () throws -> T) rethrows -> T {
    lock.lock(); defer { lock.unlock() }; return try body()
  }
  private func persist() throws { defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata") }
  var hosted: Bool { locked { state.hosted } }
  var scope: String? { locked { state.sync ? state.userID : nil } }
  var isBusy: Bool { locked { busy } }
  var configured: Bool { locked { state.hosted ? state.userID != nil && AccountCredential.read() != nil : KeyStore.read() != nil } }
  func snapshot() -> [String: Any] {
    locked { ["endpoint": state.endpoint, "signedIn": state.userID != nil, "email": state.email,
      "pending": state.pending, "hosted": state.hosted, "syncEnabled": scope != nil,
      "busy": busy, "error": syncError, "dictionaryConflict": dictionaryConflict, "usage": usage, "hasGroqKey": KeyStore.read() != nil] }
  }
  static func validateEndpoint(_ value: String) throws -> String {
    let value = value.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    if value.isEmpty { return "" }
    guard let url = URLComponents(string: value), let host = url.host, !host.isEmpty,
      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil, url.path.isEmpty,
      url.scheme == "https" || (url.scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host)) else {
      throw ClarifyError("Use um endereço HTTPS, sem caminho, usuário ou senha.")
    }
    return value
  }
  private func begin() throws {
    try locked {
      guard !busy else { throw ClarifyError("Aguarde a operação da conta.") }
      busy = true; syncError = ""
    }
  }
  private func end() { locked { busy = false } }
  private func perform(_ method: String, _ path: String, json: [String: Any]? = nil, body: Data? = nil,
    contentType: String? = nil) async throws -> (Int, [String: Any]) {
    try Task.checkCancellation()
    let base = try Self.validateEndpoint(locked { state.endpoint })
    guard !base.isEmpty, let url = URL(string: base + path) else { throw ClarifyError("O serviço Clarify ainda não foi configurado nesta versão.") }
    var request = URLRequest(url: url)
    request.httpMethod = method
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    if let token = AccountCredential.read() { request.setValue(token, forHTTPHeaderField: "X-Session-Token") }
    if let json {
      request.httpBody = try JSONSerialization.data(withJSONObject: json)
      request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    } else if let body {
      request.httpBody = body
      request.setValue(contentType, forHTTPHeaderField: "Content-Type")
    }
    let (data, response) = try await session.data(for: request)
    try Task.checkCancellation()
    guard let response = response as? HTTPURLResponse, data.count <= 512 * 1024 else { throw ClarifyError("Resposta inválida do Clarify.") }
    let result = data.isEmpty ? [:] : try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    if [401, 403].contains(response.statusCode), path.hasPrefix("/v1/") {
      try AccountCredential.save(nil)
      try locked { state.userID = nil; state.sync = false; usage = [:]; try persist() }
    }
    if let meta = result["meta"] as? [String: Any], let token = meta["session_token"] as? String {
      try AccountCredential.save(token)
    }
    return (response.statusCode, result)
  }
  private func refresh() async throws {
    let (code, result) = try await perform("GET", "/v1/account")
    guard code == 200, let userID = result["id"] as? String, UUID(uuidString: userID) != nil,
      let email = result["email"] as? String else { throw ClarifyError("A sessão expirou. Entre na conta novamente.") }
    try locked {
      state.userID = userID; state.email = email; state.pending = ""
      usage = result["usage"] as? [String: Any] ?? [:]
      try persist()
    }
  }
  func command(_ action: String, value: String, library: LocalLibrary) async throws {
    try begin(); defer { end() }
    switch action {
    case "configure":
      guard locked({ state.userID == nil }) else { throw ClarifyError("Saia da conta antes de alterar o servidor.") }
      let endpoint = try Self.validateEndpoint(value)
      try AccountCredential.save(nil)
      try locked { state = CloudAccountState(); state.endpoint = endpoint; try persist() }
    case "login", "signup":
      guard locked({ state.userID == nil }) else { throw ClarifyError("Saia da conta atual primeiro.") }
      let path = action == "signup" ? "/auth/signup" : "/auth/code/request"
      let (code, _) = try await perform("POST", "/_allauth/app/v1" + path, json: ["email": value.trimmingCharacters(in: .whitespacesAndNewlines)])
      guard code == 200 || code == 401 else { throw ClarifyError("Não foi possível enviar o código. Confira o e-mail ou aguarde antes de tentar novamente.") }
      try locked { state.pending = action; state.email = value; try persist() }
    case "confirm":
      let signup = locked { state.pending == "signup" }
      let path = signup ? "/auth/email/verify" : "/auth/code/confirm"
      let (code, result) = try await perform("POST", "/_allauth/app/v1" + path, json: [signup ? "key" : "code": value])
      guard code == 200, (result["meta"] as? [String: Any])?["is_authenticated"] as? Bool == true else {
        throw ClarifyError("O código é inválido ou expirou. Solicite um novo código.")
      }
      try await refresh()
    case "refresh": try await refresh()
    case "hosted":
      try locked {
        guard state.userID != nil || value != "1" else { throw ClarifyError("Entre na sua conta primeiro.") }
        state.hosted = value == "1"; try persist()
      }
    case "sync", "sync-local", "sync-remote":
      try await syncImpl(library, prefer: action == "sync-local" ? "local" : action == "sync-remote" ? "remote" : nil)
    case "logout", "delete":
      let userID = locked { state.userID }
      if action == "delete" {
        let (code, _) = try await perform("DELETE", "/v1/account", json: ["confirm": true])
        guard code == 204 else { throw ClarifyError("Não foi possível excluir a conta. Finalize o ditado e tente novamente.") }
      } else { _ = try? await perform("DELETE", "/_allauth/app/v1/auth/session") }
      try AccountCredential.save(nil)
      try locked { let endpoint = state.endpoint; state = CloudAccountState(); state.endpoint = endpoint; usage = [:]; dictionaryConflict = false; try persist() }
      // End the local session even if purging its dictionary cache fails.
      if action == "delete", let userID { try library.deleteCloudDictionary(userID) }
    default: throw ClarifyError("Ação de conta inválida.")
    }
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
  private func syncImpl(_ library: LocalLibrary, prefer: String? = nil) async throws {
    guard let userID = locked({ state.userID }) else { throw ClarifyError("Entre na sua conta primeiro.") }
    let cached = try library.cloudDictionary(userID)
    let local = cached.revision == nil ? try library.dictionary() : cached.entries
    var (code, remote) = try await perform("GET", "/v1/dictionary")
    guard code == 200, let revision = remote["revision"] as? Int, let raw = remote["entries"] else { throw ClarifyError("Não foi possível carregar o dicionário da conta.") }
    let remoteEntries = try JSONDecoder().decode([VocabularyEntry].self, from: JSONSerialization.data(withJSONObject: raw))
    let merged: [VocabularyEntry]
    do { merged = try Self.merge(base: cached.base, local: local, remote: remoteEntries, prefer: prefer) }
    catch is VocabularyConflict {
      locked { dictionaryConflict = true }
      throw ClarifyError("A mesma palavra mudou nos dois dispositivos. Escolha qual versão manter nas palavras em conflito.")
    }
    if merged != remoteEntries {
      let values = try JSONSerialization.jsonObject(with: JSONEncoder().encode(merged))
      (code, remote) = try await perform("PUT", "/v1/dictionary", json: ["revision": revision, "entries": values])
      guard code == 200 else { throw ClarifyError("O dicionário mudou em outro dispositivo. As cópias foram preservadas. Sincronize novamente.") }
    }
    guard let updated = remote["revision"] as? Int else { throw ClarifyError("Resposta inválida do Clarify.") }
    try library.saveCloudDictionary(CloudDictionary(entries: merged, base: merged, revision: updated), scope: userID)
    try locked { state.sync = true; dictionaryConflict = false; syncError = ""; try persist() }
  }
  func syncAfterSave(_ library: LocalLibrary) async {
    do { try await command("sync", value: "", library: library) }
    catch { locked { syncError = "As palavras foram salvas neste iPhone. Não foi possível sincronizar. Tente em Ajustes > Conta Clarify." } }
  }
  func dictate(_ audio: URL, operationID: String, library: LocalLibrary) async throws -> CloudDictation {
    try begin(); defer { end() }
    if scope != nil {
      do { try await syncImpl(library) }
      catch { try Task.checkCancellation(); locked { syncError = "O ditado usou a última versão do dicionário da conta. Há palavras pendentes de sincronização." } }
    }
    let bytes = try Data(contentsOf: audio)
    guard bytes.count <= 24 * 1024 * 1024, UUID(uuidString: operationID) != nil else { throw ClarifyError("Grave um trecho menor.") }
    let boundary = "Clarify-\(UUID().uuidString)"
    var body = Data()
    func append(_ value: String) { body.append(Data(value.utf8)) }
    append("--\(boundary)\r\nContent-Disposition: form-data; name=\"operation_id\"\r\n\r\n\(operationID)\r\n")
    append("--\(boundary)\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"clip.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n")
    body.append(bytes); append("\r\n--\(boundary)--\r\n")
    let (code, result) = try await perform("POST", "/v1/dictations", body: body, contentType: "multipart/form-data; boundary=\(boundary)")
    guard code == 200 else {
      switch code {
      case 401, 403: throw ClarifyError("Entre na conta novamente.")
      case 429: throw ClarifyError("Sua cota ou o limite de solicitações foi atingido. Aguarde ou use sua própria chave.")
      case 503: throw ClarifyError("O processamento do Clarify está indisponível. Tente mais tarde ou use sua própria chave.")
      case 400: throw ClarifyError("Grave um áudio válido de até 5 minutos.")
      default: throw ClarifyError("Não foi possível processar o áudio. A cota pode ter sido consumida.")
      }
    }
    let outcome = try JSONDecoder().decode(CloudDictation.self, from: JSONSerialization.data(withJSONObject: result))
    guard !outcome.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      !outcome.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw ClarifyError("O Clarify retornou um resultado inválido.") }
    return outcome
  }
}

import Foundation

struct GroqClient {
  let key: String
  var session: URLSession = .shared
  var vocabulary: [VocabularyEntry] = []

  private func perform(_ request: URLRequest) async throws -> [String: Any] {
    try Task.checkCancellation()
    let (data, response) = try await session.data(for: request)
    try Task.checkCancellation()
    guard let http = response as? HTTPURLResponse else { throw ClarifyError("Resposta inválida do Groq.") }
    guard (200..<300).contains(http.statusCode) else {
      switch http.statusCode {
      case 401, 403: throw ClarifyError("Verifique a chave e as permissões do Groq.")
      case 413: throw ClarifyError("A gravação excedeu o limite do Groq.")
      case 429: throw ClarifyError("Limite do Groq atingido. Aguarde e tente novamente.")
      default: throw ClarifyError("O Groq não respondeu. Tente novamente.")
      }
    }
    guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
      throw ClarifyError("Resposta inválida do Groq.")
    }
    return json
  }
  private func request(_ path: String) -> URLRequest {
    var request = URLRequest(url: URL(string: "https://api.groq.com/openai/v1/\(path)")!)
    request.httpMethod = "POST"
    request.timeoutInterval = 90
    request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
    return request
  }
  func transcribe(_ audio: URL) async throws -> String {
    let data = try Data(contentsOf: audio)
    guard data.count < 24_000_000 else { throw ClarifyError("A gravação é muito grande. Grave um trecho menor.") }
    let boundary = "Clarify-\(UUID().uuidString)"
    var body = Data()
    func append(_ value: String) { body.append(Data(value.utf8)) }
    for (name, value) in [("model", "whisper-large-v3-turbo"), ("response_format", "json"), ("temperature", "0")] {
      append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
    }
    let context = VocabularyEntry.speechContext(vocabulary)
    if !context.isEmpty {
      append("--\(boundary)\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\n\(context)\r\n")
    }
    append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n")
    body.append(data)
    append("\r\n--\(boundary)--\r\n")
    var request = request("audio/transcriptions")
    request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
    request.httpBody = body
    let json = try await perform(request)
    guard let text = json["text"] as? String, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      throw ClarifyError("Nenhuma fala foi reconhecida. Tente novamente.")
    }
    return text.trimmingCharacters(in: .whitespacesAndNewlines)
  }
  func rewrite(_ transcript: String) async throws -> String {
    var request = request("chat/completions")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONSerialization.data(withJSONObject: [
      "model": "openai/gpt-oss-20b", "temperature": 0.1, "max_completion_tokens": 8192,
      "reasoning_effort": "low",
      "messages": [
        ["role": "system", "content": RewritePrompt.system + VocabularyEntry.rewriteContext(vocabulary)],
        ["role": "user", "content": RewritePrompt.source(transcript)]
      ]
    ])
    let json = try await perform(request)
    guard let choices = json["choices"] as? [[String: Any]],
          let choice = choices.first, choice["finish_reason"] as? String == "stop",
          let message = choice["message"] as? [String: Any], let text = message["content"] as? String,
          !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      throw ClarifyError("A reescrita não foi concluída. A transcrição foi preservada.")
    }
    let result = text.trimmingCharacters(in: .whitespacesAndNewlines)
    func normalized(_ value: String) -> String {
      value.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }
    let sourceSize = normalized(transcript).count
    if sourceSize >= 240, normalized(result).count * 4 < sourceSize {
      // Same desktop safety rule: large reduction requires exact deduplication.
      let separated = transcript.replacingOccurrences(of: #"(?<=[.!?。！？])\s+"#,
        with: "\n", options: .regularExpression).components(separatedBy: "\n").map(normalized).filter { !$0.isEmpty }
      var seen = Set<String>()
      let unique = separated.filter { seen.insert($0).inserted }
      guard unique.count < separated.count, normalized(result) == unique.joined(separator: " ") else {
        throw ClarifyError("A reescrita removeu parte demais do texto. A transcrição foi preservada.")
      }
    }
    return result
  }
}

import XCTest
@testable import ClarifyContracts

final class MockProtocol: URLProtocol {
  static var handle: ((URLRequest) throws -> (Int, Data))?
  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    do {
      let (status, data) = try Self.handle!(request)
      client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
      client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    } catch { client?.urlProtocol(self, didFailWithError: error) }
  }
  override func stopLoading() {}
}

final class ContractsTests: XCTestCase {
  private func body(_ request: URLRequest) throws -> Data {
    if let data = request.httpBody { return data }
    let stream = try XCTUnwrap(request.httpBodyStream)
    stream.open(); defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while stream.hasBytesAvailable {
      let count = stream.read(&buffer, maxLength: buffer.count)
      if count < 0 { throw stream.streamError ?? ClarifyError("Test stream failed") }
      if count == 0 { break }
      data.append(buffer, count: count)
    }
    return data
  }
  private func client() -> GroqClient {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [MockProtocol.self]
    return GroqClient(key: "test-key", session: URLSession(configuration: config))
  }
  override func tearDown() { MockProtocol.handle = nil }
  func testRewriteUsesOneGroqKeyAndPreservesLanguageInstruction() async throws {
    MockProtocol.handle = { request in
      XCTAssertEqual(request.url?.absoluteString, "https://api.groq.com/openai/v1/chat/completions")
      XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-key")
      let json = try JSONSerialization.jsonObject(with: self.body(request)) as! [String: Any]
      XCTAssertEqual(json["model"] as? String, "openai/gpt-oss-20b")
      let messages = json["messages"] as! [[String: String]]
      XCTAssertEqual(messages.last?["content"], RewritePrompt.source("olá, é, mundo"))
      XCTAssertEqual(messages.first?["content"], RewritePrompt.system)
      XCTAssertTrue(RewritePrompt.system.contains("Schedule it for Thursday."))
      XCTAssertTrue(RewritePrompt.system.contains("the same language as the source transcript"))
      XCTAssertTrue(RewritePrompt.system.contains("Preserve uncertainty, alternatives"))
      return (200, Data(#"{"choices":[{"finish_reason":"stop","message":{"content":"Olá, mundo."}}]}"#.utf8))
    }
    let result = try await client().rewrite("olá, é, mundo")
    XCTAssertEqual(result, "Olá, mundo.")
  }
  func testTruncatedRewriteIsNotPublishedAsComplete() async {
    MockProtocol.handle = { _ in (200, Data(#"{"choices":[{"finish_reason":"length","message":{"content":"Partial"}}]}"#.utf8)) }
    do { _ = try await client().rewrite("A complete sentence"); XCTFail("Truncated text must be rejected") }
    catch { XCTAssertEqual(error.localizedDescription, L("A reescrita não foi concluída. A transcrição foi preservada.")) }
  }
  func testLongTranscriptCannotBeReplacedWithASummary() async {
    MockProtocol.handle = { _ in (200, Data(#"{"choices":[{"finish_reason":"stop","message":{"content":"Resumo curto."}}]}"#.utf8)) }
    let source = (1...20).map { "Requisito \($0): manter este detalhe." }.joined(separator: " ")
    do { _ = try await client().rewrite(source); XCTFail("Summary must preserve original transcript for recovery") }
    catch { XCTAssertEqual(error.localizedDescription, L("A reescrita removeu parte demais do texto. A transcrição foi preservada.")) }
  }
  func testExactDuplicateRemovalCanReduceALongTranscript() async throws {
    MockProtocol.handle = { _ in (200, Data(#"{"choices":[{"finish_reason":"stop","message":{"content":"Enviar cinco cópias para Ana."}}]}"#.utf8)) }
    let source = Array(repeating: "Enviar cinco cópias para Ana.", count: 12).joined(separator: " ")
    let result = try await client().rewrite(source)
    XCTAssertEqual(result, "Enviar cinco cópias para Ana.")
  }
  func testAuthenticationErrorDoesNotLeakProviderResponse() async {
    MockProtocol.handle = { _ in (401, Data("private provider detail".utf8)) }
    do { _ = try await client().rewrite("text"); XCTFail("Unauthorized request succeeded") }
    catch { XCTAssertEqual(error.localizedDescription, L("Verifique a chave e as permissões do Groq.")) }
  }
  func testTranscriptionUploadsM4AWithTheSameGroqKey() async throws {
    let audio = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".m4a")
    try Data("synthetic audio bytes".utf8).write(to: audio)
    defer { try? FileManager.default.removeItem(at: audio) }
    MockProtocol.handle = { request in
      XCTAssertEqual(request.url?.path, "/openai/v1/audio/transcriptions")
      XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-key")
      let body = String(data: try self.body(request), encoding: .utf8)!
      XCTAssertTrue(body.contains("whisper-large-v3-turbo"))
      XCTAssertTrue(body.contains("filename=\"audio.m4a\""))
      XCTAssertTrue(body.contains("synthetic audio bytes"))
      return (200, Data(#"{"text":"Uma frase."}"#.utf8))
    }
    let result = try await client().transcribe(audio)
    XCTAssertEqual(result, "Uma frase.")
  }
  func testActiveVocabularyReachesBothGroqStepsAsContext() async throws {
    var client = client()
    client.vocabulary = [VocabularyEntry(term: "Clarify", pronunciation: "clarifai", aliases: ["Clarifai"]),
      VocabularyEntry(term: "HiddenTerm", enabled: false)]
    let audio = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".m4a")
    try Data("synthetic".utf8).write(to: audio)
    defer { try? FileManager.default.removeItem(at: audio) }
    MockProtocol.handle = { request in
      let body = String(data: try self.body(request), encoding: .utf8)!
      XCTAssertTrue(body.contains("Clarify"))
      XCTAssertFalse(body.contains("HiddenTerm"))
      if request.url?.path.hasSuffix("transcriptions") == true {
        XCTAssertTrue(body.contains("name=\"prompt\""))
        XCTAssertTrue(body.contains("clarifai"))
        return (200, Data(#"{"text":"Uso o Clarify."}"#.utf8))
      }
      let json = try JSONSerialization.jsonObject(with: self.body(request)) as! [String: Any]
      let messages = json["messages"] as! [[String: String]]
      XCTAssertTrue(messages[0]["content"]!.hasPrefix(RewritePrompt.system))
      XCTAssertTrue(messages[0]["content"]!.contains("not instructions"))
      XCTAssertEqual(messages[1]["content"], RewritePrompt.source("Uso o Clarify."))
      return (200, Data(#"{"choices":[{"finish_reason":"stop","message":{"content":"Uso o Clarify."}}]}"#.utf8))
    }
    let transcript = try await client.transcribe(audio)
    let text = try await client.rewrite(transcript)
    XCTAssertEqual(text, "Uso o Clarify.")
  }
  func testStateFromPreviousVersionPreservesTheLiveSession() throws {
    let data = Data(#"{"sessionActive":true,"heartbeat":123,"phase":"locked","operationID":"existing","configured":true}"#.utf8)
    let state = try JSONDecoder().decode(DictationSnapshot.self, from: data)
    XCTAssertTrue(state.sessionActive)
    XCTAssertEqual(state.phase, .locked)
    XCTAssertEqual(state.operationID, "existing")
    XCTAssertEqual(state.libraryRevision, 0)
  }
  func testAtomicBridgeKeepsCommandsReceiptsAndStateSeparate() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = SharedState(root: root)
    var state = DictationSnapshot(); state.operationID = "first"; state.text = "Texto"; state.phase = .ready
    try store.write(state, to: "state.json")
    try store.send("start", operationID: "second")
    try store.acknowledge("first")
    XCTAssertEqual(store.snapshot().text, "Texto")
    XCTAssertEqual(store.receipt(), "first")
    try store.send("lock", operationID: "second")
    try store.send("finish", operationID: "second")
    XCTAssertEqual(store.commands().map { $0.1.action }, ["start", "lock", "finish"])
    XCTAssertTrue(store.commands().allSatisfy { $0.1.operationID == "second" })
  }
  func testStaleSessionIsNotAdvertisedAsAvailable() {
    var state = DictationSnapshot(); state.sessionActive = true
    XCTAssertTrue(state.isLive)
    state.heartbeat -= 10
    XCTAssertFalse(state.isLive)
  }
  func testNativeUpwardLockAndReleaseDoNotStopUntilNextPress() {
    var gesture = RecordGesture()
    XCTAssertEqual(gesture.press(), "start")
    XCTAssertNil(gesture.move(vertical: 80))
    XCTAssertNil(gesture.move(vertical: 0)) // Horizontal-only movement.
    XCTAssertNil(gesture.move(vertical: -27))
    XCTAssertEqual(gesture.move(vertical: -28), "lock")
    XCTAssertNil(gesture.move(vertical: -90))
    XCTAssertNil(gesture.release())
    XCTAssertEqual(gesture.press(), "finish")
    XCTAssertNil(gesture.release())
    XCTAssertEqual(gesture.press(), "start")
    XCTAssertEqual(gesture.release(), "finish")
  }
  func testKeyboardCasingPagesAndPortugueseAccents() {
    var keyboard = KeyboardState()
    XCTAssertEqual(keyboard.rows[0][0], "Q")
    keyboard.didInsert("Q")
    XCTAssertEqual(keyboard.rows[0][0], "q")
    keyboard.toggleShift(caps: true); keyboard.didInsert("Q")
    XCTAssertEqual(keyboard.rows[0][0], "Q")
    keyboard.page = .numbers
    XCTAssertEqual(keyboard.rows[0].joined(), "1234567890")
    keyboard.page = .symbols
    XCTAssertTrue(keyboard.rows.flatMap { $0 }.contains("€"))
    keyboard.didInsert(" ")
    XCTAssertEqual(keyboard.page, .letters)
    XCTAssertTrue(KeyboardState.accents(for: "a").contains("ã"))
    XCTAssertEqual(KeyboardState.accents(for: "C"), ["C", "Ç"])
  }
}

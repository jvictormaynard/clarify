import XCTest
@testable import ClarifyContracts

// This test is opt-in. The ordinary suite never reads credentials, records audio,
// or calls the service. The fixture uses dedicated temporary accounts only.
final class SnippetAcceptanceTests: XCTestCase {
  private struct Clip: Decodable { let filename: String; let kind: String; let expectedTextContains: [String]? }
  private struct Fixture: Decodable {
    let endpoint: String; let userID: String; let token: String
    let peerUserID: String?; let peerToken: String?
    let trigger: String; let replacement: String; let recursiveTrigger: String?; let clips: [Clip]
  }
  private struct AcceptanceFailure: Error {}
  private func require(_ condition: Bool) throws { if !condition { throw AcceptanceFailure() } }
  private func normalized(_ value: String) -> String {
    value.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "en_US_POSIX"))
      .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
  }
  @MainActor func testLiveSnippetService() async throws {
    guard let file = ProcessInfo.processInfo.environment["CLARIFY_SNIPPETS_ACCEPTANCE_FILE"],
      let reportPath = ProcessInfo.processInfo.environment["CLARIFY_SNIPPETS_ACCEPTANCE_REPORT"] else {
      throw XCTSkip("Live snippets acceptance is not enabled.")
    }
    let input = URL(fileURLWithPath: file), root = input.deletingLastPathComponent()
    let suite = "ClarifySnippetAcceptance." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    var evidence: [String: Any] = ["passed": false]
    do {
      let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: input))
      try require(UUID(uuidString: fixture.userID) != nil && !fixture.token.isEmpty)
      var state = CloudAccountState(); state.endpoint = try CloudAccount.validateEndpoint(fixture.endpoint)
      state.userID = fixture.userID; state.hosted = true
      defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
      var credential: String? = fixture.token
      let account = CloudAccount(defaults: defaults, readCredential: { credential }, saveCredential: { credential = $0 })
      let storage = root.appendingPathComponent("library", isDirectory: true)
      let library = try LocalLibrary(root: storage), owner = try XCTUnwrap(account.snippetScope)
      let guest = Snippet(trigger: "guest fixture", replacement: "Local fixture only")
      try library.saveSnippets([guest])
      _ = try await account.command("sync", value: "", library: library)
      let before = try library.snippets(scope: owner)
      let saved = Snippet(trigger: fixture.trigger, replacement: fixture.replacement)
      let recursive = Snippet(trigger: fixture.recursiveTrigger ?? "segunda frase", replacement: "RECURSION SHOULD NOT RUN")
      let entries = before.filter { ![Snippet.key(saved.trigger), Snippet.key(recursive.trigger)].contains(Snippet.key($0.trigger)) } + [saved, recursive]
      try account.saveSnippetDraft(entries, base: before, context: account.historyContext, library: library)
      _ = try await account.command("sync", value: "", library: library)
      let reopened = try LocalLibrary(root: storage)
      try require(try reopened.cloudSnippets(owner).entries == entries && reopened.cloudSnippets(owner).base == entries)
      try require(try reopened.snippets() == [guest])
      evidence["account_persisted"] = true; evidence["guest_preserved"] = true
      let onePass = [Snippet(trigger: "first phrase", replacement: "second phrase"), Snippet(trigger: "second phrase", replacement: "Forbidden")]
      try require(try Snippet.expand("first phrase", entries: onePass) == "second phrase")
      evidence["single_pass"] = true
      var hosted = 0, standalone = 0, inline = 0
      for clip in fixture.clips {
        let outcome = try await account.dictate(root.appendingPathComponent(clip.filename), operationID: UUID().uuidString, library: library)
        try require(outcome.successful && outcome.snippetExpanded == true)
        try require(!outcome.text.contains(recursive.replacement))
        try require(normalized(outcome.transcript).contains(normalized(fixture.trigger)))
        if clip.kind == "standalone" {
          try require(outcome.text == fixture.replacement && !outcome.rewritten); standalone += 1
        } else {
          // Rewriting sees the expanded source and may change its spelling or
          // line breaks. Check synthetic semantic markers rather than imposing
          // the former post-rewrite verbatim insertion contract.
          let markers = clip.expectedTextContains ?? []
          try require((2...8).contains(markers.count) && markers.allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
          try require(outcome.rewritten && !normalized(outcome.text).contains(normalized(fixture.trigger)))
          try require(markers.allSatisfy { normalized(outcome.text).contains(normalized($0)) })
          inline += 1
        }
        let entry = HistoryEntry(id: UUID().uuidString, createdAt: Date().timeIntervalSince1970, transcript: outcome.transcript,
          text: outcome.text, rewritten: outcome.successful)
        try library.record(entry, scope: account.historyScope)
        try require(try reopened.history(scope: account.historyScope).entries.contains(entry))
        hosted += 1
      }
      try require(try reopened.history(scope: account.historyScope).entries.count == hosted)
      evidence["hosted_cases"] = hosted; evidence["standalone_cases"] = standalone; evidence["inline_cases"] = inline
      evidence["original_transcript_preserved"] = true
      evidence["inline_rewritten"] = inline > 0; evidence["inline_markers_preserved"] = inline > 0
      evidence["history_persisted"] = true
      var peerIsolated = false
      if let peerID = fixture.peerUserID, let peerToken = fixture.peerToken {
        var peerState = state; peerState.userID = peerID
        defaults.set(try JSONEncoder().encode(peerState), forKey: "clarify.account.metadata")
        let peer = CloudAccount(defaults: defaults, readCredential: { peerToken }, saveCredential: { _ in })
        _ = try await peer.command("sync", value: "", library: library)
        try require(try library.snippets(scope: peer.snippetScope).isEmpty)
        peerIsolated = true
      }
      evidence["peer_isolated"] = peerIsolated; evidence["passed"] = true
    } catch {
      evidence = ["passed": false, "failure": "live_native_acceptance_failed"]
    }
    try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys]).write(to: URL(fileURLWithPath: reportPath), options: .atomic)
    XCTAssertEqual(evidence["passed"] as? Bool, true, "Live native snippets acceptance failed; no private diagnostic data is retained.")
  }
}

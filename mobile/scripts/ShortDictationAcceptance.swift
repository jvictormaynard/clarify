import AVFoundation
import Foundation

private struct Clip: Decodable {
  let filename: String
  let durationMs: Int
}

@main
private struct ShortDictationAcceptance {
  static func main() async throws {
    let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    guard let key = ProcessInfo.processInfo.environment["CLARIFY_ACCEPTANCE_GROQ_KEY"], !key.isEmpty else {
      throw ClarifyError("Missing temporary acceptance credential.")
    }
    let clips = try JSONDecoder().decode([Clip].self, from: Data(contentsOf: root.appendingPathComponent("clips.json")))
    let storage = root.appendingPathComponent("library", isDirectory: true)
    let library = try LocalLibrary(root: storage)
    var entries = ["Clarify", "Maynard", "Python", "React", "Swift", "Expo", "Groq", "Whisper", "GitHub", "SQLite", "TestFlight", "TypeScript"]
      .map { VocabularyEntry(term: $0) }
    entries[0].pronunciation = "clarifai"; entries[0].aliases = ["Clarifai"]
    entries.append(VocabularyEntry(term: "HiddenTerm", enabled: false))
    try library.saveDictionary(entries)
    let client = GroqClient(key: key, vocabulary: try library.dictionary())
    var cases: [[String: Any]] = []
    func isOi(_ text: String) -> Bool {
      text.trimmingCharacters(in: .punctuationCharacters.union(.whitespacesAndNewlines)).lowercased() == "oi"
    }
    for (index, clip) in clips.enumerated() {
      let audio = root.appendingPathComponent(clip.filename)
      let decoded = try AVAudioFile(forReading: audio)
      let actualMs = Int((Double(decoded.length) / decoded.processingFormat.sampleRate * 1000).rounded())
      guard abs(actualMs - clip.durationMs) <= 100, actualMs >= 300 else {
        throw ClarifyError("Unexpected decoded clip duration.")
      }
      let transcript = try await client.transcribe(audio)
      let text = try await client.rewrite(transcript)
      guard isOi(transcript), isOi(text) else { throw ClarifyError("Short speech was not preserved.") }
      try library.record(HistoryEntry(id: "synthetic-oi-\(index)", createdAt: Double(index), transcript: transcript, text: text, rewritten: true))
      guard try library.dictionary() == entries else { throw ClarifyError("Vocabulary changed during dictation.") }
      cases.append(["requested_ms": clip.durationMs, "decoded_ms": actualMs, "transcript": transcript, "text": text])
    }
    let reopened = try LocalLibrary(root: storage)
    guard try reopened.dictionary() == entries, try reopened.history().entries.count == clips.count else {
      throw ClarifyError("Dictionary or history did not survive reopening.")
    }
    let report: [String: Any] = ["cases": cases, "dictionary_unchanged": true,
      "metadata_preserved": true, "history_entries": clips.count, "client": "actual mobile GroqClient", "audio": "synthetic Portuguese M4A"]
    let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
    print(String(decoding: data, as: UTF8.self))
  }
}

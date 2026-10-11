import XCTest
@testable import ClarifyContracts

final class CloudAccountTests: XCTestCase {
  func testEndpointRejectsCredentialBearingURLsAndAllowsLocalSelfHosting() throws {
    for value in ["http://example.com", "https://user:secret@example.com", "https://example.com/path", "https://example.com?token=secret", "file:///tmp/x"] {
      XCTAssertThrowsError(try CloudAccount.validateEndpoint(value))
    }
    XCTAssertEqual(try CloudAccount.validateEndpoint("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")
  }
  func testIndependentEditsMergeAndDeletedWordsStayDeleted() throws {
    let a = VocabularyEntry(term: "A"), b = VocabularyEntry(term: "B")
    let merged = try CloudAccount.merge(base: [a, b], local: [b, VocabularyEntry(term: "Local")],
      remote: [a, b, VocabularyEntry(term: "Remote")])
    XCTAssertEqual(Set(merged.map(\.term)), Set(["B", "Local", "Remote"]))
  }
  func testConcurrentChangeOfSameWordRequiresResolution() {
    XCTAssertThrowsError(try CloudAccount.merge(base: [VocabularyEntry(term: "A")],
      local: [VocabularyEntry(term: "A", pronunciation: "ours")],
      remote: [VocabularyEntry(term: "A", pronunciation: "theirs")]))
  }
  func testAccountDictionariesCannotLeakIntoAnotherAccountOrLocalDictionary() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let library = try LocalLibrary(root: root)
    let a = UUID().uuidString, b = UUID().uuidString
    try library.saveDictionary([VocabularyEntry(term: "Local")])
    try library.saveCloudDictionary(CloudDictionary(entries: [VocabularyEntry(term: "Private A")], base: [], revision: 0), scope: a)
    try library.saveDictionary([VocabularyEntry(term: "Private B")], scope: b)
    XCTAssertEqual(try library.dictionary().map(\.term), ["Local"])
    XCTAssertEqual(try library.dictionary(scope: a).map(\.term), ["Private A"])
    XCTAssertEqual(try library.dictionary(scope: b).map(\.term), ["Private B"])
    try library.deleteCloudDictionary(a)
    XCTAssertTrue(try library.dictionary(scope: a).isEmpty)
    XCTAssertEqual(try library.dictionary(scope: b).map(\.term), ["Private B"])
  }
}

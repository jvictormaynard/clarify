import XCTest
@testable import ClarifyContracts

final class CloudAccountTests: XCTestCase {
  func testExpiredManagedSessionCannotUsePersonalCredentials() throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    var state = CloudAccountState()
    state.hosted = true
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let account = CloudAccount(defaults: defaults)
    XCTAssertTrue(account.managed)
    XCTAssertFalse(account.hosted)
    XCTAssertFalse(account.configured)
  }
  func testFirstAccountCacheImportsGuestWordsOnceWithoutChangingGuestData() throws {
    let suite = "ClarifyTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
    var state = CloudAccountState()
    state.userID = UUID().uuidString
    defaults.set(try JSONEncoder().encode(state), forKey: "clarify.account.metadata")
    let account = CloudAccount(defaults: defaults)
    let library = try LocalLibrary(root: root)
    try library.saveDictionary([VocabularyEntry(term: "Guest")])
    try account.prepareLibrary(library)
    try library.saveDictionary([VocabularyEntry(term: "Account")], scope: account.scope)
    try account.prepareLibrary(library)
    XCTAssertEqual(try library.dictionary().map(\.term), ["Guest"])
    XCTAssertEqual(try library.dictionary(scope: account.scope).map(\.term), ["Account"])
  }
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

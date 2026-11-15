import Foundation

struct RecoveryRecording: Codable {
  enum Status: String, Codable { case saved, failed, complete }
  let id: String
  var createdAt: TimeInterval
  var duration: TimeInterval
  var status: Status
  var historyID: String?
  var useOriginal: Bool?
}

// This app-only archive is independent of account history and the keyboard's
// App Group. Audio stays here until the user explicitly deletes it.
final class AudioRecoveryStore {
  private let root: URL
  private let temporary: URL
  private let files = FileManager.default

  init(root: URL, temporary: URL = FileManager.default.temporaryDirectory) {
    self.root = root; self.temporary = temporary
  }
  static func openDefault() throws -> AudioRecoveryStore {
    let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
      appropriateFor: nil, create: true)
    return AudioRecoveryStore(root: support.appendingPathComponent("ClarifyAudioRecovery", isDirectory: true))
  }
  private func prepare() throws {
    guard (try? root.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) != true else {
      throw CocoaError(.fileReadInvalidFileName)
    }
    try files.createDirectory(at: root, withIntermediateDirectories: true)
    var directory = root
    var values = URLResourceValues(); values.isExcludedFromBackup = true
    try directory.setResourceValues(values)
    #if os(iOS)
    try files.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: root.path)
    #endif
  }
  private func validID(_ id: String) -> Bool { UUID(uuidString: id)?.uuidString == id }
  private func regular(_ url: URL) -> Bool {
    guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]) else { return false }
    return values.isRegularFile == true && values.isSymbolicLink != true && (values.fileSize ?? 0) > 0
  }
  private func identifier(_ url: URL) -> String? {
    guard url.pathExtension == "m4a" else { return nil }
    let stem = url.deletingPathExtension().lastPathComponent
    let id = stem.hasPrefix("clarify-") ? String(stem.dropFirst(8)) : stem
    return validID(id) ? id : nil
  }
  func audioURL(_ id: String) throws -> URL {
    guard validID(id) else { throw CocoaError(.fileReadInvalidFileName) }
    let archived = root.appendingPathComponent("\(id).m4a")
    if (try? root.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) != true, regular(archived) { return archived }
    let remaining = temporary.appendingPathComponent("clarify-\(id).m4a")
    guard regular(remaining) else { throw CocoaError(.fileNoSuchFile) }
    return remaining
  }
  @discardableResult
  func retain(_ url: URL, createdAt: TimeInterval, duration: TimeInterval) throws -> URL {
    guard let id = identifier(url), regular(url) else { throw CocoaError(.fileReadInvalidFileName) }
    try prepare()
    let target = root.appendingPathComponent("\(id).m4a")
    if target.standardizedFileURL != url.standardizedFileURL {
      // A move on the app volume avoids needing a second audio-sized allocation.
      try files.moveItem(at: url, to: target)
    }
    #if os(iOS)
    try? files.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: target.path)
    #endif
    let previous = recordings().first { $0.id == id }
    let row = RecoveryRecording(id: id, createdAt: createdAt, duration: max(0, duration), status: .saved,
      historyID: previous?.historyID, useOriginal: previous?.useOriginal)
    try? JSONEncoder().encode(row).write(to: metadata(id), options: .atomic)
    return target
  }
  func recordings(excluding: URL? = nil) -> [RecoveryRecording] {
    let archived: [URL]
    let redirected = (try? root.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true
    if redirected { archived = [] }
    else { archived = (try? files.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? [] }
    let remaining = ((try? files.contentsOfDirectory(at: temporary, includingPropertiesForKeys: nil)) ?? [])
      .filter { $0.lastPathComponent.hasPrefix("clarify-") }
    var seen = Set<String>()
    return (archived + remaining).compactMap { url -> RecoveryRecording? in
      guard url != excluding, let id = identifier(url), regular(url), seen.insert(id).inserted else { return nil }
      if !redirected, let data = try? Data(contentsOf: metadata(id)), let row = try? JSONDecoder().decode(RecoveryRecording.self, from: data),
         row.id == id, row.createdAt.isFinite, row.duration.isFinite, row.duration >= 0 { return row }
      let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? Date()
      return RecoveryRecording(id: id, createdAt: date.timeIntervalSince1970, duration: 0, status: .saved)
    }.sorted { $0.createdAt > $1.createdAt }
  }
  func mark(_ id: String, status: RecoveryRecording.Status, historyID: String? = nil, useOriginal: Bool? = nil) {
    guard var row = recordings().first(where: { $0.id == id }) else { return }
    row.status = status
    if let historyID { row.historyID = historyID; row.useOriginal = false }
    if let useOriginal { row.useOriginal = useOriginal }
    // Metadata is optional. A failed write must not hide or delete the audio.
    do { try prepare() } catch { return }
    try? JSONEncoder().encode(row).write(to: metadata(id), options: .atomic)
  }
  func showOriginal(_ id: String) throws {
    guard var row = recordings().first(where: { $0.id == id }) else { throw CocoaError(.fileNoSuchFile) }
    row.useOriginal = true
    try prepare()
    try JSONEncoder().encode(row).write(to: metadata(id), options: .atomic)
  }
  func remove(_ id: String) throws {
    try files.removeItem(at: audioURL(id))
    // Do not follow a redirected archive just to remove its optional metadata.
    if (try? root.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) != true {
      try? files.removeItem(at: metadata(id))
    }
  }
  func id(for url: URL) -> String? { identifier(url) }
  private func metadata(_ id: String) -> URL { root.appendingPathComponent("\(id).json") }
}

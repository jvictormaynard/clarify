import Foundation

/// Destination support is explicit. An account or OS version cannot enable it.
enum LocalSpeechPolicy {
  static let maximumPendingBuffers = 25
  static let maximumBufferSeconds = 0.08
  static let maximumRecordingSeconds = 300.0
  static let maximumTranscriptBytes = 32 * 1024

  static func canStart(destinationSupportsLocalSpeech: Bool, deviceAvailable: Bool,
    localeSupported: Bool, assetsInstalled: Bool) -> Bool {
    destinationSupportsLocalSpeech && deviceAvailable && localeSupported && assetsInstalled
  }
}

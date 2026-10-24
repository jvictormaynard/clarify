import AVFoundation

// The session owns this writer under its existing audio-file lock.
final class AudioClipWriter {
  private var file: AVAudioFile?

  init(url: URL, inputFormat: AVAudioFormat) throws {
    do {
      file = try AVAudioFile(forWriting: url, settings: [
        AVFormatIDKey: kAudioFormatMPEG4AAC,
        AVSampleRateKey: inputFormat.sampleRate,
        AVNumberOfChannelsKey: inputFormat.channelCount,
        AVEncoderBitRateKey: 64_000
      ], commonFormat: inputFormat.commonFormat, interleaved: inputFormat.isInterleaved)
    } catch {
      try? FileManager.default.removeItem(at: url)
      throw error
    }
  }
  func write(_ buffer: AVAudioPCMBuffer) throws { try file?.write(from: buffer) }
  func finish() throws { file = nil }
  func cancel() { file = nil }
}

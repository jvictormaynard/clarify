import AVFoundation

// The session owns this writer under its existing audio-file lock.
final class AudioClipWriter {
  enum Failure: Error { case invalidFormat, formatChanged, closed, conversion }
  private let inputFormat: AVAudioFormat
  private let outputFormat: AVAudioFormat
  private let converter: AVAudioConverter
  private var output: AVAudioPCMBuffer?
  private var file: AVAudioFile?

  init(url: URL, inputFormat: AVAudioFormat) throws {
    guard inputFormat.sampleRate.isFinite, (8_000...192_000).contains(inputFormat.sampleRate),
          (1...32).contains(inputFormat.channelCount),
          let outputFormat = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1),
          let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
      throw Failure.invalidFormat
    }
    self.inputFormat = inputFormat; self.outputFormat = outputFormat; self.converter = converter
    do {
      // Hardware rates and channel counts are not necessarily valid AAC settings.
      // Convert once per clip with a persistent converter, then use a known format.
      file = try AVAudioFile(forWriting: url, settings: [
        AVFormatIDKey: kAudioFormatMPEG4AAC,
        AVSampleRateKey: outputFormat.sampleRate,
        AVNumberOfChannelsKey: outputFormat.channelCount,
        AVEncoderBitRateKey: 64_000
      ], commonFormat: outputFormat.commonFormat, interleaved: outputFormat.isInterleaved)
    } catch {
      try? FileManager.default.removeItem(at: url)
      throw error
    }
  }
  func write(_ buffer: AVAudioPCMBuffer) throws {
    guard file != nil else { throw Failure.closed }
    guard buffer.format == inputFormat else { throw Failure.formatChanged }
    guard buffer.frameLength > 0 else { return }
    guard buffer.frameLength <= 65_536 else { throw Failure.invalidFormat }
    let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * outputFormat.sampleRate / inputFormat.sampleRate)) + 64
    if output == nil || output!.frameCapacity < capacity {
      output = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: max(4_096, capacity))
    }
    var supplied = false
    try convert { _, status in
      guard !supplied else { status.pointee = .noDataNow; return nil }
      supplied = true; status.pointee = .haveData; return buffer
    }
  }
  func finish() throws {
    guard file != nil else { return }
    defer { file = nil }
    // End-of-stream drains the resampler's final speech before the AAC file closes.
    if output != nil { try convert { _, status in status.pointee = .endOfStream; return nil } }
  }
  func cancel() { file = nil }

  private func convert(_ input: @escaping AVAudioConverterInputBlock) throws {
    guard let output, let file else { throw Failure.closed }
    while true {
      output.frameLength = 0
      var error: NSError?
      let status = converter.convert(to: output, error: &error, withInputFrom: input)
      if let error { throw error }
      guard status != .error else { throw Failure.conversion }
      if output.frameLength > 0 { try file.write(from: output) }
      if status != .haveData { return }
      guard output.frameLength > 0 else { throw Failure.conversion }
    }
  }
}

#if canImport(AVFoundation)
import AVFoundation

// Called only under AudioSession.fileLock. AVAudioConverter state spans taps.
final class ComputerLivePCMConverter {
  private let converter: AVAudioConverter
  private let output: AVAudioFormat
  private var pending = Data()
  init(format: AVAudioFormat) throws {
    guard let output = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000,
      channels: 1, interleaved: true), let converter = AVAudioConverter(from: format, to: output) else {
      throw ComputerFailure.invalidAudio
    }
    self.output = output; self.converter = converter
  }
  func append(_ input: AVAudioPCMBuffer, to capture: ComputerLiveCapture) throws {
    try convert(input, capture: capture, final: false)
  }
  func finish(to capture: ComputerLiveCapture) throws {
    try convert(nil, capture: capture, final: true)
    if !pending.isEmpty { try capture.append(pending); pending.removeAll() }
    capture.end()
  }
  private func convert(_ input: AVAudioPCMBuffer?, capture: ComputerLiveCapture, final: Bool) throws {
    var supplied = false
    while true {
      guard let buffer = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: 1280) else { throw ComputerFailure.invalidAudio }
      var error: NSError?
      let status = converter.convert(to: buffer, error: &error) { _, state in
        if let input, !supplied { supplied = true; state.pointee = .haveData; return input }
        state.pointee = final ? .endOfStream : .noDataNow; return nil
      }
      if let error { throw error }
      guard status != .error else { throw ComputerFailure.invalidAudio }
      if buffer.frameLength > 0 {
        guard let bytes = buffer.int16ChannelData else { throw ComputerFailure.invalidAudio }
        pending.append(Data(bytes: bytes[0], count: Int(buffer.frameLength) * 2))
        // Coalesce short hardware taps into 80 ms wire frames. Only EOF emits
        // a short tail, so an eight-frame batch covers up to 640 ms of audio.
        while pending.count >= 2560 {
          try capture.append(Data(pending.prefix(2560))); pending.removeFirst(2560)
        }
      }
      if status == .endOfStream || status == .inputRanDry { return }
      if buffer.frameLength == 0 { throw ComputerFailure.invalidAudio }
    }
  }
}
#endif

import AVFoundation

enum ComputerAudio {
  // One detached worker owns this reader. Converter callbacks run within its
  // synchronous convert call; no reader state escapes to another operation.
  private final class FileInput: @unchecked Sendable {
    let source: AVAudioFile
    let buffer: AVAudioPCMBuffer
    private(set) var failure: Error?
    init(source: AVAudioFile, buffer: AVAudioPCMBuffer) { self.source = source; self.buffer = buffer }
    func read(_ requested: AVAudioPacketCount, state: UnsafeMutablePointer<AVAudioConverterInputStatus>) -> AVAudioBuffer? {
      // Reading an AAC file again at EOF can throw instead of returning zero.
      guard source.framePosition < source.length else { state.pointee = .endOfStream; return nil }
      let count = min(requested, buffer.frameCapacity)
      guard count > 0 else { state.pointee = .noDataNow; return nil }
      do {
        try source.read(into: buffer, frameCount: count)
        guard buffer.frameLength > 0 else { state.pointee = .endOfStream; return nil }
        state.pointee = .haveData; return buffer
      } catch { failure = error; state.pointee = .endOfStream; return nil }
    }
  }

  static func convert(_ inputURL: URL) async throws -> Data {
    try Task.checkCancellation()
    let worker = Task.detached(priority: .userInitiated) { () throws -> Data in
      try Task.checkCancellation()
      let source = try AVAudioFile(forReading: inputURL)
      let format = source.processingFormat
      guard format.sampleRate.isFinite, format.sampleRate > 0, source.length > 0,
        Double(source.length) / format.sampleRate <= 301,
        let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true),
        let converter = AVAudioConverter(from: format, to: target),
        let input = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096),
        let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: 4096) else { throw ComputerFailure.invalidAudio }
      let reader = FileInput(source: source, buffer: input)
      var pcm = Data(), stalled = 0
      while true {
        try Task.checkCancellation()
        let previousPosition = source.framePosition
        var error: NSError?
        output.frameLength = 0
        let status = converter.convert(to: output, error: &error) { requested, state in
          reader.read(requested, state: state)
        }
        if error != nil || reader.failure != nil || status == .error { throw ComputerFailure.invalidAudio }
        if output.frameLength > 0 {
          guard let bytes = output.int16ChannelData?[0] else { throw ComputerFailure.invalidAudio }
          // AAC padding and the recorder's 100 ms deadline tick can exceed the
          // capture boundary. The wire payload stops at exactly 300 seconds.
          let count = min(Int(output.frameLength) * 2, ComputerWAV.maximumSamples * 2 - pcm.count)
          pcm.append(contentsOf: UnsafeBufferPointer(start: UnsafeRawPointer(bytes).assumingMemoryBound(to: UInt8.self), count: count))
          if pcm.count == ComputerWAV.maximumSamples * 2 { break }
        }
        if status == .endOfStream { break }
        guard status == .haveData || status == .inputRanDry else { throw ComputerFailure.invalidAudio }
        // Partial output is valid. Allow one empty drain call, but reject a
        // converter that repeatedly makes no input or output progress.
        stalled = output.frameLength > 0 || source.framePosition > previousPosition ? 0 : stalled + 1
        guard stalled <= 1 else { throw ComputerFailure.invalidAudio }
      }
      try Task.checkCancellation()
      // The only WAV file belongs to this conversion. A cancelled or failed
      // upload never leaves a second audio artifact beside the existing clip.
      let wav = try ComputerWAV.wrapPCM16(pcm)
      let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("clarify-computer-\(UUID().uuidString).wav")
      defer { try? FileManager.default.removeItem(at: temporary) }
      try wav.write(to: temporary, options: .atomic)
      try Task.checkCancellation()
      return try Data(contentsOf: temporary)
    }
    return try await withTaskCancellationHandler(operation: { try await worker.value }, onCancel: { worker.cancel() })
  }
}

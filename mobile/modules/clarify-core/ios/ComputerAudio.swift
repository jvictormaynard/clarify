import AVFoundation

enum ComputerAudio {
  static func convert(_ inputURL: URL, diagnostic: (@Sendable (String) -> Void)? = nil) async throws -> Data {
    let worker = Task.detached(priority: .userInitiated) { () throws -> Data in
      try Task.checkCancellation()
      let source = try AVAudioFile(forReading: inputURL)
      let format = source.processingFormat
      diagnostic?("source rate=\(format.sampleRate) channels=\(format.channelCount) length=\(source.length)")
      guard format.sampleRate.isFinite, format.sampleRate > 0, source.length > 0,
        Double(source.length) / format.sampleRate <= 301 else {
        diagnostic?("invalid-source"); throw ComputerFailure.invalidAudio
      }
      guard let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true) else {
        diagnostic?("target-allocation"); throw ComputerFailure.invalidAudio
      }
      guard let converter = AVAudioConverter(from: format, to: target) else {
        diagnostic?("converter-allocation"); throw ComputerFailure.invalidAudio
      }
      guard let input = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096),
        let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: 4096) else {
        diagnostic?("buffer-allocation"); throw ComputerFailure.invalidAudio
      }
      var pcm = Data(), readFailure: Error?
      while true {
        try Task.checkCancellation()
        var error: NSError?
        output.frameLength = 0
        let status = converter.convert(to: output, error: &error) { requested, state in
          diagnostic?("input requested=\(requested) position=\(source.framePosition)")
          do {
            try source.read(into: input)
            if input.frameLength == 0 { state.pointee = .endOfStream; return nil }
            state.pointee = .haveData; return input
          } catch { readFailure = error; state.pointee = .endOfStream; return nil }
        }
        diagnostic?("output status=\(status.rawValue) frames=\(output.frameLength) error=\(error?.code ?? 0) read-failed=\(readFailure != nil)")
        if error != nil || readFailure != nil || status == .error { throw ComputerFailure.invalidAudio }
        if output.frameLength > 0 {
          guard let bytes = output.int16ChannelData?[0] else { diagnostic?("pcm-pointer"); throw ComputerFailure.invalidAudio }
          // AAC padding and the recorder's 100 ms deadline tick can exceed the
          // capture boundary. The wire payload stops at exactly 300 seconds.
          let count = min(Int(output.frameLength) * 2, ComputerWAV.maximumSamples * 2 - pcm.count)
          pcm.append(contentsOf: UnsafeBufferPointer(start: UnsafeRawPointer(bytes).assumingMemoryBound(to: UInt8.self), count: count))
          if pcm.count == ComputerWAV.maximumSamples * 2 { break }
        }
        if status == .endOfStream { break }
        guard status == .haveData, output.frameLength > 0 else { throw ComputerFailure.invalidAudio }
      }
      try Task.checkCancellation()
      // The only WAV file belongs to this conversion. A cancelled or failed
      // upload never leaves a second audio artifact beside the existing clip.
      let wav = try ComputerWAV.wrapPCM16(pcm)
      diagnostic?("wrapped bytes=\(wav.count)")
      let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("clarify-computer-\(UUID().uuidString).wav")
      defer { try? FileManager.default.removeItem(at: temporary) }
      try wav.write(to: temporary, options: .atomic)
      try Task.checkCancellation()
      return try Data(contentsOf: temporary)
    }
    return try await withTaskCancellationHandler(operation: { try await worker.value }, onCancel: { worker.cancel() })
  }
}

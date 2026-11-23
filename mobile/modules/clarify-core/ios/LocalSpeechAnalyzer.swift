#if compiler(>=6.2) && canImport(Speech) && canImport(AVFoundation) && os(iOS)
import AVFoundation
import Speech

/// Optional adapter. It never owns a microphone, recorder, destination, or paste.
/// The native host must supply copied buffers in `format`, at capture speed.
/// No caller enables this until its destination advertises local speech support.
@available(iOS 26.0, *)
@MainActor
final class LocalSpeechAnalyzer {
  enum Failure: Error { case unavailable, assetsMissing, invalidBuffer, overflow, closed, textLimit }
  struct Result { let text: String; let isFinal: Bool }
  let format: AVAudioFormat
  private let analyzer: SpeechAnalyzer
  private let input: AsyncStream<AnalyzerInput>.Continuation
  private var resultTask: Task<Void, Error>?
  private var cancelled = false
  private var finishing = false
  private var seconds = 0.0
  private var committed = ""
  private var terminalError: Error?
  private let onResult: (Result) -> Void

  static func create(locale: Locale, destinationSupportsLocalSpeech: Bool = false,
    onResult: @escaping (Result) -> Void) async throws -> LocalSpeechAnalyzer {
    guard destinationSupportsLocalSpeech, SpeechTranscriber.isAvailable,
      let supported = await SpeechTranscriber.supportedLocale(equivalentTo: locale)
    else { throw Failure.unavailable }
    let installed = await SpeechTranscriber.installedLocales
    guard installed.contains(supported) else { throw Failure.assetsMissing }
    let transcriber = SpeechTranscriber(locale: supported, transcriptionOptions: [],
      reportingOptions: [.volatileResults], attributeOptions: [])
    guard await AssetInventory.status(forModules: [transcriber]) == .installed,
      let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber])
    else { throw Failure.assetsMissing }
    let pair = AsyncStream<AnalyzerInput>.makeStream(
      bufferingPolicy: .bufferingOldest(LocalSpeechPolicy.maximumPendingBuffers))
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    let owner = LocalSpeechAnalyzer(format: format, analyzer: analyzer,
      input: pair.continuation, onResult: onResult)
    owner.resultTask = Task { [weak owner] in
      do {
        for try await result in transcriber.results {
          guard let owner, !owner.cancelled else { return }
          let phrase = String(result.text.characters)
          let text = owner.committed + phrase
          guard text.utf8.count <= LocalSpeechPolicy.maximumTranscriptBytes else { throw Failure.textLimit }
          if result.isFinal { owner.committed = text }
          // A final phrase is not a final recording. Only finish() returns that.
          owner.onResult(Result(text: text, isFinal: false))
        }
      } catch {
        owner?.terminalError = error
        owner?.input.finish()
        await analyzer.cancelAndFinishNow()
        throw error
      }
    }
    do {
      try await analyzer.prepareToAnalyze(in: format)
      try await analyzer.start(inputSequence: pair.stream)
      return owner
    } catch {
      await owner.cancel()
      throw error
    }
  }

  private init(format: AVAudioFormat, analyzer: SpeechAnalyzer,
    input: AsyncStream<AnalyzerInput>.Continuation, onResult: @escaping (Result) -> Void) {
    self.format = format; self.analyzer = analyzer; self.input = input; self.onResult = onResult
  }

  /// The recorder owns conversion. Never queue tasks from the audio tap here.
  func feed(_ buffer: AVAudioPCMBuffer) async throws {
    guard !cancelled, !finishing else { throw Failure.closed }
    if let terminalError { throw terminalError }
    let duration = Double(buffer.frameLength) / buffer.format.sampleRate
    guard buffer.format == format, buffer.frameLength > 0,
      duration <= LocalSpeechPolicy.maximumBufferSeconds,
      seconds + duration <= LocalSpeechPolicy.maximumRecordingSeconds,
      let copy = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: buffer.frameLength)
    else { throw Failure.invalidBuffer }
    copy.frameLength = buffer.frameLength
    let source = UnsafeMutableAudioBufferListPointer(buffer.mutableAudioBufferList)
    let target = UnsafeMutableAudioBufferListPointer(copy.mutableAudioBufferList)
    for index in source.indices {
      guard let src = source[index].mData, let dst = target[index].mData else { throw Failure.invalidBuffer }
      memcpy(dst, src, Int(source[index].mDataByteSize))
    }
    seconds += duration
    switch input.yield(AnalyzerInput(buffer: copy)) {
    case .enqueued: return
    case .dropped:
      await cancel(); throw Failure.overflow
    case .terminated:
      throw Failure.closed
    @unknown default:
      await cancel(); throw Failure.closed
    }
  }

  func finish() async throws -> String {
    guard !cancelled, !finishing else { throw Failure.closed }
    finishing = true
    let timeout = Task { [weak self] in
      do { try await Task.sleep(for: .seconds(30)) } catch { return }
      await self?.cancel()
    }
    defer { timeout.cancel() }
    input.finish()
    do {
      try await analyzer.finalizeAndFinishThroughEndOfInput()
      try await resultTask?.value
      guard !cancelled else { throw CancellationError() }
      if let terminalError { throw terminalError }
      onResult(Result(text: committed, isFinal: true))
      return committed
    } catch {
      await cancel()
      throw error
    }
  }

  deinit {
    input.finish()
    resultTask?.cancel()
    let analyzer = analyzer
    Task { await analyzer.cancelAndFinishNow() }
  }

  func cancel() async {
    cancelled = true
    input.finish()
    resultTask?.cancel()
    await analyzer.cancelAndFinishNow()
  }
}
#endif

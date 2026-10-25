import AVFoundation
import UIKit

// All control and publication run on the main queue. The audio tap owns only
// writing buffers under fileLock. No audio is saved between dictated clips.
final class ClarifyAudioSession: NSObject {
  static let shared = ClarifyAudioSession()
  private var engine = AVAudioEngine()
  private let fileLock = NSLock()
  private var file: AVAudioFile?
  private var captureAfter: TimeInterval = 0
  private var cuePlayer: AVAudioPlayer?
  private let feedback = HapticFeedback()
  private let liveActivity = ClarifyLiveActivity()
  private var audioURL: URL?
  private var store: SharedState?
  private var timer: Timer?
  private var task: Task<Void, Never>?
  private var startedAt: Date?
  private var hasTap = false
  private var backgroundTask = UIBackgroundTaskIdentifier.invalid
  private lazy var libraryResult = Result { try LocalLibrary.openDefault() }
  private var clipHistory = CloudAccount.shared.captureHistory()
  private(set) var state = DictationSnapshot()

  func library() throws -> LocalLibrary { try libraryResult.get() }
  func libraryChanged() { state.libraryRevision += 1; try? importKeyboardVocabulary(); publish() }
  func syncHistory(force: Bool = false) {
    Task { @MainActor [weak self] in
      guard let self, let library = try? self.library() else { return }
      if await CloudAccount.shared.syncHistory(library, force: force) { self.libraryChanged() }
    }
  }
  func importKeyboardVocabulary() throws {
    guard let store, !state.phase.busy, !CloudAccount.shared.isBusy else { return }
    let account = CloudAccount.shared
    let library = try library()
    guard account.configured, let scope = account.scope else {
      // Preserve words queued by the former guest keyboard before an upgrade.
      // This only imports into local storage; it never enables guest dictation.
      if !account.managed, try library.importKeyboardAdditions(store, scope: nil) {
        state.libraryRevision += 1
      }
      try store.publishKeyboardDictionary(nil); return
    }
    try account.prepareLibrary(library)
    if try library.importKeyboardAdditions(store, scope: scope) {
      state.libraryRevision += 1
      account.dictionaryChanged()
    }
    let words = try library.dictionary(scope: scope).map { KeyboardDictionaryWord(term: $0.term, enabled: $0.enabled) }
    try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: scope, words: words))
  }

  private override init() {
    super.init()
    CloudAccount.shared.setSessionInvalidationHandler { [weak self] in self?.accountSessionInvalidated() }
    // Remove only this app's clips left by an interrupted or terminated process.
    let temporary = FileManager.default.temporaryDirectory
    for url in (try? FileManager.default.contentsOfDirectory(at: temporary, includingPropertiesForKeys: nil)) ?? [] {
      if url.lastPathComponent.hasPrefix("clarify-"), url.pathExtension == "m4a" {
        try? FileManager.default.removeItem(at: url)
      }
    }
    store = SharedState()
    try? importKeyboardVocabulary()
    state.configured = CloudAccount.shared.configured
    publish()
    CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
      Unmanaged.passUnretained(self).toOpaque(), { _, observer, _, _, _ in
        guard let observer = observer else { return }
        let owner = Unmanaged<ClarifyAudioSession>.fromOpaque(observer).takeUnretainedValue()
        DispatchQueue.main.async { try? owner.importKeyboardVocabulary(); owner.tick() }
      }, "com.clarify.keyboard.command" as CFString, nil, .deliverImmediately)
    NotificationCenter.default.addObserver(self, selector: #selector(interrupted),
      name: AVAudioSession.interruptionNotification, object: nil)
    NotificationCenter.default.addObserver(self, selector: #selector(routeChanged),
      name: AVAudioSession.routeChangeNotification, object: nil)
    NotificationCenter.default.addObserver(self, selector: #selector(mediaReset),
      name: AVAudioSession.mediaServicesWereResetNotification, object: nil)
  }
  func publish() {
    state.heartbeat = Date().timeIntervalSince1970
    state.configured = CloudAccount.shared.configured
    try? store?.write(state, to: "state.json")
    liveActivity.update(state)
  }
  func activate() throws {
    guard !CloudAccount.shared.isBusy else { throw ClarifyError(L("Aguarde a operação da conta.")) }
    guard store != nil else { throw ClarifyError(L("Não foi possível acessar os dados do teclado.")) }
    guard CloudAccount.shared.configured else { throw ClarifyError(L("Entre na sua conta primeiro.")) }
    if engine.isRunning { publish(); return }
    let session = AVAudioSession.sharedInstance()
    do {
      try session.setCategory(.playAndRecord, mode: .default,
        options: [.mixWithOthers, .defaultToSpeaker, .allowBluetooth])
      // Configure this before activation; otherwise recording can suppress haptics.
      try session.setAllowHapticsAndSystemSoundsDuringRecording(true)
      try session.setActive(true)
      feedback.prepare()
      let input = engine.inputNode
      let format = input.outputFormat(forBus: 0)
      guard format.sampleRate > 0, format.channelCount > 0 else {
        throw ClarifyError(L("O microfone está indisponível."))
      }
      if hasTap { input.removeTap(onBus: 0) }
      input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
        guard let self = self else { return }
        self.fileLock.lock()
        defer { self.fileLock.unlock() }
        let bufferDuration = Double(buffer.frameLength) / buffer.format.sampleRate
        if let file = self.file, Date().timeIntervalSince1970 - bufferDuration >= self.captureAfter {
          do { try file.write(from: buffer) }
          catch {
            let failedURL = self.audioURL
            DispatchQueue.main.async {
              if let failedURL = failedURL, self.audioURL == failedURL {
                self.fail(L("Não foi possível gravar o áudio."))
              }
            }
          }
        }
      }
      hasTap = true
      engine.prepare(); try engine.start()
      state.sessionActive = true
      if state.phase == .error { state.phase = .idle; state.message = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil }
      timer?.invalidate()
      timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.tick() }
      publish()
    } catch {
      // Category, session activation and engine startup all need the same rollback.
      // A call can reject setActive before a tap or engine has been started.
      stopAudio()
      engine = AVAudioEngine()
      let message = MicrophoneFailure.message(for: error)
      fail(message)
      throw ClarifyError(message)
    }
  }
  func deactivate() {
    cancel()
    stopAudio()
    publish()
  }
  func accountSessionInvalidated() {
    stopAudio()
    fail(L("Entre na conta novamente."), diagnostics: ClarifyError(L("Entre na conta novamente."), code: "authentication_required"))
    try? store?.publishKeyboardDictionary(nil)
  }
  private func stopAudio() {
    engine.stop()
    if hasTap { engine.inputNode.removeTap(onBus: 0); hasTap = false }
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    timer?.invalidate(); timer = nil
    state.sessionActive = false
  }
  private func tick() {
    for (url, command) in store?.commands() ?? [] {
      try? FileManager.default.removeItem(at: url)
      if Date().timeIntervalSince1970 - command.createdAt < 5 {
        // The visible keyboard owns feedback for keyboard-originated commands.
        handle(command.action, id: command.operationID, haptics: false)
      }
    }
    if SessionDeadline.action(startedAt: startedAt, phase: state.phase, now: Date()) == .finishRecording {
      finish()
    }
    // Refresh liveness once per second, without disk writes on every audio buffer.
    if Date().timeIntervalSince1970 - state.heartbeat >= 1 { try? importKeyboardVocabulary(); publish() }
  }
  func handle(_ action: String, id: String, haptics: Bool = true) {
    switch action {
    case "start", "lock":
      if action == "lock", state.operationID == id, state.phase == .recording {
        if haptics, UIApplication.shared.applicationState == .active { feedback.record("lock") }
        state.phase = .locked; publish(); return
      }
      guard !state.phase.busy else { return }
      guard state.sessionActive, engine.isRunning else {
        deactivate(); fail(L("Abra o Clarify e ative o microfone.")); return
      }
      do { try start(id: id, locked: action == "lock", haptics: haptics) }
      catch { fail(error.localizedDescription) }
    case "finish":
      if state.operationID == id { finish(haptics: haptics) }
    case "cancel":
      if state.operationID == id { cancel() }
    default: break
    }
  }
  private func start(id: String, locked: Bool, haptics: Bool) throws {
    guard CloudAccount.shared.configured else { throw ClarifyError(L("Entre na sua conta primeiro.")) }
    guard !CloudAccount.shared.isBusy else { throw ClarifyError(L("Aguarde a operação da conta.")) }
    try? importKeyboardVocabulary()
    clipHistory = CloudAccount.shared.captureHistory()
    let format = engine.inputNode.outputFormat(forBus: 0)
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("clarify-\(UUID().uuidString).m4a")
    let newFile = try AVAudioFile(forWriting: url, settings: [
      AVFormatIDKey: kAudioFormatMPEG4AAC,
      AVSampleRateKey: format.sampleRate,
      AVNumberOfChannelsKey: format.channelCount,
      AVEncoderBitRateKey: 64_000
    ], commonFormat: format.commonFormat, interleaved: format.isInterleaved)
    playCue(starting: true)
    if haptics, UIApplication.shared.applicationState == .active {
      feedback.record("start")
    }
    // The engine discards the short start cue so it is not sent for transcription.
    let captureStart = Date().addingTimeInterval(0.12)
    fileLock.lock(); file = newFile; audioURL = url; captureAfter = captureStart.timeIntervalSince1970; fileLock.unlock()
    startedAt = captureStart
    state.operationID = id
    state.phase = locked ? .locked : .recording
    state.text = nil; state.message = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil
    publish()
  }
  private func closeFile() -> URL? {
    fileLock.lock(); defer { fileLock.unlock() }
    file = nil
    let url = audioURL; audioURL = nil
    return url
  }
  private func finish(haptics: Bool = true) {
    guard [.recording, .locked].contains(state.phase), let id = state.operationID else { return }
    let duration = startedAt.map { Date().timeIntervalSince($0) } ?? 0
    let recordedAt = startedAt?.timeIntervalSince1970 ?? Date().timeIntervalSince1970
    let historyOwner = clipHistory
    startedAt = nil
    guard let url = closeFile() else { fail(L("Não foi possível ler a gravação.")); return }
    playCue(starting: false)
    if haptics, UIApplication.shared.applicationState == .active { feedback.record("finish") }
    guard duration >= 0.3 else {
      try? FileManager.default.removeItem(at: url)
      fail(L("Segure o botão e fale por mais tempo.")); return
    }
    guard CloudAccount.shared.acceptsHistory(historyOwner) else {
      try? FileManager.default.removeItem(at: url); fail(L("Entre na conta novamente.")); return
    }
    guard CloudAccount.shared.configured else {
      try? FileManager.default.removeItem(at: url)
      fail(L("Entre na conta novamente.")); return
    }
    state.phase = .transcribing; publish()
    backgroundTask = UIApplication.shared.beginBackgroundTask(withName: "Clarify transcription") { [weak self] in
      self?.cancel()
    }
    let backgroundID = backgroundTask
    task = Task { @MainActor [weak self] in
      guard let self = self else { return }
      defer {
        try? FileManager.default.removeItem(at: url)
        self.endBackgroundTask(backgroundID)
      }
      do {
        let outcome = try await CloudAccount.shared.dictate(url, operationID: id, library: self.library())
        guard !Task.isCancelled, self.state.operationID == id, CloudAccount.shared.acceptsHistory(historyOwner) else { return }
        let transcript = outcome.transcript
        self.state.text = outcome.text
        self.state.phase = outcome.successful ? .ready : .error
        if !outcome.successful { self.state.message = L("A reescrita falhou. Você pode inserir a transcrição original.") }
        // Save only the terminal result of this still-current operation. The
        // original remains available when rewriting fails; audio is never kept.
        guard !Task.isCancelled, self.state.operationID == id, CloudAccount.shared.acceptsHistory(historyOwner) else { return }
        do {
          try self.library().record(HistoryEntry(id: id, createdAt: recordedAt,
            transcript: transcript, text: self.state.text ?? transcript, rewritten: self.state.phase == .ready), scope: historyOwner.scope)
          self.state.libraryRevision += 1
          self.syncHistory(force: true)
        } catch {
          self.state.message = L("O texto foi preservado, mas não foi possível salvar o histórico.")
        }
        self.publish()
      } catch {
        guard !Task.isCancelled, self.state.operationID == id else { return }
        // The account boundary cancels stale responses without marking this
        // Task cancelled. End only this still-current clip, not a new recording.
        if error is CancellationError { self.cancel(); return }
        self.fail(error is ClarifyError ? error.localizedDescription : L("Falha de conexão. Verifique a internet e tente novamente."), diagnostics: error as? ClarifyError)
      }
    }
  }
  private func endBackgroundTask(_ expected: UIBackgroundTaskIdentifier? = nil) {
    if let expected = expected, expected != backgroundTask { return }
    if backgroundTask != .invalid { UIApplication.shared.endBackgroundTask(backgroundTask); backgroundTask = .invalid }
  }
  func cancel() {
    cuePlayer?.stop(); cuePlayer = nil
    task?.cancel(); task = nil; startedAt = nil
    if let url = closeFile() { try? FileManager.default.removeItem(at: url) }
    if state.phase.busy {
      state.operationID = nil; state.phase = .idle; state.text = nil; state.message = nil
      state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil
    }
    endBackgroundTask()
    publish()
  }
  private func fail(_ message: String, diagnostics: ClarifyError? = nil) {
    if !CloudAccount.shared.configured, state.sessionActive { stopAudio() }
    cuePlayer?.stop(); cuePlayer = nil
    task?.cancel(); task = nil; startedAt = nil
    if let url = closeFile() { try? FileManager.default.removeItem(at: url) }
    endBackgroundTask()
    state.phase = .error; state.message = message
    state.errorCode = diagnostics?.code; state.errorPhase = diagnostics?.phase; state.errorStatus = diagnostics?.status
    publish()
  }
  private func playCue(starting: Bool) {
    // Original 90 ms cue, with a soft envelope. No WhatsApp audio is bundled.
    let rate = 24_000
    let samples = 2_160
    var wav = Data()
    func ascii(_ value: String) { wav.append(Data(value.utf8)) }
    func integer<T: FixedWidthInteger>(_ value: T) {
      var little = value.littleEndian
      withUnsafeBytes(of: &little) { wav.append(contentsOf: $0) }
    }
    ascii("RIFF"); integer(UInt32(36 + samples * 2)); ascii("WAVEfmt ")
    integer(UInt32(16)); integer(UInt16(1)); integer(UInt16(1))
    integer(UInt32(rate)); integer(UInt32(rate * 2)); integer(UInt16(2)); integer(UInt16(16))
    ascii("data"); integer(UInt32(samples * 2))
    var phase = 0.0
    for index in 0..<samples {
      let progress = Double(index) / Double(samples - 1)
      let frequency = starting ? 840 + 360 * progress : 1_040 - 300 * progress
      phase += 2 * .pi * frequency / Double(rate)
      let envelope = pow(sin(.pi * progress), 2)
      integer(Int16(sin(phase) * envelope * 3_800))
    }
    cuePlayer = try? AVAudioPlayer(data: wav)
    cuePlayer?.volume = 0.5; cuePlayer?.prepareToPlay(); cuePlayer?.play()
  }
  @objc private func interrupted(_ notification: Notification) {
    guard let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
          AVAudioSession.InterruptionType(rawValue: raw) == .began else { return }
    DispatchQueue.main.async { self.deactivate(); self.fail(L("O áudio foi interrompido. Abra o Clarify para reativar o microfone.")) }
  }
  @objc private func routeChanged(_ notification: Notification) {
    guard let raw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
          let reason = AVAudioSession.RouteChangeReason(rawValue: raw),
          [.oldDeviceUnavailable, .newDeviceAvailable].contains(reason) else { return }
    DispatchQueue.main.async {
      if self.state.sessionActive { self.deactivate(); self.fail(L("O dispositivo de áudio mudou. Ative o microfone novamente.")) }
    }
  }
  @objc private func mediaReset() {
    DispatchQueue.main.async {
      self.deactivate(); self.engine = AVAudioEngine()
      self.fail(L("O áudio foi reiniciado pelo iOS. Ative o microfone novamente."))
    }
  }
}

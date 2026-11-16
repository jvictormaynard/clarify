import AVFoundation
import UIKit

// All control and publication run on the main queue. The audio tap owns only
// writing buffers under fileLock. Stopped clips have a separate app-only recovery owner.
final class ClarifyAudioSession: NSObject, AVAudioPlayerDelegate {
  static let shared = ClarifyAudioSession()
  private var engine = AVAudioEngine()
  private let fileLock = NSLock()
  private var file: AudioClipWriter?
  private var liveCapture: ComputerLiveCapture?
  private var liveConverter: ComputerLivePCMConverter?
  private var liveOperationID: String?
  private var captureAfter: TimeInterval = 0
  private var meteredOperationID: String?
  private var meteredAt: TimeInterval = 0
  private var meteredLevel = 0.0
  private var cancellations = RecordingCancellations()
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
  private lazy var recoveryResult = Result { try AudioRecoveryStore.openDefault() }
  private var processingRecordings = Set<String>()
  private var sharedRecordings = Set<String>()
  private var keyboardRetry: (operationID: String, url: URL, context: String)?
  private var recoveryPlayer: AVAudioPlayer?
  private var recoveryPlayerID: String?
  private var clipPolicy = DictationPolicy.legacy
  private var clipPreferences = OutputPreferences()
  private var clipHistory = ProcessingDestination.shared.captureHistory()
  private(set) var state = DictationSnapshot()

  func library() throws -> LocalLibrary { try libraryResult.get() }
  func libraryChanged() { state.libraryRevision += 1; try? importKeyboardVocabulary(); publish() }
  func syncHistory(force: Bool = false) {
    Task { @MainActor [weak self] in
      guard let self, !ProcessingDestination.shared.computerMode, let library = try? self.library() else { return }
      if await ProcessingDestination.shared.syncHistory(library, force: force) { self.libraryChanged() }
    }
  }
  func importKeyboardVocabulary() throws {
    guard let store, !state.phase.busy, !ProcessingDestination.shared.isBusy else { return }
    if ProcessingDestination.shared.computerMode { try store.publishKeyboardDictionary(nil); return }
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
    CloudAccount.shared.setSessionInvalidationHandler { [weak self] in
      if !ProcessingDestination.shared.computerMode { self?.accountSessionInvalidated() }
    }
    ComputerConnection.shared.setInvalidationHandler { [weak self] in
      guard ProcessingDestination.shared.computerMode else { return }
      self?.destinationChanged()
      self?.fail(ComputerFailure.authentication.localizedDescription)
    }
    // Converted request WAVs are disposable. Keep source AAC clips for recovery.
    let temporary = FileManager.default.temporaryDirectory
    for url in (try? FileManager.default.contentsOfDirectory(at: temporary, includingPropertiesForKeys: nil)) ?? [] {
      if url.lastPathComponent.hasPrefix("clarify-"), url.pathExtension == "wav" {
        try? FileManager.default.removeItem(at: url)
      }
    }
    store = SharedState()
    try? importKeyboardVocabulary()
    state.computerMode = ProcessingDestination.shared.computerMode
    state.configured = ProcessingDestination.shared.configured
    state.textActions = ProcessingDestination.shared.textActions
    state.legacyRewriteReady = ProcessingDestination.shared.legacyRewriteReady
    state.legacyTranslateReady = ProcessingDestination.shared.legacyTranslateReady
    state.outputPreferencesSupported = ProcessingDestination.shared.outputPreferencesSupported
    publish()
    CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
      Unmanaged.passUnretained(self).toOpaque(), { _, observer, _, _, _ in
        guard let observer = observer else { return }
        let owner = Unmanaged<ClarifyAudioSession>.fromOpaque(observer).takeUnretainedValue()
        DispatchQueue.main.async { try? owner.importKeyboardVocabulary(); owner.tick() }
      }, "com.clarify.keyboard.command" as CFString, nil, .deliverImmediately)
    #if CLARIFY_APP_FLOW_TESTING
    // Enabled only by the isolated simulator harness. Test deactivation without
    // starting audio or exposing a production command or JavaScript test API.
    CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
      Unmanaged.passUnretained(self).toOpaque(), { _, observer, _, _, _ in
        guard let observer else { return }
        let owner = Unmanaged<ClarifyAudioSession>.fromOpaque(observer).takeUnretainedValue()
        DispatchQueue.main.async { owner.deactivate() }
      }, "com.clarify.app-flow.deactivate" as CFString, nil, .deliverImmediately)
    #endif
    NotificationCenter.default.addObserver(self, selector: #selector(interrupted),
      name: AVAudioSession.interruptionNotification, object: nil)
    NotificationCenter.default.addObserver(self, selector: #selector(routeChanged),
      name: AVAudioSession.routeChangeNotification, object: nil)
    NotificationCenter.default.addObserver(self, selector: #selector(mediaReset),
      name: AVAudioSession.mediaServicesWereResetNotification, object: nil)
  }
  func publish() {
    state.heartbeat = Date().timeIntervalSince1970
    state.processingContext = ProcessingDestination.shared.historyContext
    state.computerMode = ProcessingDestination.shared.computerMode
    state.configured = ProcessingDestination.shared.configured
    state.retryAvailable = state.phase == .error && !state.textOperation &&
      keyboardRetry?.operationID == state.operationID && keyboardRetry?.context == state.processingContext &&
      keyboardRetry.map { FileManager.default.fileExists(atPath: $0.url.path) } == true
    state.textActions = ProcessingDestination.shared.textActions
    state.legacyRewriteReady = ProcessingDestination.shared.legacyRewriteReady
    state.legacyTranslateReady = ProcessingDestination.shared.legacyTranslateReady
    state.outputPreferencesSupported = ProcessingDestination.shared.outputPreferencesSupported
    let destination = ProcessingDestination.shared
    let policy = DictationPolicyStore().read(scope: destination.historyScope ?? "")
    state.dictationMode = policy.mode.rawValue
    state.dictationActionID = policy.actionID
    state.dictationModes = DictationPolicy.selectableModes(capabilities: destination.processingCapabilities)
    state.toneAllowed = destination.configured && destination.outputPreferencesSupported &&
      policy.canApplyTone(capabilities: destination.processingCapabilities, catalog: destination.textActions, computer: destination.computerMode,
        outputLanguage: store?.outputPreferences().language ?? .auto)
    try? store?.write(state, to: "state.json")
    liveActivity.update(state)
    publishMeter()
  }
  func activate() throws {
    guard !ProcessingDestination.shared.isBusy else { throw ClarifyError(L("Aguarde a operação da conta.")) }
    guard store != nil else { throw ClarifyError(L("Não foi possível acessar os dados do teclado.")) }
    guard ProcessingDestination.shared.configured else { throw ClarifyError(L("Entre na sua conta primeiro.")) }
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
        let observedAt = Date().timeIntervalSince1970
        self.fileLock.lock()
        defer { self.fileLock.unlock() }
        let bufferDuration = Double(buffer.frameLength) / buffer.format.sampleRate
        if let file = self.file, observedAt - bufferDuration >= self.captureAfter {
          self.meteredLevel = 0
          if let channels = buffer.floatChannelData {
            let planes = buffer.format.isInterleaved ? 1 : Int(buffer.format.channelCount)
            let count = Int(buffer.frameLength) * (buffer.format.isInterleaved ? Int(buffer.format.channelCount) : 1)
            for channel in 0..<planes {
              self.meteredLevel = max(self.meteredLevel, AudioLevel.measure(UnsafeBufferPointer(start: channels[channel], count: count)))
            }
          }
          self.meteredAt = observedAt
          do {
            try file.write(buffer)
            if let capture = self.liveCapture { try self.liveConverter?.append(buffer, to: capture) }
          }
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
      if state.phase == .error { state.phase = .idle; state.message = nil; state.errorRecovery = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil }
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
    // The input route is no longer needed after finalization. A call or a
    // headset change must not cancel the upload of an already stopped clip.
    if state.phase == .transcribing && !state.textOperation {
      stopAudio(); publish(); return
    }
    cancel(preserveCapture: true)
    stopAudio()
    publish()
  }
  func accountSessionInvalidated() {
    clearResult()
    stopAudio()
    fail(L("Entre na conta novamente."), diagnostics: ClarifyError(L("Entre na conta novamente."), code: "authentication_required"))
    try? store?.publishKeyboardDictionary(nil)
  }
  private func stopAudio() {
    stopRecoveryPlayback(publish: false)
    engine.stop()
    if hasTap { engine.inputNode.removeTap(onBus: 0); hasTap = false }
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    timer?.invalidate(); timer = nil
    state.sessionActive = false
  }
  private func publishMeter() {
    let now = Date().timeIntervalSince1970
    guard state.sessionActive, [.recording, .locked].contains(state.phase), let id = state.operationID else {
      try? store?.publishAudioMeter(.inactive(now: now)); return
    }
    fileLock.lock()
    let reading = AudioMeterReading(operationID: meteredOperationID, measuredAt: meteredAt, level: meteredLevel)
    fileLock.unlock()
    try? store?.publishAudioMeter(AudioMeterReading(operationID: id, measuredAt: now, level: reading.level(for: id, now: now)))
  }
  private func tick() {
    for (url, command) in store?.commands() ?? [] {
      try? FileManager.default.removeItem(at: url)
      let age = Date().timeIntervalSince1970 - command.createdAt
      if age >= 0, age < 5, command.context == ProcessingDestination.shared.historyContext {
        // The visible keyboard owns feedback for keyboard-originated commands.
        if command.action == "dictation_policy" {
          guard !state.phase.busy else { continue }
          do {
            guard !state.phase.busy, let mode = command.text.flatMap(DictationMode.init(rawValue:)),
              let scope = ProcessingDestination.shared.historyScope else { throw ComputerFailure.notReady }
            let policy = DictationPolicy(mode: mode, actionID: command.actionID ?? "",
              actionRevision: command.actionRevision ?? "", language: OutputLanguage(rawValue: command.language ?? "auto") ?? .auto)
            _ = try ProcessingDestination.shared.dictationFields(policy)
            try DictationPolicyStore().save(policy, scope: scope)
            publish()
          } catch { fail(error.localizedDescription, diagnostics: error as? ClarifyError) }
        } else if let text = command.text, let language = command.language {
          let context = command.context ?? ""
          Task { @MainActor in
            do {
              _ = try await self.startText(command.action, id: command.operationID, text: text, language: language,
                context: context, actionID: command.actionID, revision: command.actionRevision, preferences: command.outputPreferences)
            } catch {
              guard !(error is CancellationError), !self.state.phase.busy,
                context == ProcessingDestination.shared.historyContext, self.store?.isCancelled(command.operationID) != true else { return }
              self.state.operationID = command.operationID; self.state.textOperation = true; self.state.text = nil
              self.fail(error.localizedDescription, diagnostics: error as? ClarifyError)
            }
          }
        } else { handle(command.action, id: command.operationID, haptics: false, preferences: command.outputPreferences, retryOfOperationID: command.retryOfOperationID) }
      }
    }
    if SessionDeadline.action(startedAt: startedAt, phase: state.phase, now: Date()) == .finishRecording {
      finish()
    }
    if [.recording, .locked].contains(state.phase) { publishMeter() }
    // Refresh liveness once per second, without disk writes on every audio buffer.
    if Date().timeIntervalSince1970 - state.heartbeat >= 1 { try? importKeyboardVocabulary(); publish() }
  }
  func handle(_ action: String, id: String, haptics: Bool = true, preferences: OutputPreferences? = nil, retryOfOperationID: String? = nil) {
    switch action {
    case "start", "lock":
      if action == "lock", state.operationID == id, state.phase == .recording {
        if haptics, UIApplication.shared.applicationState == .active { feedback.record("lock") }
        state.phase = .locked; publish(); return
      }
      guard !state.phase.busy, cancellations.acceptsStart(id, now: Date().timeIntervalSince1970), store?.isCancelled(id) != true else { return }
      guard state.sessionActive, engine.isRunning else {
        deactivate(); fail(L("Abra o Clarify e ative o microfone.")); return
      }
      do { try start(id: id, locked: action == "lock", haptics: haptics, preferences: preferences) }
      catch {
        state.operationID = id; state.textOperation = false; state.text = nil
        if error is ComputerFailure || error is ClarifyError { fail(error.localizedDescription, diagnostics: error as? ClarifyError); return }
        let failure = MicrophoneFailure.recordingError(for: error)
        fail(failure.localizedDescription, diagnostics: failure)
      }
    case "retry":
      guard state.canRetryRecording, let previous = keyboardRetry,
        previous.operationID == retryOfOperationID, state.operationID == retryOfOperationID,
        previous.context == ProcessingDestination.shared.historyContext,
        UUID(uuidString: id) != nil, id != previous.operationID,
        cancellations.acceptsStart(id, now: Date().timeIntervalSince1970), store?.isCancelled(id) != true else { return }
      do { try reprocessAudio(previous.url, id: id, preferences: preferences) }
      catch {
        // A rejected preparation still acknowledges this new retry operation.
        state.operationID = id; keyboardRetry = (id, previous.url, previous.context)
        fail(error.localizedDescription, diagnostics: error as? ClarifyError)
      }
    case "finish":
      if state.operationID == id { finish(haptics: haptics) }
    case "cancel":
      cancellations.cancel(id, now: Date().timeIntervalSince1970)
      if state.operationID == id { cancel() } else { publish() }
    default: break
    }
  }
  private func prepareDictation(preferences: OutputPreferences? = nil) throws {
    if ProcessingDestination.shared.computerMode, ComputerConnection.shared.busy { throw ComputerFailure.busy }
    guard ProcessingDestination.shared.configured else { throw ClarifyError(L("Entre na sua conta primeiro.")) }
    guard !ProcessingDestination.shared.isBusy else { throw ClarifyError(L("Aguarde a operação da conta.")) }
    if ProcessingDestination.shared.computerMode, !ComputerConnection.shared.isReady(for: "dictate") {
      throw ComputerConnection.shared.status == "offline" ? ComputerFailure.offline : ComputerFailure.notReady
    }
    let policy = DictationPolicyStore().read(scope: ProcessingDestination.shared.historyScope ?? "")
    let savedPreferences = preferences ?? store?.outputPreferences() ?? OutputPreferences()
    let frozenPreferences = policy.frozenPreferences(savedPreferences, capabilities: ProcessingDestination.shared.processingCapabilities,
      catalog: ProcessingDestination.shared.textActions, computer: ProcessingDestination.shared.computerMode)
    _ = try frozenPreferences.requestFields(supported: ProcessingDestination.shared.outputPreferencesSupported, dictation: true)
    _ = try ProcessingDestination.shared.dictationFields(policy)
    try ProcessingDestination.shared.processingCapabilities.validate(frozenPreferences)
    clipPolicy = policy
    clipPreferences = frozenPreferences
    try? importKeyboardVocabulary()
    clipHistory = ProcessingDestination.shared.captureHistory()
  }
  private func start(id: String, locked: Bool, haptics: Bool, preferences: OutputPreferences? = nil) throws {
    try prepareDictation(preferences: preferences)
    keyboardRetry = nil
    stopRecoveryPlayback(publish: false)
    let format = engine.inputNode.outputFormat(forBus: 0)
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("clarify-\(UUID().uuidString).m4a")
    let newFile = try AudioClipWriter(url: url, inputFormat: format)
    let capture: ComputerLiveCapture?
    do { capture = try MainActor.assumeIsolated {
      // Keep the supported background/keyboard WAV path until native live
      // transport has passed physical-device background acceptance.
      guard Bundle.main.object(forInfoDictionaryKey: "ClarifyExperimentalLiveCapture") as? Bool == true,
        UIApplication.shared.applicationState == .active else { return nil }
      return try ProcessingDestination.shared.prepareLive(id, preferences: clipPreferences, policy: clipPolicy) { [weak self] partial in
        guard let self, self.state.operationID == id,
          [.recording, .locked, .transcribing].contains(self.state.phase),
          ProcessingDestination.shared.acceptsHistory(self.clipHistory),
          self.store?.isCancelled(id) != true else { return }
        self.state.livePartial = partial; self.publish()
      }
    } } catch { newFile.cancel(); try? FileManager.default.removeItem(at: url); throw error }
    let converter: ComputerLivePCMConverter?
    do { converter = try capture.map { _ in try ComputerLivePCMConverter(format: format) } }
    catch {
      capture?.cancel()
      MainActor.assumeIsolated { ComputerConnection.shared.cancelOperation(id) }
      newFile.cancel(); try? FileManager.default.removeItem(at: url); throw error
    }
    let cueDuration = playCue(starting: true)
    if haptics, UIApplication.shared.applicationState == .active {
      feedback.record("start")
    }
    // The engine discards the short start cue so it is not sent for transcription.
    let captureStart = Date().addingTimeInterval(cueDuration)
    fileLock.lock()
    liveCapture = capture; liveConverter = converter; liveOperationID = capture == nil ? nil : id
    file = newFile; audioURL = url; captureAfter = captureStart.timeIntervalSince1970
    meteredOperationID = id; meteredAt = 0; meteredLevel = 0
    fileLock.unlock()
    startedAt = captureStart
    state.operationID = id
    state.textOperation = false
    state.phase = locked ? .locked : .recording
    state.text = nil; state.livePartial = nil; state.message = nil; state.errorRecovery = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil
    publish()
  }
  private func closeFile(finalize: Bool = false) -> URL? {
    fileLock.lock()
    var failed = false
    if finalize {
      do { if let capture = liveCapture { try liveConverter?.finish(to: capture) } }
      catch { liveCapture?.cancel(); failed = true }
      do { try file?.finish() } catch { liveCapture?.cancel(); failed = true }
    } else { liveCapture?.cancel(); file?.cancel() }
    liveCapture = nil; liveConverter = nil
    file = nil
    let url = audioURL; audioURL = nil
    meteredOperationID = nil; meteredAt = 0; meteredLevel = 0
    fileLock.unlock()
    try? store?.publishAudioMeter(.inactive())
    if failed {
      if let url { _ = retainRecording(url, createdAt: startedAt?.timeIntervalSince1970 ?? Date().timeIntervalSince1970,
        duration: startedAt.map { max(0, Date().timeIntervalSince($0)) } ?? 0) }
      return nil
    }
    return url
  }
  private func finish(haptics: Bool = true) {
    guard [.recording, .locked].contains(state.phase), let id = state.operationID else { return }
    let duration = startedAt.map { Date().timeIntervalSince($0) } ?? 0
    let recordedAt = startedAt?.timeIntervalSince1970 ?? Date().timeIntervalSince1970
    let historyOwner = clipHistory
    let preferences = clipPreferences
    let policy = clipPolicy
    startedAt = nil
    fileLock.lock(); let live = liveCapture; fileLock.unlock()
    guard let url = closeFile(finalize: true) else { fail(L("Não foi possível gravar o áudio.")); return }
    playCue(starting: false)
    if haptics, UIApplication.shared.applicationState == .active { feedback.record("finish") }
    guard duration >= 0.3 else {
      try? FileManager.default.removeItem(at: url)
      fail(L("Fale por mais tempo antes de concluir.")); return
    }
    let retainedURL = retainRecording(url, createdAt: recordedAt, duration: duration)
    guard ProcessingDestination.shared.acceptsHistory(historyOwner) else {
      fail(L("Entre na conta novamente.")); return
    }
    guard ProcessingDestination.shared.configured else {
      fail(L("Entre na conta novamente.")); return
    }
    processRecording(retainedURL, id: id, recordedAt: recordedAt, historyOwner: historyOwner,
      preferences: preferences, policy: policy, live: live)
  }
  private func retainRecording(_ url: URL, createdAt: TimeInterval, duration: TimeInterval) -> URL {
    let retained = (try? recoveryResult.get().retain(url, createdAt: createdAt, duration: duration)) ?? url
    state.libraryRevision += 1
    return retained
  }
  func recoveryRecordings() throws -> [[String: Any]] {
    let rows = try recoveryResult.get().recordings(excluding: audioURL)
    let destination = ProcessingDestination.shared
    return try rows.map { row in
      let linked = try row.historyID.map { try library().hasHistoryEntry($0, scope: destination.historyScope, includeLocal: !destination.computerMode) } ?? false
      return ["id": row.id, "createdAt": row.createdAt, "duration": row.duration,
        "status": row.status.rawValue, "processing": processingRecordings.contains(row.id),
        "historyId": row.historyID ?? "", "linked": linked, "useOriginal": row.useOriginal ?? false]
    }
  }
  func assertRecordingCanBeDeleted(_ id: String) throws {
    let recovery = try recoveryResult.get()
    guard !processingRecordings.contains(id), !sharedRecordings.contains(id),
          audioURL.flatMap({ recovery.id(for: $0) }) != id else { throw ClarifyError(L("Aguarde o processamento atual.")) }
  }
  func deleteRecoveryRecording(_ id: String) throws {
    try assertRecordingCanBeDeleted(id)
    if recoveryPlayerID == id { stopRecoveryPlayback(publish: false) }
    try recoveryResult.get().remove(id)
    state.libraryRevision += 1; publish()
  }
  func undoRecoveryEdit(_ id: String, context: String) throws {
    guard context == ProcessingDestination.shared.historyContext else { throw ComputerFailure.cancelled }
    let recovery = try recoveryResult.get()
    try recovery.showOriginal(id)
    state.libraryRevision += 1; publish()
  }
  func toggleRecoveryPlayback(_ id: String) throws -> Bool {
    guard ![.recording, .locked].contains(state.phase) else { throw ComputerFailure.busy }
    do {
      if recoveryPlayerID == id, let player = recoveryPlayer, player.isPlaying {
        player.pause(); state.playingRecordingID = nil
        if !state.sessionActive { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
        publish(); return false
      }
      if recoveryPlayerID != id || recoveryPlayer == nil {
        stopRecoveryPlayback(publish: false)
        let player = try AVAudioPlayer(contentsOf: recoveryResult.get().audioURL(id))
        player.delegate = self; recoveryPlayer = player; recoveryPlayerID = id
      }
      if !state.sessionActive {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
        try session.setActive(true)
      }
      guard recoveryPlayer?.play() == true else { throw ClarifyError(L("Não foi possível abrir o áudio. Tente novamente.")) }
      state.playingRecordingID = id; publish(); return true
    } catch {
      stopRecoveryPlayback()
      throw error
    }
  }
  private func stopRecoveryPlayback(publish shouldPublish: Bool = true) {
    let hadPlayer = recoveryPlayer != nil
    recoveryPlayer?.stop(); recoveryPlayer = nil; recoveryPlayerID = nil; state.playingRecordingID = nil
    if hadPlayer, !state.sessionActive { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
    if shouldPublish { publish() }
  }
  func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
    guard player === recoveryPlayer else { return }
    stopRecoveryPlayback()
  }
  func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
    if player === recoveryPlayer { stopRecoveryPlayback() }
  }
  func beginSharingRecording(_ id: String) throws -> URL {
    let url = try recoveryResult.get().audioURL(id)
    sharedRecordings.insert(id)
    return url
  }
  func endSharingRecording(_ id: String) { sharedRecordings.remove(id) }
  func reprocessRecording(_ recordingID: String, context: String) throws -> String {
    guard !state.phase.busy, !processingRecordings.contains(recordingID),
          context == ProcessingDestination.shared.historyContext else { throw ComputerFailure.busy }
    let recovery = try recoveryResult.get()
    let source = try recovery.audioURL(recordingID)
    let id = UUID().uuidString
    try reprocessAudio(source, id: id)
    return id
  }
  private func reprocessAudio(_ source: URL, id: String, preferences: OutputPreferences? = nil) throws {
    let recovery = try? recoveryResult.get()
    let row = recovery?.recordings().first { $0.id == recovery?.id(for: source) }
    try prepareDictation(preferences: preferences)
    let url = retainRecording(source, createdAt: row?.createdAt ?? Date().timeIntervalSince1970, duration: row?.duration ?? 0)
    state.operationID = id; state.textOperation = false; state.text = nil; state.livePartial = nil; state.message = nil
    state.errorRecovery = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil
    processRecording(url, id: id, recordedAt: Date().timeIntervalSince1970, historyOwner: clipHistory,
      preferences: clipPreferences, policy: clipPolicy)
  }
  private func processRecording(_ url: URL, id: String, recordedAt: TimeInterval, historyOwner: ProcessingCapture,
    preferences: OutputPreferences, policy: DictationPolicy, live: ComputerLiveCapture? = nil) {
    keyboardRetry = (id, url, ProcessingDestination.shared.historyContext)
    let recoveryID = try? recoveryResult.get().id(for: url)
    if let recoveryID { processingRecordings.insert(recoveryID) }
    state.libraryRevision += 1
    state.phase = .transcribing; publish()
    backgroundTask = UIApplication.shared.beginBackgroundTask(withName: "Clarify transcription") { [weak self] in
      guard let self, self.state.operationID == id else { return }
      self.cancel()
    }
    let backgroundID = backgroundTask
    task = Task { @MainActor [weak self] in
      guard let self = self else { return }
      defer {
        if self.liveOperationID == id { self.liveOperationID = nil }
        if let recoveryID { self.processingRecordings.remove(recoveryID) }
        self.state.libraryRevision += 1; self.publish()
        self.endBackgroundTask(backgroundID)
      }
      do {
        let outcome: ProcessingDictation
        if let live { outcome = try await ProcessingDestination.shared.finishLive(live, owner: historyOwner) }
        else { outcome = try await ProcessingDestination.shared.dictate(url, operationID: id, library: self.library(), preferences: preferences, policy: policy) }
        guard !Task.isCancelled, self.state.operationID == id, ProcessingDestination.shared.acceptsHistory(historyOwner) else { return }
        self.state.livePartial = nil
        let transcript = outcome.transcript
        if let recoveryID { try? self.recoveryResult.get().mark(recoveryID, status: .complete) }
        self.state.text = outcome.text
        self.state.phase = outcome.successful ? .ready : .error
        if !outcome.successful { self.state.message = L(outcome.outputPreferenceFailed ? OutputPreferences.unappliedMessage : "A reescrita falhou. Você pode inserir a transcrição original.") }
        if outcome.outputPreferenceFailed { self.state.errorCode = "output_preferences_unapplied"; self.state.errorPhase = "rewriting" }
        // Save only the terminal result of this still-current operation. The
        // original text remains available when rewriting fails. The audio has
        // independent device-only retention and never enters account sync.
        guard !Task.isCancelled, self.state.operationID == id, ProcessingDestination.shared.acceptsHistory(historyOwner) else { return }
        do {
          try self.library().record(HistoryEntry(id: id, createdAt: recordedAt,
            transcript: transcript, text: self.state.text ?? transcript,
            rewritten: outcome.rewritten), scope: historyOwner.scope)
          if let recoveryID { try? self.recoveryResult.get().mark(recoveryID, status: .complete, historyID: id) }
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
        if let recoveryID { try? self.recoveryResult.get().mark(recoveryID, status: .failed) }
        self.fail((error is ClarifyError || error is ComputerFailure) ? error.localizedDescription : L("Falha de conexão. Verifique a internet e tente novamente."), diagnostics: error as? ClarifyError)
      }
    }
  }
  @MainActor func startText(_ action: String, id: String = UUID().uuidString, text: String, language: String,
    context: String, actionID: String? = nil, revision: String? = nil, preferences: OutputPreferences? = nil) async throws -> String {
    let destination = ProcessingDestination.shared
    guard !state.phase.busy, !destination.textStartBlocked else { throw ComputerFailure.busy }
    guard destination.configured,
      cancellations.acceptsStart(id, now: Date().timeIntervalSince1970), store?.isCancelled(id) != true,
      UUID(uuidString: id) != nil, !text.contains("\0"), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      text.utf8.count <= (destination.computerMode ? ProcessingContractData.computerTextInputBytes : ProcessingContractData.accountTextInputBytes), context == destination.historyContext,
      OutputLanguage(rawValue: language) != nil else { throw ComputerFailure.notReady }
    let frozen = preferences ?? store?.outputPreferences() ?? OutputPreferences()
    let owner = destination.captureHistory()
    let accountIdentity = destination.captureTextIdentity()
    // Reserve the operation before discovery can suspend. The keyboard can then
    // acknowledge and cancel preparation through the same existing task owner.
    state.operationID = id; state.textOperation = true; state.text = nil; state.livePartial = nil; state.message = nil
    state.errorRecovery = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil; state.phase = .rewriting; publish()
    task = Task { @MainActor [weak self] in
      guard let self else { return }
      do {
        let prepared = try await destination.prepareText(action, actionID: actionID, revision: revision,
          language: language, context: context, preferences: frozen, accountIdentity: accountIdentity)
        try Task.checkCancellation()
        guard self.state.operationID == id, self.state.phase == .rewriting,
          destination.acceptsHistory(owner), destination.acceptsHistory(prepared.owner),
          self.cancellations.acceptsStart(id, now: Date().timeIntervalSince1970),
          self.store?.isCancelled(id) != true else { throw CancellationError() }
        let result = try await destination.processText(id, prepared: prepared, text: text)
        guard !Task.isCancelled, self.state.operationID == id, destination.acceptsHistory(prepared.owner) else { return }
        if self.store?.isCancelled(id) == true { self.cancel(); return }
        self.state.text = result.text; self.state.phase = result.successful ? .ready : .error
        if !result.successful { self.state.message = L(result.outputPreferenceFailed ? OutputPreferences.unappliedMessage : "A reescrita falhou. Você pode inserir a transcrição original.") }
        if result.outputPreferenceFailed { self.state.errorCode = "output_preferences_unapplied"; self.state.errorPhase = "rewriting" }
        do {
          try self.library().record(HistoryEntry(id: id, createdAt: Date().timeIntervalSince1970,
            transcript: text, text: result.text, rewritten: result.rewritten), scope: prepared.owner.scope)
          self.state.libraryRevision += 1; self.publish(); self.syncHistory(force: true)
        } catch {
          self.state.message = L("O texto foi preservado, mas não foi possível salvar o histórico."); self.publish()
        }
      } catch {
        guard !Task.isCancelled, self.state.operationID == id else { return }
        if error is CancellationError || !destination.acceptsHistory(owner) { self.cancel(); return }
        self.fail((error is ComputerFailure || error is ClarifyError) ? error.localizedDescription : ComputerFailure.offline.localizedDescription,
          diagnostics: error as? ClarifyError)
      }
    }
    return id
  }
  private func endBackgroundTask(_ expected: UIBackgroundTaskIdentifier? = nil) {
    if let expected = expected, expected != backgroundTask { return }
    if backgroundTask != .invalid { UIApplication.shared.endBackgroundTask(backgroundTask); backgroundTask = .invalid }
  }
  func clearResult(publish: Bool = true) {
    keyboardRetry = nil
    state.livePartial = nil
    state.operationID = nil; state.textOperation = false; state.text = nil; state.phase = .idle; state.message = nil
    state.errorRecovery = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil
    if publish { self.publish() }
  }
  func destinationChanged() {
    if let id = state.operationID {
      // Control callbacks already use the main queue. Cancel synchronously so
      // the remote action is retired before publishing another destination.
      MainActor.assumeIsolated { ComputerConnection.shared.cancelOperation(id) }
    }
    // Clear ownership before cancel/deactivate publish any intermediate state.
    clearResult(publish: false)
    deactivate(); libraryChanged()
  }
  private func cancelLiveCapture() {
    fileLock.lock()
    liveCapture?.cancel(); liveCapture = nil; liveConverter = nil
    fileLock.unlock()
    liveOperationID = nil
  }
  func cancel(preserveCapture: Bool = false) {
    cancelLiveCapture()
    state.livePartial = nil
    keyboardRetry = nil
    let capturedAt = startedAt
    let wasRecording = [.recording, .locked].contains(state.phase)
    if ProcessingDestination.shared.computerMode, let id = state.operationID {
      MainActor.assumeIsolated { ComputerConnection.shared.cancelOperation(id) }
    }
    cuePlayer?.stop(); cuePlayer = nil
    task?.cancel(); task = nil; startedAt = nil
    if let url = closeFile(finalize: preserveCapture) {
      if preserveCapture {
        _ = retainRecording(url, createdAt: capturedAt?.timeIntervalSince1970 ?? Date().timeIntervalSince1970,
          duration: capturedAt.map { max(0, Date().timeIntervalSince($0)) } ?? 0)
      } else { try? FileManager.default.removeItem(at: url) }
    }
    if wasRecording { playCue(starting: false) }
    if state.phase.busy {
      state.operationID = nil; state.phase = .idle; state.text = nil; state.livePartial = nil; state.message = nil
      state.errorRecovery = nil; state.errorCode = nil; state.errorPhase = nil; state.errorStatus = nil
    }
    endBackgroundTask()
    publish()
  }
  private func fail(_ message: String, diagnostics: ClarifyError? = nil) {
    cancelLiveCapture()
    state.livePartial = nil
    if let id = state.operationID { MainActor.assumeIsolated { ComputerConnection.shared.cancelOperation(id) } }
    let capturedAt = startedAt
    if !ProcessingDestination.shared.configured, state.sessionActive { stopAudio() }
    cuePlayer?.stop(); cuePlayer = nil
    task?.cancel(); task = nil; startedAt = nil
    if let url = closeFile(finalize: true) {
      _ = retainRecording(url, createdAt: capturedAt?.timeIntervalSince1970 ?? Date().timeIntervalSince1970,
        duration: capturedAt.map { max(0, Date().timeIntervalSince($0)) } ?? 0)
    }
    endBackgroundTask()
    state.phase = .error; state.message = message
    state.errorRecovery = diagnostics?.recovery; state.errorCode = diagnostics?.code; state.errorPhase = diagnostics?.phase; state.errorStatus = diagnostics?.status
    publish()
  }
  @discardableResult
  private func playCue(starting: Bool) -> TimeInterval {
    cuePlayer?.stop(); cuePlayer = nil
    let name = starting ? "dictation-start" : "dictation-stop"
    guard let url = Bundle.main.url(forResource: name, withExtension: "wav"),
      let player = try? AVAudioPlayer(contentsOf: url) else { return 0 }
    player.volume = 1
    player.prepareToPlay()
    guard player.play() else { return 0 }
    cuePlayer = player
    // Include the output route's latency so the microphone does not capture
    // either note, including on Bluetooth routes.
    let session = AVAudioSession.sharedInstance()
    return player.duration + session.outputLatency + session.ioBufferDuration + 0.03
  }
  private func inputInterrupted(_ message: String, resetEngine: Bool = false) {
    let processingStoppedClip = state.phase == .transcribing && !state.textOperation
    deactivate()
    if resetEngine { engine = AVAudioEngine() }
    if !processingStoppedClip { fail(message) }
  }
  @objc private func interrupted(_ notification: Notification) {
    guard let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
          AVAudioSession.InterruptionType(rawValue: raw) == .began else { return }
    DispatchQueue.main.async { self.inputInterrupted(L("O áudio foi interrompido. Abra o Clarify para reativar o microfone.")) }
  }
  @objc private func routeChanged(_ notification: Notification) {
    guard let raw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
          let reason = AVAudioSession.RouteChangeReason(rawValue: raw),
          [.oldDeviceUnavailable, .newDeviceAvailable].contains(reason) else { return }
    DispatchQueue.main.async {
      if self.state.sessionActive { self.inputInterrupted(L("O dispositivo de áudio mudou. Ative o microfone novamente.")) }
    }
  }
  @objc private func mediaReset() {
    DispatchQueue.main.async {
      self.inputInterrupted(L("O áudio foi reiniciado pelo iOS. Ative o microfone novamente."), resetEngine: true)
    }
  }
}

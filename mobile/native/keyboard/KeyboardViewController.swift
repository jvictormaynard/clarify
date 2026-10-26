import UIKit
import SwiftUI
#if SWIFT_PACKAGE
import KeyboardHostSupport
#endif

final class KeyboardInputView: UIInputView {
  static let contentHeight: CGFloat = 278
  override init(frame: CGRect, inputViewStyle: UIInputView.Style) {
    super.init(frame: frame, inputViewStyle: inputViewStyle)
    // Publish one height before UIKit attaches and animates this input view.
    // The host can resize its width without changing the keyboard's height.
    autoresizingMask = [.flexibleWidth]
    allowsSelfSizing = true
    heightAnchor.constraint(equalToConstant: Self.contentHeight).isActive = true
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
  override var intrinsicContentSize: CGSize { CGSize(width: UIView.noIntrinsicMetric, height: Self.contentHeight) }
  override func sizeThatFits(_ size: CGSize) -> CGSize {
    CGSize(width: size.width, height: Self.contentHeight)
  }
  override func systemLayoutSizeFitting(_ targetSize: CGSize) -> CGSize {
    CGSize(width: targetSize.width, height: Self.contentHeight)
  }
  override func systemLayoutSizeFitting(_ targetSize: CGSize, withHorizontalFittingPriority horizontal: UILayoutPriority,
                                      verticalFittingPriority vertical: UILayoutPriority) -> CGSize {
    systemLayoutSizeFitting(targetSize)
  }
}

final class RecordingGlyph: UIView {
  private let icon = UIImageView(image: UIImage(systemName: "mic.fill"))
  override init(frame: CGRect) {
    super.init(frame: frame)
    isUserInteractionEnabled = false; isAccessibilityElement = false
    icon.tintColor = .systemBackground; icon.contentMode = .scaleAspectFit
    icon.translatesAutoresizingMaskIntoConstraints = false; addSubview(icon)
    NSLayoutConstraint.activate([
      icon.widthAnchor.constraint(equalToConstant: 22), icon.heightAnchor.constraint(equalToConstant: 22),
      icon.centerXAnchor.constraint(equalTo: centerXAnchor), icon.centerYAnchor.constraint(equalTo: centerYAnchor)
    ])
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
}

final class RecordControl: UIButton {
  var onAction: ((String) -> Void)?
  override init(frame: CGRect) {
    super.init(frame: frame)
    addAction(UIAction { [weak self] _ in self?.startRecording() }, for: .touchUpInside)
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
  @objc private func startRecording() { if isEnabled && !isHidden { onAction?("start") } }
  override func accessibilityActivate() -> Bool {
    guard isEnabled, !isHidden else { return false }
    startRecording(); return true
  }
}

// Match the desktop pill's envelope, energy response and independent bar motion.
// Only this view owns its display clock; the app remains the audio owner.
final class RecordingWaveform: UIView {
  private let bars = (0..<12).map { _ in UIView() }
  private var targetLevel = 0.0
  private var motionPhase = 0.0
  private var recording = false
  private var reduceMotion = UIAccessibility.isReduceMotionEnabled
  private var frameTimer: Timer?
  private var lastFrameTime: CFTimeInterval?
  private var motionObserver: NSObjectProtocol?
  private(set) var displayedLevel = 0.0
  var isAnimating: Bool { frameTimer != nil }
  override var isHidden: Bool { didSet { syncClock() } }
  override init(frame: CGRect) {
    super.init(frame: frame)
    isUserInteractionEnabled = false; isAccessibilityElement = false
    for bar in bars { bar.backgroundColor = .label; bar.layer.cornerRadius = 2; addSubview(bar) }
    motionObserver = NotificationCenter.default.addObserver(forName: UIAccessibility.reduceMotionStatusDidChangeNotification,
      object: nil, queue: .main) { [weak self] _ in
        guard let self else { return }
        self.reduceMotion = UIAccessibility.isReduceMotionEnabled
        if self.reduceMotion { self.motionPhase = 0; self.displayedLevel = self.targetLevel; self.layoutBars() }
        self.syncClock()
      }
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
  deinit {
    frameTimer?.invalidate()
    if let motionObserver { NotificationCenter.default.removeObserver(motionObserver) }
  }
  override func layoutSubviews() { super.layoutSubviews(); layoutBars() }
  override func didMoveToWindow() { super.didMoveToWindow(); syncClock() }
  private func layoutBars(blend: Double = 1) {
    let step = bounds.width / CGFloat(bars.count)
    for (index, bar) in bars.enumerated() {
      let position = Double(index) / 11
      let envelope = 0.58 + 0.42 * sin(position * .pi)
      let motion = reduceMotion ? 0 : 0.12 * sin(motionPhase + Double(index) * 0.82)
      let amplitude = max(0.22, min(0.98, (displayedLevel * 1.45 + 0.24 + motion) * envelope))
      let target = max(6.4, Double(max(0, bounds.height - 16)) * amplitude)
      let current = max(6.4, Double(bar.bounds.height))
      let height = CGFloat(current + (target - current) * blend)
      bar.frame = CGRect(x: step * CGFloat(index) + (step - 4) / 2, y: (bounds.height - height) / 2, width: 4, height: height)
    }
  }
  func update(level: Double, recording: Bool, reduceMotion: Bool? = nil) {
    let measured = level.isFinite ? min(1, max(0, level)) : 0
    // The shared meter uses a -52...-9 dB scale. Convert only its presentation
    // back to the RMS x16 input used by the desktop pill, without changing audio.
    targetLevel = measured > 0 ? min(1, pow(10, (measured * 43 - 52) / 20) * 16) : 0
    self.recording = recording; self.reduceMotion = reduceMotion ?? UIAccessibility.isReduceMotionEnabled
    if !recording { targetLevel = 0; displayedLevel = 0; motionPhase = 0; layoutBars() }
    else if self.reduceMotion { displayedLevel = targetLevel; motionPhase = 0; layoutBars() }
    syncClock()
  }
  // An elapsed-time boundary keeps smoothing stable if UIKit misses a frame.
  func advanceFrame(by elapsed: TimeInterval) {
    guard recording, !reduceMotion, elapsed.isFinite, elapsed > 0 else { return }
    let interval = min(0.064, elapsed)
    let blend = targetLevel > displayedLevel ? 0.38 : 0.12
    displayedLevel += (targetLevel - displayedLevel) * (1 - pow(1 - blend, interval / 0.016))
    motionPhase = (motionPhase + 0.085 * interval / 0.016).truncatingRemainder(dividingBy: 2 * .pi)
    // Desktop bars retarget a 45 ms OutCubic interpolation on each 16 ms tick.
    layoutBars(blend: 1 - pow(1 - min(1, interval / 0.045), 3))
  }
  private func syncClock() {
    guard recording, !reduceMotion, !isHidden, window != nil else {
      frameTimer?.invalidate(); frameTimer = nil; lastFrameTime = nil; return
    }
    guard frameTimer == nil else { return }
    lastFrameTime = CACurrentMediaTime()
    let timer = Timer(timeInterval: 0.016, repeats: true) { [weak self] _ in
      guard let self else { return }
      let now = CACurrentMediaTime()
      self.advanceFrame(by: now - (self.lastFrameTime ?? now)); self.lastFrameTime = now
    }
    frameTimer = timer; RunLoop.main.add(timer, forMode: .common)
  }
}

// SwiftUI opens the container; the experimental source resolver supplies a nonce.
private struct ActivationLink: View {
  @Environment(\.openURL) private var openURL
  @State private var launchTask: Task<Void, Never>?
  @State private var opening = false
  let destination: () async -> URL?
  var body: some View {
    Button {
      guard !opening else { return }; opening = true
      launchTask = Task {
        defer { opening = false; launchTask = nil }
        guard let url = await destination(), !Task.isCancelled else { return }
        openURL(url)
      }
    } label: {
      HStack(spacing: 7) {
        ClarifyMark().fill(Color(uiColor: .systemBackground)).frame(width: 22, height: 24)
        Text(L("Começar")).font(.system(size: 14, weight: .semibold))
      }.foregroundStyle(Color(uiColor: .systemBackground))
        .frame(width: 118, height: 44).background(Color(uiColor: .label), in: Capsule())
    }.buttonStyle(.plain).disabled(opening).accessibilityLabel(L("Começar no Clarify"))
      .accessibilityIdentifier("clarify.keyboard.start")
      .accessibilityHint(L("Abre o Clarify para ativar o microfone."))
      .onDisappear { launchTask?.cancel(); launchTask = nil; opening = false }
  }
}

class KeyboardViewController: UIInputViewController {
  var store = SharedState()
  private let mic = RecordControl()
  private let glyph = RecordingGlyph()
  private let status = UILabel()
  private let detail = UILabel()
  private var detailTop: NSLayoutConstraint?
  private var detailCenter: NSLayoutConstraint?
  private var detailTrailing: NSLayoutConstraint?
  private var errorTrailing: NSLayoutConstraint?
  private let insert = UIButton(type: .system)
  private let cancel = UIButton(type: .system)
  private let finishRecordingButton = UIButton(type: .system)
  private let recordingPanel = UIView()
  private let waveform = RecordingWaveform()
  private let recordingStatus = UILabel()
  private let processingSpinner = UIActivityIndicatorView(style: .medium)
  private let globe = UIButton(type: .system)
  private var recordingRequest = RecordingRequest()
  private var recordingPanelVisible = false
  private var recordingError: String?
  private let keys = KeyGridView()
  private let typing = TypingAssistant()
  private var typingVocabularyRevision = -1
  private var typingVocabularyCheckedAt = Date.distantPast
  private let suggestions = UIStackView()
  private let addToDictionary = UIButton(type: .system)
  private let undoDictation = UIButton(type: .system)
  private var dictationEdit: DictationEdit?
  private var applyingDictationEdit = false
  private var dictionaryTrailing: NSLayoutConstraint?
  private var selectedTerm: String?
  private var selectedScope: String?
  private var selectedDocument: UUID?
  private var dictionaryError: String?
  private var dictionaryContext: KeyboardDictionaryContext?
  private var dictionaryCheckedAt = Date.distantPast
  private var dictionaryRevision = -1
  private var selectedTermSaved = false
  private let feedback = HapticFeedback()
  private var activation: UIHostingController<ActivationLink>?
  private var timer: Timer?
  private var operationID: String?
  private var documentID: UUID?
  private var textOperationID: String?
  private var textSelection: TextSelectionOwner?
  private var attached = false
  private var state = DictationSnapshot()

  // The remote input host can ask before loadView, and can propose another size
  // during presentation. Both measurement paths must advertise the same height.
  override var preferredContentSize: CGSize {
    get { CGSize(width: super.preferredContentSize.width, height: KeyboardInputView.contentHeight) }
    set { super.preferredContentSize = CGSize(width: newValue.width, height: KeyboardInputView.contentHeight) }
  }

  override func loadView() {
    let input = KeyboardInputView(frame: CGRect(x: 0, y: 0, width: 0, height: KeyboardInputView.contentHeight), inputViewStyle: .keyboard)
    inputView = input
    // Let the system keyboard material remain visible behind the extension.
    view.backgroundColor = .clear
    view.isOpaque = false
  }

  override func viewDidLoad() {
    super.viewDidLoad()
    // Public API disables the OS dictation action. iOS owns its bottom-bar icon.
    hasDictationKey = true
    status.font = .systemFont(ofSize: 15, weight: .semibold)
    status.accessibilityIdentifier = "clarify.keyboard.status"
    detail.font = .systemFont(ofSize: 11); detail.textColor = .secondaryLabel
    detail.accessibilityIdentifier = "clarify.keyboard.detail"
    detail.numberOfLines = 1; detail.lineBreakMode = .byTruncatingTail
    mic.backgroundColor = .label; mic.layer.cornerRadius = 22
    mic.isAccessibilityElement = true; mic.accessibilityTraits = .button
    mic.accessibilityIdentifier = "clarify.keyboard.record"
    mic.accessibilityLabel = L("Gravar")
    mic.accessibilityHint = L("Toque para começar o ditado.")
    mic.onAction = { [weak self] action in self?.send(action) }
    mic.addSubview(glyph); glyph.translatesAutoresizingMaskIntoConstraints = false
    detailTop = detail.topAnchor.constraint(equalTo: status.bottomAnchor, constant: 3)
    detailCenter = detail.centerYAnchor.constraint(equalTo: mic.centerYAnchor)
    detailTrailing = detail.trailingAnchor.constraint(equalTo: insert.leadingAnchor, constant: -4)
    errorTrailing = detail.trailingAnchor.constraint(equalTo: mic.leadingAnchor, constant: -8)
    NSLayoutConstraint.activate([
      glyph.leadingAnchor.constraint(equalTo: mic.leadingAnchor), glyph.trailingAnchor.constraint(equalTo: mic.trailingAnchor),
      glyph.topAnchor.constraint(equalTo: mic.topAnchor), glyph.bottomAnchor.constraint(equalTo: mic.bottomAnchor)
    ])
    insert.setTitle(L("Inserir"), for: .normal)
    insert.isHidden = true; cancel.isHidden = true
    insert.titleLabel?.font = .systemFont(ofSize: 13, weight: .medium)
    insert.addTarget(self, action: #selector(insertResult), for: .touchUpInside)
    cancel.setImage(UIImage(systemName: "xmark"), for: .normal); cancel.accessibilityLabel = L("Cancelar gravação")
    cancel.tintColor = .label
    cancel.accessibilityIdentifier = "clarify.keyboard.cancel"
    cancel.addAction(UIAction { [weak self] _ in self?.cancelRecording() }, for: .touchUpInside)
    keys.previewContainer = view
    keys.onKeyPress = { [weak self] in self?.feedback.type() }
    keys.onInsert = { [weak self] text in
      guard let self = self else { return }
      self.dictationEdit = nil
      self.typing.insert(text, into: self.textDocumentProxy); self.updateCapitalization(); self.updateSuggestions()
    }
    keys.onDelete = { [weak self] in
      guard let self = self else { return }
      self.dictationEdit = nil
      self.typing.delete(in: self.textDocumentProxy); self.updateCapitalization(); self.updateSuggestions()
    }
    keys.onNextKeyboard = { [weak self] button, event in
      if let event = event { self?.handleInputModeList(from: button, with: event) }
      else { self?.advanceToNextInputMode() }
    }
    suggestions.axis = .horizontal; suggestions.distribution = .fillEqually
    addToDictionary.accessibilityIdentifier = "clarify.add-to-dictionary"
    addToDictionary.titleLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
    addToDictionary.titleLabel?.adjustsFontSizeToFitWidth = true
    addToDictionary.titleLabel?.minimumScaleFactor = 0.75
    addToDictionary.setPreferredSymbolConfiguration(UIImage.SymbolConfiguration(pointSize: 16, weight: .regular), forImageIn: .normal)
    addToDictionary.imageEdgeInsets = UIEdgeInsets(top: 0, left: 10, bottom: 0, right: -10)
    addToDictionary.layer.cornerRadius = 22
    addToDictionary.addAction(UIAction { [weak self] _ in self?.saveSelectedTerm() }, for: .touchUpInside)
    addToDictionary.contentEdgeInsets = UIEdgeInsets(top: 0, left: 18, bottom: 0, right: 28)
    addToDictionary.isHidden = true
    undoDictation.accessibilityIdentifier = "clarify.undo-dictation"
    undoDictation.setPreferredSymbolConfiguration(UIImage.SymbolConfiguration(pointSize: 22, weight: .medium), forImageIn: .normal)
    undoDictation.tintColor = .label; undoDictation.isHidden = true
    undoDictation.addAction(UIAction { [weak self] _ in self?.toggleDictationEdit() }, for: .touchUpInside)
    for element in [status, detail, mic, insert, keys, suggestions, addToDictionary, undoDictation] {
      element.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(element)
    }
    NSLayoutConstraint.activate([
      mic.topAnchor.constraint(equalTo: view.topAnchor, constant: 7), mic.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -10),
      mic.widthAnchor.constraint(equalToConstant: 44), mic.heightAnchor.constraint(equalToConstant: 44),
      status.topAnchor.constraint(equalTo: view.topAnchor, constant: 10), status.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 12),
      status.trailingAnchor.constraint(lessThanOrEqualTo: insert.leadingAnchor, constant: -4),
      detailTop!, detail.leadingAnchor.constraint(equalTo: status.leadingAnchor), detailTrailing!,
      detail.heightAnchor.constraint(lessThanOrEqualToConstant: 44),
      insert.centerYAnchor.constraint(equalTo: mic.centerYAnchor), insert.trailingAnchor.constraint(equalTo: mic.leadingAnchor, constant: -4),
      insert.widthAnchor.constraint(equalToConstant: 48),
      keys.topAnchor.constraint(equalTo: view.topAnchor, constant: 58), keys.heightAnchor.constraint(equalToConstant: 220),
      keys.leadingAnchor.constraint(equalTo: view.leadingAnchor), keys.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      suggestions.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 6),
      suggestions.trailingAnchor.constraint(equalTo: mic.leadingAnchor, constant: -8),
      suggestions.topAnchor.constraint(equalTo: view.topAnchor, constant: 7),
      suggestions.heightAnchor.constraint(equalToConstant: 44)
    ])
    NSLayoutConstraint.activate([
      undoDictation.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 10),
      undoDictation.centerYAnchor.constraint(equalTo: mic.centerYAnchor),
      undoDictation.widthAnchor.constraint(equalToConstant: 44), undoDictation.heightAnchor.constraint(equalToConstant: 44)
    ])
    dictionaryTrailing = addToDictionary.trailingAnchor.constraint(equalTo: mic.leadingAnchor, constant: -8)
    NSLayoutConstraint.activate([
      addToDictionary.leadingAnchor.constraint(greaterThanOrEqualTo: view.leadingAnchor, constant: 12),
      dictionaryTrailing!, addToDictionary.centerYAnchor.constraint(equalTo: mic.centerYAnchor),
      addToDictionary.heightAnchor.constraint(equalToConstant: 44)
    ])
    let host = UIHostingController(rootView: ActivationLink { [weak self] in await self?.activationURL() })
    if #available(iOS 16.4, *) { host.safeAreaRegions = [] }
    addChild(host); view.addSubview(host.view); host.didMove(toParent: self)
    host.view.backgroundColor = .clear; host.view.translatesAutoresizingMaskIntoConstraints = false
    NSLayoutConstraint.activate([
      host.view.trailingAnchor.constraint(equalTo: mic.trailingAnchor), host.view.centerYAnchor.constraint(equalTo: mic.centerYAnchor),
      host.view.widthAnchor.constraint(equalToConstant: 118), host.view.heightAnchor.constraint(equalToConstant: 44)
    ])
    activation = host
    configureRecordingPanel()
    requestSupplementaryLexicon { [weak self] lexicon in
      DispatchQueue.main.async { [weak self] in
        self?.typing.protect(lexicon); self?.updateSuggestions()
      }
    }
  }
  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    ClarifyKeyboardHeightDidLayout(self)
    if keys.needsGlobe != needsInputModeSwitchKey {
      UIView.performWithoutAnimation { keys.needsGlobe = needsInputModeSwitchKey; keys.rebuild(); keys.layoutIfNeeded() }
    }
  }
  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    ClarifyKeyboardHeightDidAppear(self)
  }
  override func textDidChange(_ textInput: UITextInput?) {
    super.textDidChange(textInput)
    // Context is used only locally for casing; it is never saved or sent to Groq.
    let proxy = textDocumentProxy
    let appearance: UIUserInterfaceStyle = proxy.keyboardAppearance == .dark ? .dark : (proxy.keyboardAppearance == .light ? .light : .unspecified)
    let returnType = proxy.returnKeyType ?? .default
    let changed = view.overrideUserInterfaceStyle != appearance || keys.returnType != returnType
    view.overrideUserInterfaceStyle = appearance
    keys.returnType = returnType
    updateCapitalization()
    if changed { keys.rebuild() }
    updateSuggestions()
  }
  private func updateCapitalization() {
    let proxy = textDocumentProxy
    guard !keys.model.shiftIsManual else { return }
    // An empty host field may expose nil context. Do not mistake unavailable
    // context in a nonempty field for the beginning of a sentence.
    guard let context = proxy.documentContextBeforeInput ?? (proxy.hasText ? nil : "") else { return }
    let type = proxy.autocapitalizationType ?? .sentences
    let next: KeyboardState.Shift = type == .allCharacters ? .caps :
      ((type == .sentences && KeyboardState.startsSentence(after: context)) ||
       (type == .words && (context.isEmpty || context.last?.isWhitespace == true)) ? .once : .off)
    if keys.model.shift != next { keys.model.shift = next; keys.rebuild() }
  }
  override func selectionDidChange(_ textInput: UITextInput?) {
    super.selectionDidChange(textInput)
    updateCapitalization()
    updateSuggestions()
  }
  override func viewWillAppear(_ animated: Bool) {
    super.viewWillAppear(animated); attached = true; feedback.prepare(); refreshFromStore(); updateCapitalization(); updateSuggestions(); timer?.invalidate()
    timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.refreshFromStore() }
  }
  override func viewDidDisappear(_ animated: Bool) {
    super.viewDidDisappear(animated); attached = false; timer?.invalidate(); timer = nil
    waveform.update(level: 0, recording: false)
    dictationEdit = nil; undoDictation.isHidden = true
    invalidateActivationSource()
    typing.reset()
    suggestions.arrangedSubviews.forEach { $0.removeFromSuperview() }
    // A tapped recording continues while switching apps/keyboards. Publication
    // still requires the original attached document or an explicit Insert tap.
    ClarifyKeyboardHeightDidDisappear(self)
  }
  deinit { timer?.invalidate() }
  private func send(_ action: String) {
    guard hasFullAccess, state.isLive, let store else { return }
    let id: String
    if action == "start" {
      textOperationID = nil; textSelection = nil
      guard !state.phase.busy, recordingRequest.action == nil else { return }
      id = UUID().uuidString
    } else {
      guard let current = operationID else { return }; id = current
      if action == "finish" {
        guard state.operationID == id, [.recording, .locked].contains(state.phase) else { return }
      }
    }
    guard recordingRequest.submit(action, operationID: id, now: Date().timeIntervalSince1970) else { return }
    if action == "start" {
      dictationEdit = nil; recordingError = nil
      operationID = id; documentID = textDocumentProxy.documentIdentifier
    }
    do { try store.send(action, operationID: id); feedback.record(action) }
    catch { recordingRequest.reset(); recordingError = L("Abra o Clarify para configurar o teclado.") }
    refreshFromStore()
  }
  private func currentTextSelection() -> TextSelectionOwner? {
    let proxy = textDocumentProxy
    guard proxy.isSecureTextEntry != true, let text = proxy.selectedText,
      !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.utf8.count <= 32_768 else { return nil }
    return TextSelectionOwner(document: proxy.documentIdentifier, text: text,
      before: proxy.documentContextBeforeInput, after: proxy.documentContextAfterInput)
  }
  func processSelection(_ action: String, language: String) {
    guard attached, hasFullAccess, state.isLive, state.computerMode, !state.phase.busy,
      recordingRequest.action == nil, let store, let selection = currentTextSelection() else { return }
    let id = UUID().uuidString
    guard recordingRequest.submit("start", operationID: id, now: Date().timeIntervalSince1970) else { return }
    do {
      try store.send(action, operationID: id, text: selection.text, language: language)
      operationID = id; documentID = selection.document
      textOperationID = id; textSelection = selection; dictationEdit = nil
      feedback.type()
    } catch { recordingRequest.reset(); recordingError = L("Abra o Clarify para configurar o teclado.") }
  }
  private func isCancelled(_ id: String?) -> Bool {
    recordingRequest.isCancelled(id) || store?.isCancelled(id) == true
  }
  // The lifecycle and timer share this state refresh. It does not simulate a
  // UIKit appearance transition when a snapshot or microphone meter changes.
  func refreshFromStore() {
    let previousContext = state.processingContext
    state = store?.snapshot() ?? DictationSnapshot()
    if previousContext != state.processingContext {
      operationID = nil; documentID = nil; textOperationID = nil; textSelection = nil; recordingRequest.reset()
    }
    let requestTimedOut = recordingRequest.observe(state, now: Date().timeIntervalSince1970)
    if requestTimedOut { recordingError = L("O ditado não iniciou. Tente novamente.") }
    if state.phase.busy || !state.isLive { recordingError = nil }
    if state.isLive, state.phase.busy, operationID != state.operationID {
      // A recreated extension can stop/cancel the clip but cannot claim its
      // original document. The explicit Insert action remains available later.
      operationID = state.operationID; documentID = nil; recordingRequest.reset()
    }
    let available = hasFullAccess && state.configured
    activation?.view.isHidden = !hasFullAccess || state.isLive
    mic.isEnabled = available && state.isLive && !state.phase.busy && recordingRequest.action == nil
    insert.isHidden = !state.isLive || state.text?.isEmpty != false || state.phase.busy ||
      isCancelled(state.operationID) || state.operationID == store?.receipt()
    if state.textOperation, textOperationID != state.operationID || textSelection != currentTextSelection() { insert.isHidden = true }
    if !hasFullAccess {
      status.text = L("Ative o Acesso Total"); detail.text = L("Ajustes > Geral > Teclado > Clarify")
    } else if state.isLive, state.phase == .error {
      status.text = L("Não foi possível concluir"); detail.text = state.message
    } else if !state.configured {
      status.text = state.computerMode ? L("Conecte seu computador") : L("Entre no Clarify")
      detail.text = L("Abra o Clarify para configurar.")
    } else if !state.isLive {
      status.text = L("Ative o microfone"); detail.text = L("Toque em Começar.")
    } else {
      status.text = nil; detail.text = recordingError
    }
    updateToolbar()
    updateRecordingPanel()
    if attached, state.phase == .ready, let id = operationID, state.operationID == id,
       !isCancelled(id), documentID == textDocumentProxy.documentIdentifier,
       store?.receipt() != id { insertResult() }
  }
  private func configureRecordingPanel() {
    recordingPanel.accessibilityIdentifier = "clarify.keyboard.recording-panel"
    recordingPanel.backgroundColor = .clear; recordingPanel.isOpaque = false
    recordingPanel.isHidden = true
    recordingStatus.font = .preferredFont(forTextStyle: .subheadline)
    recordingStatus.textAlignment = .center; recordingStatus.textColor = .secondaryLabel
    recordingStatus.adjustsFontForContentSizeCategory = true
    recordingStatus.adjustsFontSizeToFitWidth = true; recordingStatus.minimumScaleFactor = 0.75
    recordingStatus.accessibilityIdentifier = "clarify.keyboard.recording-status"
    recordingStatus.numberOfLines = 2
    finishRecordingButton.backgroundColor = .label; finishRecordingButton.tintColor = .systemBackground
    finishRecordingButton.layer.cornerRadius = 22
    finishRecordingButton.accessibilityIdentifier = "clarify.keyboard.finish"
    finishRecordingButton.accessibilityLabel = L("Finalizar gravação")
    finishRecordingButton.addAction(UIAction { [weak self] _ in self?.finishRecording() }, for: .touchUpInside)
    cancel.isHidden = false
    cancel.backgroundColor = .tertiarySystemFill; cancel.layer.cornerRadius = 22
    globe.setImage(UIImage(systemName: "globe"), for: .normal); globe.tintColor = .label
    globe.accessibilityIdentifier = "clarify.keyboard.recording-globe"
    globe.accessibilityLabel = L("Próximo teclado")
    globe.addTarget(self, action: #selector(nextRecordingKeyboard(_:event:)), for: .allTouchEvents)
    processingSpinner.color = .systemBackground; processingSpinner.hidesWhenStopped = true
    view.addSubview(recordingPanel); recordingPanel.translatesAutoresizingMaskIntoConstraints = false
    for element in [cancel, finishRecordingButton, waveform, recordingStatus, globe] {
      recordingPanel.addSubview(element); element.translatesAutoresizingMaskIntoConstraints = false
    }
    finishRecordingButton.addSubview(processingSpinner); processingSpinner.translatesAutoresizingMaskIntoConstraints = false
    NSLayoutConstraint.activate([
      recordingPanel.leadingAnchor.constraint(equalTo: view.leadingAnchor), recordingPanel.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      recordingPanel.topAnchor.constraint(equalTo: view.topAnchor), recordingPanel.bottomAnchor.constraint(equalTo: view.topAnchor, constant: KeyboardInputView.contentHeight),
      cancel.leadingAnchor.constraint(equalTo: recordingPanel.leadingAnchor, constant: 10), cancel.topAnchor.constraint(equalTo: recordingPanel.topAnchor, constant: 7),
      cancel.widthAnchor.constraint(equalToConstant: 44), cancel.heightAnchor.constraint(equalToConstant: 44),
      finishRecordingButton.trailingAnchor.constraint(equalTo: recordingPanel.trailingAnchor, constant: -10), finishRecordingButton.topAnchor.constraint(equalTo: cancel.topAnchor),
      finishRecordingButton.widthAnchor.constraint(equalToConstant: 44), finishRecordingButton.heightAnchor.constraint(equalToConstant: 44),
      processingSpinner.centerXAnchor.constraint(equalTo: finishRecordingButton.centerXAnchor), processingSpinner.centerYAnchor.constraint(equalTo: finishRecordingButton.centerYAnchor),
      waveform.centerXAnchor.constraint(equalTo: recordingPanel.centerXAnchor), waveform.centerYAnchor.constraint(equalTo: recordingPanel.centerYAnchor, constant: -16),
      waveform.widthAnchor.constraint(equalToConstant: 144), waveform.heightAnchor.constraint(equalToConstant: 56),
      recordingStatus.topAnchor.constraint(equalTo: waveform.bottomAnchor, constant: 12), recordingStatus.centerXAnchor.constraint(equalTo: recordingPanel.centerXAnchor),
      recordingStatus.leadingAnchor.constraint(greaterThanOrEqualTo: recordingPanel.leadingAnchor, constant: 60), recordingStatus.trailingAnchor.constraint(lessThanOrEqualTo: recordingPanel.trailingAnchor, constant: -60),
      globe.leadingAnchor.constraint(equalTo: cancel.leadingAnchor), globe.bottomAnchor.constraint(equalTo: recordingPanel.bottomAnchor, constant: -6),
      globe.widthAnchor.constraint(equalToConstant: 44), globe.heightAnchor.constraint(equalToConstant: 44)
    ])
  }
  private func updateRecordingPanel() {
    let pending = recordingRequest.action
    let visible = hasFullAccess && state.isLive && (state.phase.busy || pending != nil)
    let recording = [.recording, .locked].contains(state.phase) && pending != "cancel"
    let processing = [.transcribing, .rewriting].contains(state.phase) || pending == "finish"
    finishRecordingButton.isEnabled = recording && pending == nil
    finishRecordingButton.setImage(processing ? nil : UIImage(systemName: "checkmark"), for: .normal)
    finishRecordingButton.alpha = (recording && pending == nil) || processing ? 1 : 0.4
    if processing { processingSpinner.startAnimating() } else { processingSpinner.stopAnimating() }
    cancel.isEnabled = pending != "cancel"
    cancel.alpha = cancel.isEnabled ? 1 : 0.4
    globe.isHidden = !needsInputModeSwitchKey
    let caption = pending == "cancel" ? L("Cancelando…") : pending == "start" ? L("Preparando…") :
      state.phase == .rewriting ? L("Reescrevendo…") : processing ? L("Transcrevendo…") : L("Ouvindo…")
    if visible, recordingStatus.text != caption, UIAccessibility.isVoiceOverRunning {
      UIAccessibility.post(notification: .announcement, argument: caption)
    }
    recordingStatus.text = caption
    let level = visible && recording && !processing ? store?.audioMeter()?.level(for: state.operationID) ?? 0 : 0
    waveform.update(level: level, recording: attached && visible && recording && !processing)
    if visible != recordingPanelVisible {
      recordingPanelVisible = visible
      let change = { self.recordingPanel.isHidden = !visible; self.keys.isHidden = visible }
      if UIAccessibility.isReduceMotionEnabled || !attached { UIView.performWithoutAnimation(change) }
      else { UIView.transition(with: view, duration: 0.16, options: [.transitionCrossDissolve, .allowUserInteraction], animations: change) }
      if UIAccessibility.isVoiceOverRunning {
        let focus: UIView = visible ? recordingStatus : mic
        UIAccessibility.post(notification: .layoutChanged, argument: focus)
      }
    }
    if visible {
      // These may also be updated by a host selection callback while recording.
      for element in [status, detail, mic, insert, suggestions, addToDictionary, undoDictation] { element.isHidden = true }
      activation?.view.isHidden = true
      view.bringSubviewToFront(recordingPanel)
    } else { mic.isHidden = false; updateToolbar() }
  }
  @objc private func finishRecording() { send("finish") }
  @objc private func nextRecordingKeyboard(_ sender: UIButton, event: UIEvent?) {
    if let event { handleInputModeList(from: sender, with: event) } else { advanceToNextInputMode() }
  }
  @objc private func insertResult() {
    guard attached, let store = store, let text = state.text, !text.isEmpty,
          let id = state.operationID, !isCancelled(id), store.receipt() != id else { return }
    let current = store.snapshot()
    guard current.isLive, current.operationID == id, current.processingContext == state.processingContext,
      !current.phase.busy, current.text == text else { return }
    if state.textOperation, id != textOperationID || textSelection != currentTextSelection() { return }
    // Claim publication before insertion, so repeated polling cannot insert twice.
    do { try store.acknowledge(id) } catch { return }
    let proxy = textDocumentProxy, replaced = textDocumentProxy.selectedText ?? ""
    typing.reset(); dictationEdit = nil; proxy.insertText(text)
    dictationEdit = DictationEdit(text: text, replaced: replaced, proxy: proxy)
    insert.isHidden = true; updateCapitalization(); updateSuggestions()
  }
  private func updateSuggestions() {
    if typingVocabularyRevision != state.libraryRevision || Date().timeIntervalSince(typingVocabularyCheckedAt) >= 1 {
      let vocabulary = store?.keyboardDictionary()
      let pending = vocabulary.map { store?.keyboardAdditions(scope: $0.scope).map { $0.1.term } ?? [] } ?? []
      typing.protectVocabulary((vocabulary?.words.filter(\.enabled).map(\.term) ?? []) + pending)
      typingVocabularyRevision = state.libraryRevision; typingVocabularyCheckedAt = Date()
    }
    suggestions.arrangedSubviews.forEach { $0.removeFromSuperview() }
    for suggestion in typing.suggestions(textDocumentProxy) {
      let button = UIButton(type: .system)
      button.setTitle(suggestion.title, for: .normal); button.tintColor = .label
      button.titleLabel?.font = .systemFont(ofSize: 18)
      button.titleLabel?.adjustsFontSizeToFitWidth = true
      button.titleLabel?.minimumScaleFactor = 0.65
      button.accessibilityLabel = suggestion.undo ? L("Desfazer correção: {word}", ["word": suggestion.value]) : L("Usar {word}", ["word": suggestion.value])
      button.addAction(UIAction { [weak self] _ in
        guard let self = self else { return }
        self.dictationEdit = nil
        self.feedback.type(); self.typing.choose(suggestion, in: self.textDocumentProxy); self.updateCapitalization(); self.updateSuggestions()
      }, for: .touchUpInside)
      suggestions.addArrangedSubview(button)
    }
    updateToolbar()
  }
  private func updateToolbar(forceDictionaryRefresh: Bool = false) {
    if state.textOperation, state.phase.busy, let id = textOperationID, state.operationID == id,
      textSelection != currentTextSelection(), recordingRequest.action != "cancel" { send("cancel") }
    let proxy = textDocumentProxy
    let computerSelection = state.computerMode ? currentTextSelection() : nil
    let term = proxy.isSecureTextEntry == true ? nil : KeyboardSelection.term(proxy.selectedText)
    // UIKit has no document identifier while this controller is detached.
    // Access it only when the host actually supplies a text selection.
    let document = term == nil ? nil : proxy.documentIdentifier
    let selectionChanged = term != selectedTerm || selectedDocument != document
    if selectionChanged { dictionaryError = nil; dictionaryCheckedAt = .distantPast }
    selectedTerm = term; selectedDocument = document
    let available = !state.phase.busy && recordingRequest.action == nil && insert.isHidden
    let showDictionary = (state.computerMode ? computerSelection != nil : term != nil) && available
    if !applyingDictationEdit, let edit = dictationEdit, !edit.isCurrent(proxy) { dictationEdit = nil }
    let showEdit = dictationEdit != nil && available && !showDictionary
    undoDictation.isHidden = !showEdit
    if let edit = dictationEdit {
      undoDictation.setImage(UIImage(systemName: edit.removed ? "arrow.uturn.forward" : "arrow.uturn.backward"), for: .normal)
      undoDictation.accessibilityLabel = edit.removed ? L("Refazer ditado") : L("Desfazer ditado")
    }
    addToDictionary.isHidden = !showDictionary
    addToDictionary.showsMenuAsPrimaryAction = state.computerMode
    if showDictionary, state.computerMode {
      addToDictionary.isEnabled = hasFullAccess && state.isLive
      addToDictionary.setTitle(L("Texto selecionado"), for: .normal)
      addToDictionary.setImage(UIImage(systemName: "wand.and.stars"), for: .normal)
      addToDictionary.backgroundColor = .label; addToDictionary.tintColor = .systemBackground
      addToDictionary.setTitleColor(.systemBackground, for: .normal)
      addToDictionary.menu = UIMenu(children: [
        UIAction(title: L("Reescrever")) { [weak self] _ in self?.processSelection("rewrite", language: ClarifyLocale.language) },
        UIMenu(title: L("Traduzir"), children: [("pt", "Português"), ("en", "English"), ("es", "Español")].map { language, title in
          UIAction(title: title) { [weak self] _ in self?.processSelection("translate", language: language) }
        })
      ])
      dictionaryTrailing?.constant = -8
    } else if showDictionary, let term {
      addToDictionary.menu = nil
      // Selection and taps refresh immediately. Idle polling must not scan the
      // vocabulary inbox on every 150 ms keyboard state refresh.
      if selectionChanged || forceDictionaryRefresh || dictionaryRevision != state.libraryRevision || Date().timeIntervalSince(dictionaryCheckedAt) >= 1 {
        dictionaryContext = store?.keyboardDictionary()
        selectedScope = dictionaryContext?.scope
        selectedTermSaved = dictionaryContext.map { store?.isKeyboardTermSaved(term, context: $0) == true } ?? false
        dictionaryCheckedAt = Date(); dictionaryRevision = state.libraryRevision
      }
      let saved = selectedTermSaved
      let title = saved ? L("Salvo") : dictionaryError == nil ? L("Adicionar ao dicionário") : L("Tentar novamente")
      let titleChanged = addToDictionary.title(for: .normal) != title
      // A system button crossfades title changes. Confirm the durable save
      // immediately, and do not restart that transition on keyboard polling.
      UIView.performWithoutAnimation {
        addToDictionary.isEnabled = !saved && hasFullAccess && dictionaryContext != nil
        addToDictionary.backgroundColor = .label
        addToDictionary.setTitleColor(.systemBackground, for: .normal)
        addToDictionary.setTitleColor(.systemBackground, for: .disabled)
        if titleChanged {
          addToDictionary.setTitle(title, for: .normal)
          addToDictionary.setImage(UIImage(systemName: saved ? "checkmark" : "plus"), for: .normal)
        }
        addToDictionary.tintColor = .systemBackground
        addToDictionary.semanticContentAttribute = .forceRightToLeft
        if titleChanged { view.layoutIfNeeded() }
      }
      addToDictionary.accessibilityLabel = title
      addToDictionary.accessibilityHint = dictionaryError ?? term
      dictionaryTrailing?.constant = state.isLive ? -8 : -82
    }
    let showSuggestions = !showDictionary && !showEdit && !suggestions.arrangedSubviews.isEmpty && available
    let showingError = hasFullAccess && state.isLive && state.phase == .error
    suggestions.isHidden = !showSuggestions || showingError
    let covered = showDictionary || (!suggestions.isHidden) || showEdit
    // Keep the toolbar and keyboard heights fixed. Errors replace the redundant
    // generic title with the complete cause in the same 44-point row.
    status.isHidden = covered || showingError || status.text?.isEmpty != false; detail.isHidden = covered
    detail.numberOfLines = showingError ? 3 : 1
    detail.lineBreakMode = showingError ? .byWordWrapping : .byTruncatingTail
    detail.textColor = showingError ? .label : .secondaryLabel
    // Remove an alternative before enabling its replacement. Activating both
    // even briefly imposes incompatible required positions on the same label.
    let vertical = showingError ? detailCenter : detailTop
    if vertical?.isActive == false {
      (showingError ? detailTop : detailCenter)?.isActive = false
      vertical?.isActive = true
    }
    let wideError = showingError && insert.isHidden
    let trailing = wideError ? errorTrailing : detailTrailing
    if trailing?.isActive == false {
      (wideError ? detailTrailing : errorTrailing)?.isActive = false
      trailing?.isActive = true
    }
    if recordingPanelVisible {
      for element in [status, detail, mic, insert, suggestions, addToDictionary, undoDictation] { element.isHidden = true }
    }
  }
  private func toggleDictationEdit() {
    guard !state.phase.busy, !applyingDictationEdit, var edit = dictationEdit else { return }
    applyingDictationEdit = true
    dictationEdit = edit.toggle(in: textDocumentProxy) ? edit : nil
    applyingDictationEdit = false
    typing.reset(); feedback.type(); updateCapitalization(); updateSuggestions()
  }
  private func saveSelectedTerm() {
    guard !state.computerMode else { return }
    guard let term = selectedTerm, let scope = selectedScope, let store,
          hasFullAccess, selectedDocument == textDocumentProxy.documentIdentifier,
          term == KeyboardSelection.term(textDocumentProxy.selectedText), !state.phase.busy else { updateToolbar(); return }
    do {
      try store.addKeyboardTerm(term, scope: scope); dictionaryError = nil
      // Protect a durable keyboard addition before the next key, including
      // hosts that do not send a selection-change callback after the save.
      typingVocabularyCheckedAt = .distantPast; updateSuggestions(); feedback.type()
    }
    catch { dictionaryError = error.localizedDescription; UIAccessibility.post(notification: .announcement, argument: dictionaryError) }
    updateToolbar(forceDictionaryRefresh: true)
  }
  @objc private func cancelRecording() { send("cancel") }
}

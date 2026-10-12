import UIKit
import SwiftUI

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
  private let icon = UIImageView()
  private let tips = UIImageView(image: UIImage(systemName: "chevron.up.2"))
  private var mode = ""
  override init(frame: CGRect) {
    super.init(frame: frame)
    isUserInteractionEnabled = false; isAccessibilityElement = false
    for image in [icon, tips] {
      image.tintColor = .systemBackground; image.contentMode = .scaleAspectFit
      image.translatesAutoresizingMaskIntoConstraints = false; addSubview(image)
    }
    tips.alpha = 0
    NSLayoutConstraint.activate([
      icon.widthAnchor.constraint(equalToConstant: 22), icon.heightAnchor.constraint(equalToConstant: 22),
      icon.centerXAnchor.constraint(equalTo: centerXAnchor), icon.centerYAnchor.constraint(equalTo: centerYAnchor),
      tips.widthAnchor.constraint(equalToConstant: 11), tips.heightAnchor.constraint(equalToConstant: 10),
      tips.centerXAnchor.constraint(equalTo: centerXAnchor), tips.topAnchor.constraint(equalTo: topAnchor, constant: 5)
    ])
    update(recording: false, locked: false, animated: false)
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
  func update(recording: Bool, locked: Bool, animated: Bool = true) {
    let next = locked ? "locked" : recording ? "recording" : "idle"
    guard mode != next else { return }; mode = next
    icon.image = UIImage(systemName: locked ? "paperplane.fill" : "mic.fill")
    let change = {
      self.tips.alpha = recording && !locked ? 0.8 : 0
      self.icon.transform = recording && !locked ? CGAffineTransform(translationX: 0, y: 5).scaledBy(x: 0.75, y: 0.75) : .identity
    }
    if animated && !UIAccessibility.isReduceMotionEnabled {
      UIView.animate(withDuration: 0.18, delay: 0, options: [.beginFromCurrentState, .allowUserInteraction, .curveEaseOut], animations: change)
    } else { change() }
  }
}

final class RecordControl: UIControl {
  var onAction: ((String) -> Void)?
  private var gesture = RecordGesture()
  var locked: Bool { get { gesture.locked } set { gesture.locked = newValue } }
  private var origin = CGPoint.zero
  var holding: Bool { gesture.holding }
  func reset() { gesture.reset() }
  override func accessibilityActivate() -> Bool {
    guard isEnabled else { return false }
    if locked { reset(); onAction?("finish") }
    else { onAction?(gesture.press()); locked = true; onAction?("lock") }
    return true
  }
  override func beginTracking(_ touch: UITouch, with event: UIEvent?) -> Bool {
    origin = touch.location(in: self.superview)
    let action = gesture.press(); onAction?(action); return action == "start"
  }
  override func continueTracking(_ touch: UITouch, with event: UIEvent?) -> Bool {
    if let action = gesture.move(vertical: Double(touch.location(in: self.superview).y - origin.y)) { onAction?(action) }
    return true
  }
  override func endTracking(_ touch: UITouch?, with event: UIEvent?) {
    if let action = gesture.release() { onAction?(action) }
  }
  override func cancelTracking(with event: UIEvent?) {
    reset(); onAction?("cancel")
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
  private let insert = UIButton(type: .system)
  private let cancel = UIButton(type: .system)
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
    detail.font = .systemFont(ofSize: 11); detail.textColor = .secondaryLabel
    detail.numberOfLines = 1; detail.lineBreakMode = .byTruncatingTail
    mic.backgroundColor = .label; mic.layer.cornerRadius = 22
    mic.isAccessibilityElement = true; mic.accessibilityTraits = .button
    mic.accessibilityIdentifier = "clarify.keyboard.record"
    mic.accessibilityLabel = L("Gravar")
    mic.accessibilityHint = L("Segure para falar. Deslize para cima para travar.")
    mic.onAction = { [weak self] action in self?.send(action) }
    mic.addSubview(glyph); glyph.translatesAutoresizingMaskIntoConstraints = false
    NSLayoutConstraint.activate([
      glyph.leadingAnchor.constraint(equalTo: mic.leadingAnchor), glyph.trailingAnchor.constraint(equalTo: mic.trailingAnchor),
      glyph.topAnchor.constraint(equalTo: mic.topAnchor), glyph.bottomAnchor.constraint(equalTo: mic.bottomAnchor)
    ])
    insert.setTitle(L("Inserir"), for: .normal)
    insert.isHidden = true; cancel.isHidden = true
    insert.titleLabel?.font = .systemFont(ofSize: 13, weight: .medium)
    insert.addTarget(self, action: #selector(insertResult), for: .touchUpInside)
    cancel.setImage(UIImage(systemName: "xmark"), for: .normal); cancel.accessibilityLabel = L("Cancelar gravação")
    cancel.tintColor = .secondaryLabel
    cancel.addTarget(self, action: #selector(cancelRecording), for: .touchUpInside)
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
    for element in [status, detail, mic, insert, keys, cancel, suggestions, addToDictionary, undoDictation] {
      element.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(element)
    }
    NSLayoutConstraint.activate([
      mic.topAnchor.constraint(equalTo: view.topAnchor, constant: 7), mic.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -10),
      mic.widthAnchor.constraint(equalToConstant: 44), mic.heightAnchor.constraint(equalToConstant: 44),
      status.topAnchor.constraint(equalTo: view.topAnchor, constant: 10), status.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 12),
      status.trailingAnchor.constraint(lessThanOrEqualTo: insert.leadingAnchor, constant: -4),
      detail.topAnchor.constraint(equalTo: status.bottomAnchor, constant: 3), detail.leadingAnchor.constraint(equalTo: status.leadingAnchor),
      detail.trailingAnchor.constraint(equalTo: insert.leadingAnchor, constant: -4),
      insert.centerYAnchor.constraint(equalTo: mic.centerYAnchor), insert.trailingAnchor.constraint(equalTo: cancel.leadingAnchor),
      insert.widthAnchor.constraint(equalToConstant: 48),
      cancel.centerYAnchor.constraint(equalTo: mic.centerYAnchor), cancel.trailingAnchor.constraint(equalTo: mic.leadingAnchor, constant: -2),
      cancel.widthAnchor.constraint(equalToConstant: 44), cancel.heightAnchor.constraint(equalToConstant: 44),
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
    requestSupplementaryLexicon { [weak self] lexicon in
      DispatchQueue.main.async { [weak self] in
        self?.typing.protect(lexicon); self?.updateSuggestions()
      }
    }
  }
  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    if keys.needsGlobe != needsInputModeSwitchKey {
      UIView.performWithoutAnimation { keys.needsGlobe = needsInputModeSwitchKey; keys.rebuild(); keys.layoutIfNeeded() }
    }
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
    super.viewWillAppear(animated); attached = true; feedback.prepare(); refresh(); updateCapitalization(); updateSuggestions(); timer?.invalidate()
    timer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in self?.refresh() }
  }
  override func viewDidDisappear(_ animated: Bool) {
    super.viewDidDisappear(animated); attached = false; timer?.invalidate(); timer = nil
    dictationEdit = nil; undoDictation.isHidden = true
    invalidateActivationSource()
    typing.reset()
    suggestions.arrangedSubviews.forEach { $0.removeFromSuperview() }
    if !mic.locked { send("cancel") }
  }
  deinit { timer?.invalidate() }
  private func send(_ action: String) {
    guard hasFullAccess, state.isLive, let store = store else { return }
    if action == "start" {
      guard !state.phase.busy else { return }
      dictationEdit = nil
      operationID = UUID().uuidString; documentID = textDocumentProxy.documentIdentifier
    }
    guard let id = operationID else { return }
    do {
      try store.send(action, operationID: id)
      feedback.record(action)
      glyph.update(recording: mic.holding, locked: mic.locked)
    }
    catch { detail.text = L("Abra o Clarify para configurar o teclado.") }
  }
  private func refresh() {
    state = store?.snapshot() ?? DictationSnapshot()
    if state.isLive, state.phase.busy, operationID != state.operationID {
      // Recover cancellation after iOS recreates the extension during processing.
      operationID = state.operationID; documentID = nil
    }
    // Do not reset a held gesture while the host is accepting its start command.
    if !state.isLive || (state.operationID == operationID && !state.phase.busy && !mic.holding) { mic.reset() }
    if state.isLive, [.recording, .locked].contains(state.phase), !mic.holding {
      // A new keyboard instance must be able to stop an existing locked clip.
      if operationID != state.operationID { documentID = nil }
      operationID = state.operationID
      mic.locked = true
    }
    let available = hasFullAccess && state.configured
    activation?.view.isHidden = !hasFullAccess || state.isLive
    mic.isEnabled = available && state.isLive && ![.transcribing, .rewriting].contains(state.phase)
    insert.isHidden = !state.isLive || state.text?.isEmpty != false || state.phase.busy || state.operationID == store?.receipt()
    cancel.isHidden = !state.isLive || !state.phase.busy
    if !hasFullAccess {
      status.text = L("Ative o Acesso Total"); detail.text = L("Ajustes > Geral > Teclado > Clarify")
    } else if !state.configured {
      status.text = L("Configure sua chave Groq"); detail.text = L("Abra o Clarify para configurar.")
    } else if !state.isLive {
      status.text = L("Ative o microfone"); detail.text = L("Toque em Começar.")
    } else {
      switch state.phase {
      case .recording: status.text = L("Ouvindo…"); detail.text = L("Deslize para cima para travar ↑")
      case .locked: status.text = L("Gravação travada"); detail.text = L("Toque para finalizar e transcrever.")
      case .transcribing: status.text = L("Transcrevendo…"); detail.text = nil
      case .rewriting: status.text = L("Reescrevendo…"); detail.text = nil
      case .error: status.text = L("Não foi possível concluir"); detail.text = state.message
      default: status.text = "Clarify"; detail.text = L("Segure para falar · Trave para cima ↑")
      }
    }
    glyph.update(recording: mic.holding, locked: mic.locked)
    mic.accessibilityLabel = mic.locked ? L("Finalizar gravação") : L("Gravar")
    updateToolbar()
    if attached, state.phase == .ready, let id = operationID, state.operationID == id,
       documentID == textDocumentProxy.documentIdentifier, store?.receipt() != id { insertResult() }
  }
  @objc private func insertResult() {
    guard attached, let store = store, let text = state.text, !text.isEmpty,
          let id = state.operationID, store.receipt() != id else { return }
    // Claim publication before insertion, so repeated polling cannot insert twice.
    do { try store.acknowledge(id) } catch { return }
    let proxy = textDocumentProxy, replaced = textDocumentProxy.selectedText ?? ""
    typing.reset(); dictationEdit = nil; proxy.insertText(text)
    dictationEdit = DictationEdit(text: text, replaced: replaced, proxy: proxy)
    insert.isHidden = true; updateSuggestions()
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
    let proxy = textDocumentProxy
    let term = proxy.isSecureTextEntry == true ? nil : KeyboardSelection.term(proxy.selectedText)
    // UIKit has no document identifier while this controller is detached.
    // Access it only when the host actually supplies a text selection.
    let document = term == nil ? nil : proxy.documentIdentifier
    let selectionChanged = term != selectedTerm || selectedDocument != document
    if selectionChanged { dictionaryError = nil; dictionaryCheckedAt = .distantPast }
    selectedTerm = term; selectedDocument = document
    let available = !state.phase.busy && !mic.holding && !mic.locked && insert.isHidden
    let showDictionary = term != nil && available
    if !applyingDictationEdit, let edit = dictationEdit, !edit.isCurrent(proxy) { dictationEdit = nil }
    let showEdit = dictationEdit != nil && available && !showDictionary
    undoDictation.isHidden = !showEdit
    if let edit = dictationEdit {
      undoDictation.setImage(UIImage(systemName: edit.removed ? "arrow.uturn.forward" : "arrow.uturn.backward"), for: .normal)
      undoDictation.accessibilityLabel = edit.removed ? L("Refazer ditado") : L("Desfazer ditado")
    }
    addToDictionary.isHidden = !showDictionary
    if showDictionary, let term {
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
    suggestions.isHidden = !showSuggestions
    status.isHidden = showDictionary || showSuggestions || showEdit; detail.isHidden = status.isHidden
  }
  private func toggleDictationEdit() {
    guard !state.phase.busy, !applyingDictationEdit, var edit = dictationEdit else { return }
    applyingDictationEdit = true
    dictationEdit = edit.toggle(in: textDocumentProxy) ? edit : nil
    applyingDictationEdit = false
    typing.reset(); feedback.type(); updateSuggestions()
  }
  private func saveSelectedTerm() {
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
  @objc private func cancelRecording() { mic.reset(); send("cancel") }
}

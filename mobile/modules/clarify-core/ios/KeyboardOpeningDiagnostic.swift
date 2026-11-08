import UIKit
import QuartzCore

// Temporary device diagnostic. Does not alter the installed keyboard, its host
// sizing, microphone state, or the user's library. Only geometry is exported.
struct KeyboardOpeningReport: Encodable {
  struct Frame: Encodable {
    let elapsed: Double
    let opening: Int
    let phase: String
    var displayElapsed: Double?
    var targetElapsed: Double?
    let guideHeight: Double
    let composerHeight: Double
  }
  struct Opening: Encodable {
    let index: Int
    let peakGuideHeight: Double
    let settledGuideHeight: Double
    let peakComposerHeight: Double
    let settledComposerHeight: Double
  }
  let schema = 1
  let ios: String
  let appVersion: String
  let appBuild: String
  // This is the user's label. Public UIKit does not identify the active
  // third-party keyboard. Do not represent it as automatic identification.
  let keyboardLabel: String
  let screenWidth: Double
  let screenHeight: Double
  let requestedFPS: Int
  var frames: [Frame] = []
  var openings: [Opening] = []
  var outcome = "running"

  mutating func append(_ frame: Frame) -> Bool {
    guard frames.count < 12_000, frame.elapsed.isFinite,
          frame.guideHeight.isFinite, frame.composerHeight.isFinite,
          frame.displayElapsed?.isFinite != false, frame.targetElapsed?.isFinite != false else { return false }
    frames.append(frame)
    return true
  }
  mutating func completeOpening(_ index: Int) {
    let samples = frames.filter { $0.opening == index && $0.phase == "opening" }
    guard let last = samples.last else { return }
    openings.append(Opening(index: index,
      peakGuideHeight: samples.map(\.guideHeight).max() ?? last.guideHeight,
      settledGuideHeight: last.guideHeight,
      peakComposerHeight: samples.map(\.composerHeight).max() ?? last.composerHeight,
      settledComposerHeight: last.composerHeight))
  }
}

@MainActor
final class KeyboardOpeningDiagnostic: UIViewController {
  static let openingCount = 10
  static let phaseTimeout: CFTimeInterval = 10
  private let field = UITextField()
  private let choice = UISegmentedControl(items: ["Apple", "Clarify", "Wispr Flow"])
  private let status = UILabel()
  private let runButton = UIButton(type: .system)
  private let shareButton = UIButton(type: .system)
  private var link: CADisplayLink?
  private var observers: [NSObjectProtocol] = []
  private(set) var report: KeyboardOpeningReport?
  private var temporaryExport: URL?
  private var started: CFTimeInterval = 0
  private var phaseStarted: CFTimeInterval = 0
  private var opening = 0
  private var phase = ""
  private var stableFrames = 0
  private var previousGuide: CGFloat = -1
  private var previousComposer: CGFloat = -1
  private var didShow = false

  override func viewDidLoad() {
    super.viewDidLoad()
    title = L("Teste de abertura do teclado")
    view.backgroundColor = .systemBackground
    navigationItem.rightBarButtonItem = UIBarButtonItem(systemItem: .close, primaryAction: UIAction { [weak self] _ in
      self?.stop("cancelled"); self?.dismiss(animated: true)
    })
    let instructions = UILabel()
    instructions.text = L("Escolha abaixo o teclado que vai testar. Toque no campo e use o globo para selecionar esse mesmo teclado. Depois, inicie o teste. Não digite durante as dez aberturas.")
    instructions.font = .preferredFont(forTextStyle: .body)
    instructions.adjustsFontForContentSizeCategory = true
    instructions.numberOfLines = 0
    let privacy = UILabel()
    privacy.text = L("O resultado contém apenas medidas e tempos. Nenhum áudio ou texto digitado é coletado.")
    privacy.font = .preferredFont(forTextStyle: .footnote)
    privacy.adjustsFontForContentSizeCategory = true
    privacy.textColor = .secondaryLabel
    privacy.numberOfLines = 0
    choice.selectedSegmentIndex = 1
    choice.accessibilityLabel = L("Teclado em teste")
    status.font = .preferredFont(forTextStyle: .footnote)
    status.adjustsFontForContentSizeCategory = true
    status.numberOfLines = 0
    status.text = L("Selecione o teclado no campo abaixo.")
    runButton.setTitle(L("Testar dez aberturas"), for: .normal)
    runButton.addAction(UIAction { [weak self] _ in self?.begin() }, for: .touchUpInside)
    shareButton.setTitle(L("Compartilhar resultado"), for: .normal)
    shareButton.addAction(UIAction { [weak self] _ in self?.share() }, for: .touchUpInside)
    shareButton.isEnabled = false
    let stack = UIStackView(arrangedSubviews: [instructions, choice, runButton, status, shareButton, privacy])
    stack.axis = .vertical; stack.spacing = 16
    stack.translatesAutoresizingMaskIntoConstraints = false
    // The controls can scroll on smaller phones or with large accessibility
    // text. The measured composer stays outside the scroll view.
    let scroll = UIScrollView()
    scroll.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(scroll); scroll.addSubview(stack)
    field.borderStyle = .roundedRect
    field.placeholder = L("Toque para selecionar o teclado")
    field.accessibilityIdentifier = "clarify.keyboard.diagnostic.composer"
    field.autocapitalizationType = .sentences
    field.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(field)
    NSLayoutConstraint.activate([
      scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      scroll.bottomAnchor.constraint(equalTo: field.topAnchor, constant: -16),
      stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 16),
      stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 20),
      stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -20),
      stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -16),
      stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -40),
      field.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
      field.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
      field.heightAnchor.constraint(equalToConstant: 44),
      field.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor, constant: -8),
    ])
    observers.append(NotificationCenter.default.addObserver(forName: UIResponder.keyboardDidShowNotification, object: nil, queue: .main) { [weak self] _ in
      MainActor.assumeIsolated { if self?.phase == "opening" { self?.didShow = true } }
    })
    observers.append(NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
      MainActor.assumeIsolated { self?.stop("interrupted") }
    })
  }

  override func viewWillDisappear(_ animated: Bool) {
    super.viewWillDisappear(animated)
    // A share sheet can disappear this controller after a completed run. The
    // report is retained, while an active measurement always stops.
    stop("cancelled")
  }

  private func begin() {
    guard link == nil else { return }
    guard field.isFirstResponder,
          view.keyboardLayoutGuide.layoutFrame.height > view.safeAreaInsets.bottom + 100 else {
      status.text = L("Primeiro, abra o campo e selecione o teclado pelo globo.")
      return
    }
    removeExport()
    let info = Bundle.main.infoDictionary ?? [:]
    report = KeyboardOpeningReport(ios: UIDevice.current.systemVersion,
      appVersion: info["CFBundleShortVersionString"] as? String ?? "",
      appBuild: info["CFBundleVersion"] as? String ?? "",
      keyboardLabel: choice.titleForSegment(at: choice.selectedSegmentIndex) ?? "",
      screenWidth: Double(view.bounds.width), screenHeight: Double(view.bounds.height),
      requestedFPS: view.window?.windowScene?.screen.maximumFramesPerSecond ?? 60)
    started = CACurrentMediaTime(); opening = 0
    choice.isEnabled = false; runButton.isEnabled = false; shareButton.isEnabled = false
    phase = "closing"; resetPhase()
    field.resignFirstResponder()
    // A weak proxy prevents CADisplayLink from retaining a dismissed screen.
    let proxy = KeyboardDiagnosticDisplayTarget(self)
    let display = CADisplayLink(target: proxy, selector: #selector(KeyboardDiagnosticDisplayTarget.tick(_:)))
    let maximum = Float(report?.requestedFPS ?? 60)
    display.preferredFrameRateRange = CAFrameRateRange(minimum: min(60, maximum), maximum: maximum, preferred: maximum)
    display.add(to: .main, forMode: .common); link = display
  }

  private func resetPhase() {
    phaseStarted = CACurrentMediaTime(); stableFrames = 0
    previousGuide = -1; previousComposer = -1; didShow = false
  }

  fileprivate func sample(_ display: CADisplayLink) {
    guard link != nil else { return }
    let time = CACurrentMediaTime()
    let guide = view.keyboardLayoutGuide.layoutFrame.height
    let bottom = field.layer.presentation()?.frame.maxY ?? field.frame.maxY
    let composer = view.bounds.maxY - bottom - 8
    let frame = KeyboardOpeningReport.Frame(elapsed: time - started, opening: opening,
      phase: phase, displayElapsed: display.timestamp - started, targetElapsed: display.targetTimestamp - started,
      guideHeight: Double(guide), composerHeight: Double(composer))
    guard report?.append(frame) == true else { stop("sample-limit"); return }
    if time - phaseStarted > Self.phaseTimeout { stop("timeout"); return }
    let steady = abs(previousGuide - guide) < 0.5 && abs(previousComposer - composer) < 0.5
    previousGuide = guide; previousComposer = composer
    let closed = guide <= view.safeAreaInsets.bottom + 2 && composer <= view.safeAreaInsets.bottom + 2
    let shown = didShow && guide > view.safeAreaInsets.bottom + 100
    stableFrames = steady && (phase == "closing" ? closed : shown) ? stableFrames + 1 : 0
    guard stableFrames >= 12 else { return }
    if phase == "closing" {
      opening += 1; phase = "opening"; resetPhase()
      status.text = L("Abertura {v0} de 10", ["v0": String(opening)])
      guard field.becomeFirstResponder() else { stop("focus-failed"); return }
    } else {
      report?.completeOpening(opening)
      if opening == Self.openingCount { stop("completed"); return }
      phase = "closing"; resetPhase(); field.resignFirstResponder()
    }
  }

  private func stop(_ outcome: String) {
    guard link != nil else { return }
    link?.invalidate(); link = nil
    report?.outcome = outcome
    choice.isEnabled = true; runButton.isEnabled = true; shareButton.isEnabled = true
    status.text = outcome == "completed" ? L("Teste concluído. Compartilhe o resultado e repita com os outros teclados.")
      : L("Teste interrompido. Você pode compartilhar o resultado parcial ou tentar novamente.")
  }

  private func share() {
    guard let report, link == nil else { return }
    do {
      removeExport()
      let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
      let url = FileManager.default.temporaryDirectory.appendingPathComponent("clarify-keyboard-\(UUID().uuidString).json")
      try encoder.encode(report).write(to: url, options: [.atomic, .completeFileProtection])
      temporaryExport = url
      field.resignFirstResponder()
      let sheet = UIActivityViewController(activityItems: [url], applicationActivities: nil)
      sheet.popoverPresentationController?.sourceView = shareButton
      sheet.completionWithItemsHandler = { [weak self] _, _, _, _ in
        Task { @MainActor [weak self] in self?.removeExport() }
      }
      present(sheet, animated: true)
    } catch {
      status.text = L("Não foi possível exportar o teste. Tente novamente.")
    }
  }

  private func removeExport() {
    if let temporaryExport { try? FileManager.default.removeItem(at: temporaryExport) }
    temporaryExport = nil
  }

  deinit {
    link?.invalidate()
    observers.forEach(NotificationCenter.default.removeObserver)
    if let temporaryExport { try? FileManager.default.removeItem(at: temporaryExport) }
  }
}

@MainActor
private final class KeyboardDiagnosticDisplayTarget: NSObject {
  weak var owner: KeyboardOpeningDiagnostic?
  init(_ owner: KeyboardOpeningDiagnostic) { self.owner = owner }
  @objc func tick(_ display: CADisplayLink) { owner?.sample(display) }
}

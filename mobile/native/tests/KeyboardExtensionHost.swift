import UIKit

@main
final class KeyboardHostApp: UIResponder, UIApplicationDelegate {}

final class KeyboardHostScene: UIResponder, UIWindowSceneDelegate {
  var window: UIWindow?
  func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
    guard let scene = scene as? UIWindowScene else { return }
    let window = UIWindow(windowScene: scene)
    window.rootViewController = KeyboardHostController(); window.makeKeyAndVisible(); self.window = window
  }
}

final class KeyboardHostController: UIViewController {
  private let field = UITextField()
  private let trace = UILabel()
  private let returnTrace = UILabel()
  private var heights: [CGFloat] = []
  private var sampledHeights: [CGFloat] = []
  private var visibleHeights: [CGFloat] = []
  private var displayLink: CADisplayLink?
  private var lastWindowHeight: CGFloat = -1
  private var composerBottom: NSLayoutConstraint?
  override func viewDidLoad() {
    super.viewDidLoad(); view.backgroundColor = .systemBackground
    field.borderStyle = .roundedRect; field.placeholder = "Type here"; field.accessibilityIdentifier = "composer"
    field.autocapitalizationType = .sentences
    field.isSecureTextEntry = ProcessInfo.processInfo.arguments.contains("--system-keyboard")
    trace.text = "Keyboard frame trace"; trace.accessibilityIdentifier = "keyboard-frames"
    returnTrace.text = "Return trace"; returnTrace.accessibilityIdentifier = "return-trace"
    NotificationCenter.default.addObserver(self, selector: #selector(publishReturnTrace), name: UIApplication.didBecomeActiveNotification, object: nil)
    let dismiss = UIButton(type: .system); dismiss.setTitle("Dismiss", for: .normal)
    dismiss.addAction(UIAction { [weak self] _ in self?.field.resignFirstResponder() }, for: .touchUpInside)
    let reset = UIButton(type: .system); reset.setTitle("Reset trace", for: .normal)
    reset.addAction(UIAction { [weak self] _ in self?.heights = []; self?.sampledHeights = []; self?.visibleHeights = []; self?.publishTrace() }, for: .touchUpInside)
    let activate = UIButton(type: .system); activate.setTitle("Open activation fixture", for: .normal)
    activate.addAction(UIAction { _ in UIApplication.shared.open(URL(string: "clarify://fixture-preflight")!) }, for: .touchUpInside)
    for element in [field, trace, returnTrace, dismiss, reset, activate] { element.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(element) }
    let notificationComposer = Bundle.main.object(forInfoDictionaryKey: "ClarifyFixtureNotificationComposer") as? Bool == true
    let bottom = notificationComposer
      ? field.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -8)
      : field.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor, constant: -8)
    if notificationComposer { composerBottom = bottom }
    NSLayoutConstraint.activate([
      trace.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 16),
      trace.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20), trace.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
      dismiss.topAnchor.constraint(equalTo: trace.bottomAnchor, constant: 20), dismiss.leadingAnchor.constraint(equalTo: trace.leadingAnchor),
      reset.topAnchor.constraint(equalTo: dismiss.topAnchor), reset.trailingAnchor.constraint(equalTo: trace.trailingAnchor),
      returnTrace.topAnchor.constraint(equalTo: reset.bottomAnchor, constant: 16), returnTrace.leadingAnchor.constraint(equalTo: trace.leadingAnchor),
      activate.topAnchor.constraint(equalTo: returnTrace.bottomAnchor, constant: 16), activate.leadingAnchor.constraint(equalTo: trace.leadingAnchor),
      field.leadingAnchor.constraint(equalTo: trace.leadingAnchor), field.trailingAnchor.constraint(equalTo: trace.trailingAnchor),
      field.heightAnchor.constraint(equalToConstant: 44), bottom
    ])
    NotificationCenter.default.addObserver(self, selector: #selector(frameChanged), name: UIResponder.keyboardWillChangeFrameNotification, object: nil)
    displayLink = CADisplayLink(target: self, selector: #selector(sampleFrame)); displayLink?.add(to: .main, forMode: .common)
  }
  @objc private func publishReturnTrace() {
    if let values = SharedState()?.read("return-trace.json", as: [String: String].self),
       let data = try? JSONSerialization.data(withJSONObject: values) { returnTrace.accessibilityValue = String(data: data, encoding: .utf8) }
  }
  @objc private func sampleFrame() {
    guard field.isFirstResponder else { return }
    let height = view.keyboardLayoutGuide.layoutFrame.height
    let visible = view.bounds.maxY - (field.layer.presentation()?.frame.maxY ?? field.frame.maxY) - 8
    if height != lastWindowHeight {
      lastWindowHeight = height
      // Fixture-only public view geometry. No text or private method is read.
      NSLog("ClarifyFixtureHostWindow time=%.6f guide=%.3f composer=%.3f", CACurrentMediaTime(), height, visible)
      let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
      for window in windows {
        var count = 0
        func geometry(_ node: UIView, depth: Int) {
          guard depth < 9, count < 160 else { return }; count += 1
          NSLog("ClarifyFixtureHostNode depth=%d type=%@ model=%@ presentation=%@", depth,
            String(describing: type(of: node)), String(describing: node.convert(node.bounds, to: window)),
            node.layer.presentation().flatMap { layer in window.layer.presentation().map { String(describing: layer.convert(layer.bounds, to: $0)) } } ?? "unavailable")
          for child in node.subviews { geometry(child, depth: depth + 1) }
        }
        geometry(window, depth: 0)
      }
    }
    let changed = (height > 0 && sampledHeights.last != height) || (visible > 0 && visibleHeights.last != visible)
    guard changed else { return }
    if height > 0, sampledHeights.last != height { sampledHeights.append(height) }
    if visible > 0, visibleHeights.last != visible { visibleHeights.append(visible) }
    publishTrace()
  }
  private func publishTrace() {
    let values = ["notifications": heights.map(Double.init), "displayFrames": sampledHeights.map(Double.init), "visibleFrames": visibleHeights.map(Double.init)]
    if let data = try? JSONSerialization.data(withJSONObject: values) { trace.accessibilityValue = String(data: data, encoding: .utf8) }
  }
  @objc private func frameChanged(_ note: Notification) {
    guard let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
    let height = view.bounds.intersection(view.convert(frame, from: nil)).height
    if field.isFirstResponder, height > 0 { heights.append(height) }
    if let bottom = composerBottom {
      view.layoutIfNeeded()
      bottom.constant = -8 - max(0, height - view.safeAreaInsets.bottom)
      let duration = (note.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? NSNumber)?.doubleValue ?? 0
      let curve = (note.userInfo?[UIResponder.keyboardAnimationCurveUserInfoKey] as? NSNumber)?.uintValue ?? 0
      UIView.animate(withDuration: duration, delay: 0,
        options: [UIView.AnimationOptions(rawValue: curve << 16), .beginFromCurrentState, .allowUserInteraction]) {
        self.view.layoutIfNeeded()
      }
    }
    publishTrace()
  }
}

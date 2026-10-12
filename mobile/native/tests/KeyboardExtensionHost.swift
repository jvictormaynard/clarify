import UIKit

@main
final class KeyboardHostApp: UIResponder, UIApplicationDelegate {
  var window: UIWindow?
  func application(_ application: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
    let window = UIWindow(frame: UIScreen.main.bounds)
    window.rootViewController = KeyboardHostController(); window.makeKeyAndVisible(); self.window = window
    return true
  }
}

final class KeyboardHostController: UIViewController {
  private let field = UITextField()
  private let trace = UILabel()
  private var heights: [CGFloat] = []
  private var sampledHeights: [CGFloat] = []
  private var displayLink: CADisplayLink?
  override func viewDidLoad() {
    super.viewDidLoad(); view.backgroundColor = .systemBackground
    field.borderStyle = .roundedRect; field.placeholder = "Type here"; field.accessibilityIdentifier = "composer"
    trace.text = "Keyboard frame trace"; trace.accessibilityIdentifier = "keyboard-frames"
    let dismiss = UIButton(type: .system); dismiss.setTitle("Dismiss", for: .normal)
    dismiss.addAction(UIAction { [weak self] _ in self?.field.resignFirstResponder() }, for: .touchUpInside)
    let reset = UIButton(type: .system); reset.setTitle("Reset trace", for: .normal)
    reset.addAction(UIAction { [weak self] _ in self?.heights = []; self?.sampledHeights = []; self?.publishTrace() }, for: .touchUpInside)
    for element in [field, trace, dismiss, reset] { element.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(element) }
    NSLayoutConstraint.activate([
      trace.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 16),
      trace.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20), trace.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
      dismiss.topAnchor.constraint(equalTo: trace.bottomAnchor, constant: 20), dismiss.leadingAnchor.constraint(equalTo: trace.leadingAnchor),
      reset.topAnchor.constraint(equalTo: dismiss.topAnchor), reset.trailingAnchor.constraint(equalTo: trace.trailingAnchor),
      field.leadingAnchor.constraint(equalTo: trace.leadingAnchor), field.trailingAnchor.constraint(equalTo: trace.trailingAnchor),
      field.heightAnchor.constraint(equalToConstant: 44), field.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor, constant: -8)
    ])
    NotificationCenter.default.addObserver(self, selector: #selector(frameChanged), name: UIResponder.keyboardWillChangeFrameNotification, object: nil)
    displayLink = CADisplayLink(target: self, selector: #selector(sampleFrame)); displayLink?.add(to: .main, forMode: .common)
  }
  @objc private func sampleFrame() {
    guard field.isFirstResponder else { return }
    let height = view.keyboardLayoutGuide.layoutFrame.height
    if height > 0, sampledHeights.last != height { sampledHeights.append(height); publishTrace() }
  }
  private func publishTrace() {
    let values = ["notifications": heights.map(Double.init), "displayFrames": sampledHeights.map(Double.init)]
    if let data = try? JSONSerialization.data(withJSONObject: values) { trace.accessibilityValue = String(data: data, encoding: .utf8) }
  }
  @objc private func frameChanged(_ note: Notification) {
    guard field.isFirstResponder, let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
    let height = view.bounds.intersection(view.convert(frame, from: nil)).height
    if height > 0 { heights.append(height) }
    publishTrace()
  }
}

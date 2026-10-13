import UIKit

// Isolated diagnostic only. No production grid, SwiftUI, polling, store or hooks.
final class MinimalKeyboardInputView: UIInputView {
  override init(frame: CGRect, inputViewStyle: UIInputView.Style) {
    super.init(frame: frame, inputViewStyle: inputViewStyle)
    autoresizingMask = [.flexibleWidth]
    allowsSelfSizing = true
    heightAnchor.constraint(equalToConstant: 278).isActive = true
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
  override var intrinsicContentSize: CGSize { CGSize(width: UIView.noIntrinsicMetric, height: 278) }
  override func sizeThatFits(_ size: CGSize) -> CGSize { CGSize(width: size.width, height: 278) }
  override func systemLayoutSizeFitting(_ targetSize: CGSize) -> CGSize { CGSize(width: targetSize.width, height: 278) }
  override func systemLayoutSizeFitting(_ targetSize: CGSize, withHorizontalFittingPriority horizontal: UILayoutPriority,
                                      verticalFittingPriority vertical: UILayoutPriority) -> CGSize { systemLayoutSizeFitting(targetSize) }
}

final class KeyboardViewController: UIInputViewController {
  override var preferredContentSize: CGSize {
    get { CGSize(width: super.preferredContentSize.width, height: 278) }
    set { super.preferredContentSize = CGSize(width: newValue.width, height: 278) }
  }
  override func loadView() {
    inputView = MinimalKeyboardInputView(frame: CGRect(x: 0, y: 0, width: 0, height: 278), inputViewStyle: .keyboard)
  }
  override func viewDidLoad() {
    super.viewDidLoad()
    let probe = UIButton(type: .system)
    probe.setTitle("Minimal keyboard", for: .normal)
    probe.accessibilityIdentifier = "clarify.keyboard.record"
    probe.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(probe)
    NSLayoutConstraint.activate([
      probe.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      probe.bottomAnchor.constraint(equalTo: view.bottomAnchor, constant: -8),
      probe.heightAnchor.constraint(equalToConstant: 44)
    ])
  }
  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    var geometry: [String] = []; var ancestor: UIView? = view
    while let item = ancestor, geometry.count < 8 {
      geometry.append("\(type(of: item)):\(item.frame):\(item.bounds)"); ancestor = item.superview
    }
    NSLog("ClarifyMinimalGeometry %@", geometry.joined(separator: " > "))
  }
}

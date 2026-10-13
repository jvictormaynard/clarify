import UIKit

// Diagnostic only: default UIKit sizing, one control, no layout callbacks or logs.
final class KeyboardViewController: UIInputViewController {
  override var preferredContentSize: CGSize {
    get { CGSize(width: UIScreen.main.bounds.width, height: 216) }
    set { super.preferredContentSize = newValue }
  }
  override func viewDidLoad() {
    super.viewDidLoad()
    let button = UIButton(type: .system)
    button.setTitle("Minimal keyboard", for: .normal)
    button.accessibilityIdentifier = "clarify.keyboard.record"
    button.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(button)
    NSLayoutConstraint.activate([
      button.topAnchor.constraint(equalTo: view.topAnchor, constant: 7),
      button.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      button.heightAnchor.constraint(equalToConstant: 44)
    ])
  }
}

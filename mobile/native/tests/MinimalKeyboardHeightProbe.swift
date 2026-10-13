import UIKit

// Diagnostic only: default UIKit sizing, one control, no layout callbacks or logs.
final class KeyboardViewController: UIInputViewController {
  override init(nibName nibNameOrNil: String?, bundle nibBundleOrNil: Bundle?) {
    super.init(nibName: nibNameOrNil, bundle: nibBundleOrNil)
    loadViewIfNeeded()
  }
  required init?(coder: NSCoder) {
    super.init(coder: coder)
    loadViewIfNeeded()
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

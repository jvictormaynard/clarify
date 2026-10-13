import UIKit

// Isolated diagnostic: no logging from the layout callbacks.
final class KeyboardViewController: UIInputViewController {
  override func willMove(toParent parent: UIViewController?) {
    ClarifyGeometryPrepareParent(parent)
    super.willMove(toParent: parent)
  }
  override func viewDidLoad() {
    super.viewDidLoad()
    ClarifyGeometryConfigure(self)
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
  override func viewWillAppear(_ animated: Bool) {
    ClarifyGeometryConfigure(self)
    super.viewWillAppear(animated)
  }
}

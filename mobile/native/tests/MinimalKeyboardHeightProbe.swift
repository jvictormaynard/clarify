import UIKit

// Isolated diagnostic only. Let UIKit create and size the default input view.
// No production grid, SwiftUI, polling, store, hooks or custom sizing contracts.
final class KeyboardViewController: UIInputViewController {
  override func viewDidLoad() {
    super.viewDidLoad()
    let probe = UIButton(type: .system)
    probe.setTitle("Minimal keyboard", for: .normal)
    probe.accessibilityIdentifier = "clarify.keyboard.record"
    probe.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(probe)
    NSLayoutConstraint.activate([
      probe.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      // Keep the probe visible even during the provisional fullscreen layout.
      // A bottom-anchored control is outside the remote host's clipped area.
      probe.topAnchor.constraint(equalTo: view.topAnchor, constant: 7),
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

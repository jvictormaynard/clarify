import UIKit
import ObjectiveC.runtime

// Isolated diagnostic only. Let UIKit create and size the default input view.
// No production grid, SwiftUI, polling, store, hooks or custom sizing contracts.
final class KeyboardViewController: UIInputViewController {
  private var previousHeight: CGFloat = -1
  private var recordedParents = false
  override init(nibName: String?, bundle: Bundle?) {
    super.init(nibName: nibName, bundle: bundle)
  }
  required init?(coder: NSCoder) {
    super.init(coder: coder)
  }
  override func viewDidLoad() {
    super.viewDidLoad()
    ClarifyGeometryConfigure(self)
    NSLog("ClarifyGeometryExperiment %@", ClarifyGeometryVariant())
    ClarifyGeometryLogController(self, "loaded")
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
  override func viewWillAppear(_ animated: Bool) {
    ClarifyGeometryConfigure(self)
    if ClarifyGeometryVariant() == "operator-fullscreen" { parent?.modalPresentationStyle = .fullScreen }
    super.viewWillAppear(animated)
    ClarifyGeometryLogController(self, "willAppear")
  }
  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    ClarifyGeometryLogController(self, "didAppear")
  }
  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    var geometry: [String] = []; var ancestor: UIView? = view
    while let item = ancestor, geometry.count < 8 {
      geometry.append("\(type(of: item)):\(item.frame):\(item.bounds)"); ancestor = item.superview
    }
    NSLog("ClarifyMinimalGeometry %@", geometry.joined(separator: " > "))
    if view.bounds.height != previousHeight {
      previousHeight = view.bounds.height
      ClarifyGeometryLogController(self, "height-\(previousHeight)")
      NSLog("ClarifyMinimalLayoutStack %@", Thread.callStackSymbols.prefix(18).joined(separator: " | "))
    }
    if !recordedParents, parent != nil {
      recordedParents = true
      var controller: UIViewController? = self
      while let current = controller {
        NSLog("ClarifyMinimalParent %@ preferred=%@", String(describing: type(of: current)), String(describing: current.preferredContentSize))
        NSLog("ClarifyMinimalPresentation %@ style=%ld presenter=%@", String(describing: type(of: current)), current.modalPresentationStyle.rawValue, String(describing: current.presentationController))
        var runtimeClass: AnyClass? = object_getClass(current)
        while let cls = runtimeClass, cls != UIViewController.self {
          var count: UInt32 = 0
          if let methods = class_copyMethodList(cls, &count) {
            defer { free(methods) }
            let names = (0..<Int(count)).map { NSStringFromSelector(method_getName(methods[$0])) }
              .filter { name in ["size", "height", "frame", "geometry", "layout"].contains { name.lowercased().contains($0) } }
            NSLog("ClarifyMinimalMethods %@ %@", NSStringFromClass(cls), names.joined(separator: ","))
          }
          runtimeClass = class_getSuperclass(cls)
        }
        controller = current.parent
      }
    }
  }
}

import ExpoModulesCore
import UIKit

struct HistoryMenuAction: Record {
  @Field var id: String = ""
  @Field var title: String = ""
  @Field var systemImage: String = ""
  @Field var disabled: Bool = false
  @Field var destructive: Bool = false
}

final class HistoryContextMenu: ExpoView, UIContextMenuInteractionDelegate {
  let onAction = EventDispatcher()
  var menuID = "" {
    didSet { if menuID != oldValue { interaction.dismissMenu() } }
  }
  var actions: [HistoryMenuAction] = [] {
    didSet { interaction.updateVisibleMenu { [weak self] _ in self?.makeMenu() ?? UIMenu() } }
  }
  private lazy var interaction = UIContextMenuInteraction(delegate: self)

  required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    addInteraction(interaction)
  }

  func contextMenuInteraction(_ interaction: UIContextMenuInteraction,
    configurationForMenuAtLocation location: CGPoint) -> UIContextMenuConfiguration? {
    guard !actions.isEmpty else { return nil }
    // Cancel the React press when UIKit takes the hold, as the pinned Expo Router does.
    var ancestor: UIView? = self
    while let view = ancestor {
      if let handler = view.gestureRecognizers?.first(where: { NSStringFromClass(type(of: $0)).contains("RCTSurfaceTouchHandler") }) {
        if handler.isEnabled { handler.isEnabled = false; handler.isEnabled = true }
        break
      }
      ancestor = view.superview
    }
    return UIContextMenuConfiguration(identifier: menuID as NSString, previewProvider: nil) { [weak self] _ in
      self?.makeMenu()
    }
  }

  private func makeMenu() -> UIMenu {
    let identity = menuID
    return UIMenu(children: actions.map { item in
      var attributes: UIMenuElement.Attributes = []
      if item.disabled { attributes.insert(.disabled) }
      if item.destructive { attributes.insert(.destructive) }
      return UIAction(title: item.title, image: UIImage(systemName: item.systemImage), attributes: attributes) { [weak self] _ in
        guard let self, self.menuID == identity,
          self.actions.contains(where: { $0.id == item.id && !$0.disabled }) else { return }
        self.onAction(["id": item.id, "menuID": identity])
      }
    })
  }

  func contextMenuInteraction(_ interaction: UIContextMenuInteraction,
    previewForHighlightingMenuWithConfiguration configuration: UIContextMenuConfiguration) -> UITargetedPreview? {
    let parameters = UIPreviewParameters()
    parameters.backgroundColor = .clear
    parameters.visiblePath = UIBezierPath(roundedRect: bounds, cornerRadius: 12)
    return UITargetedPreview(view: self, parameters: parameters)
  }
}

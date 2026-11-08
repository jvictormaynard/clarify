import UIKit

// The preview stays inside the extension, including for the top row.
final class KeyPreview: UIView {
  private let shape = CAShapeLayer()
  private let label = UILabel()
  override init(frame: CGRect) {
    super.init(frame: frame)
    isUserInteractionEnabled = false; isAccessibilityElement = false
    layer.addSublayer(shape); addSubview(label)
    label.textAlignment = .center; label.font = .systemFont(ofSize: 34)
    layer.shadowColor = UIColor.black.cgColor; layer.shadowOpacity = 0.2
    layer.shadowRadius = 3; layer.shadowOffset = CGSize(width: 0, height: 1)
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
  func show(_ text: String, key: CGRect, in container: UIView, color: UIColor) {
    let width = max(54, key.width + 22), cap: CGFloat = 54
    let x = min(max(2, key.midX - width / 2), container.bounds.width - width - 2)
    let top = max(0, key.minY - cap - 9)
    frame = CGRect(x: x, y: top, width: width, height: key.maxY - top)
    let stemLeft = key.minX - x, stemRight = key.maxX - x
    let path = UIBezierPath()
    path.move(to: CGPoint(x: 12, y: 0))
    path.addLine(to: CGPoint(x: width - 12, y: 0))
    path.addQuadCurve(to: CGPoint(x: width, y: 12), controlPoint: CGPoint(x: width, y: 0))
    path.addLine(to: CGPoint(x: width, y: cap - 12))
    path.addCurve(to: CGPoint(x: stemRight, y: cap + 14),
      controlPoint1: CGPoint(x: width, y: cap + 2), controlPoint2: CGPoint(x: stemRight, y: cap + 1))
    path.addLine(to: CGPoint(x: stemRight, y: bounds.height - 8))
    path.addQuadCurve(to: CGPoint(x: stemRight - 8, y: bounds.height), controlPoint: CGPoint(x: stemRight, y: bounds.height))
    path.addLine(to: CGPoint(x: stemLeft + 8, y: bounds.height))
    path.addQuadCurve(to: CGPoint(x: stemLeft, y: bounds.height - 8), controlPoint: CGPoint(x: stemLeft, y: bounds.height))
    path.addLine(to: CGPoint(x: stemLeft, y: cap + 14))
    path.addCurve(to: CGPoint(x: 0, y: cap - 12),
      controlPoint1: CGPoint(x: stemLeft, y: cap + 1), controlPoint2: CGPoint(x: 0, y: cap + 2))
    path.addLine(to: CGPoint(x: 0, y: 12))
    path.addQuadCurve(to: CGPoint(x: 12, y: 0), controlPoint: .zero); path.close()
    let fill = container.traitCollection.userInterfaceStyle == .dark ? UIColor(white: 0.33, alpha: 1) : color.withAlphaComponent(1)
    shape.path = path.cgPath; shape.fillColor = fill.resolvedColor(with: container.traitCollection).cgColor
    layer.shadowPath = path.cgPath
    label.text = text; label.textColor = .label
    label.frame = CGRect(x: 0, y: 0, width: width, height: cap)
    container.addSubview(self)
  }
}

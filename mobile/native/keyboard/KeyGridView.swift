import UIKit

private final class KeyButton: UIButton {
  var restingColor = UIColor.clear
  var accessibleAction: (() -> Void)?
  var onHighlight: ((KeyButton, Bool) -> Void)?
  var acceptsPoint: ((CGPoint) -> Bool)?
  weak var grid: KeyGridView?
  var isGlobe = false
  // Keep the original UIKit touch identity, but let the grid transfer a press
  // to a neighbouring key. UIButton's default tracking drops such releases.
  override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) { grid?.track(touches, phase: .began, event: event) }
  override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) { grid?.track(touches, phase: .moved, event: event) }
  override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) { grid?.track(touches, phase: .ended, event: event) }
  override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { grid?.track(touches, phase: .cancelled, event: event) }
  override func point(inside point: CGPoint, with event: UIEvent?) -> Bool {
    acceptsPoint?(point) ?? super.point(inside: point, with: event)
  }
  override func accessibilityActivate() -> Bool {
    guard isEnabled else { return false }
    if let action = accessibleAction { action(); return true }
    return super.accessibilityActivate()
  }
  override var isHighlighted: Bool {
    didSet {
      backgroundColor = isHighlighted ? .systemGray2 : restingColor
      if oldValue != isHighlighted { onHighlight?(self, isHighlighted) }
    }
  }
}

// UIKit keys styled like the system keyboard. No private Apple keyboard engine.
final class KeyGridView: UIView {
  var onInsert: ((String) -> Void)?
  var onDelete: (() -> Void)?
  var onNextKeyboard: ((UIButton, UIEvent?) -> Void)?
  var onKeyPress: (() -> Void)?
  weak var previewContainer: UIView?
  var model = KeyboardState()
  var needsGlobe = false
  var returnType: UIReturnKeyType = .default
  private let stack = UIStackView()
  private var repeatTimer: Timer?
  private var lastShift = Date.distantPast
  private var accentBar: UIStackView?
  private var accentKeys: [UIButton] = []
  private var selectedAccent: String?
  private var suppressKey = false
  private let preview = KeyPreview()
  private var touchKeys: [KeyButton] = []
  private var presses: [AnyHashable: KeyButton] = [:]
  private var rebuildPending = false
  private var layoutSignature = ""

  func track(_ touches: Set<UITouch>, phase: UITouch.Phase, event: UIEvent?) {
    for touch in touches.sorted(by: { $0.timestamp < $1.timestamp }) {
      let id = AnyHashable(ObjectIdentifier(touch)), point = touch.location(in: self)
      switch phase {
      case .began: beginPress(id, at: point, event: event)
      case .moved: movePress(id, to: point, event: event)
      case .ended: endPress(id, at: point, event: event)
      default: cancelPress(id)
      }
    }
  }
  func beginPress(_ id: AnyHashable, at point: CGPoint, event: UIEvent? = nil) {
    guard presses[id] == nil, accentBar == nil, let key = nearestKey(at: point) else { return }
    presses[id] = key; key.isHighlighted = true
    if key.isGlobe { onNextKeyboard?(key, event) } else { key.sendActions(for: .touchDown) }
  }
  func movePress(_ id: AnyHashable, to point: CGPoint, event: UIEvent? = nil) {
    guard let previous = presses[id], accentBar == nil else { return }
    if previous.isGlobe { onNextKeyboard?(previous, event); return }
    // A small release margin tolerates finger motion at the outer keyboard edge.
    guard let next = releaseKey(at: point), next !== previous else { return }
    presses[id] = next
    if !presses.values.contains(where: { $0 === previous }) { previous.isHighlighted = false }
    previous.sendActions(for: .touchDragExit)
    next.isHighlighted = true
    if !next.isGlobe { next.sendActions(for: .touchDown) }
  }
  func endPress(_ id: AnyHashable, at point: CGPoint, event: UIEvent? = nil) {
    movePress(id, to: point, event: event)
    guard let key = presses.removeValue(forKey: id) else { return }
    if !presses.values.contains(where: { $0 === key }) { key.isHighlighted = false }
    if key.isGlobe { onNextKeyboard?(key, event) }
    else { key.sendActions(for: releaseKey(at: point) != nil && accentBar == nil ? .touchUpInside : .touchCancel) }
    finishPresses()
  }
  func cancelPress(_ id: AnyHashable) {
    guard let key = presses.removeValue(forKey: id) else { return }
    if !presses.values.contains(where: { $0 === key }) { key.isHighlighted = false }
    key.sendActions(for: .touchCancel); finishPresses()
  }
  private func finishPresses() {
    if presses.isEmpty, rebuildPending { rebuildPending = false; rebuild() }
  }
  private func releaseKey(at point: CGPoint) -> KeyButton? {
    guard bounds.insetBy(dx: -12, dy: -12).contains(point) else { return nil }
    return nearestKey(at: CGPoint(x: min(max(0, point.x), bounds.maxX - 0.01), y: min(max(0, point.y), bounds.maxY - 0.01)))
  }

  // Partition the visible grid by distance to each key's rectangle. This covers
  // row gaps and outside margins without changing the visible key geometry.
  private func nearestKey(at point: CGPoint) -> KeyButton? {
    guard bounds.contains(point) else { return nil }
    var result: KeyButton?
    var shortest = CGFloat.greatestFiniteMagnitude
    for key in touchKeys where key.isEnabled && key.isUserInteractionEnabled && !key.isHidden && key.alpha > 0.01 {
      let rect = key.convert(key.bounds, to: self)
      let dx = max(rect.minX - point.x, 0, point.x - rect.maxX)
      let dy = max(rect.minY - point.y, 0, point.y - rect.maxY)
      let distance = dx * dx + dy * dy
      if distance < shortest { shortest = distance; result = key }
    }
    return result
  }
  override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
    let hit = super.hitTest(point, with: event)
    // Leave the accent picker and UIKit's hidden/disabled/outside rules intact.
    guard hit != nil, accentBar == nil else { return hit }
    return nearestKey(at: point) ?? hit
  }

  override init(frame: CGRect) {
    super.init(frame: frame)
    isMultipleTouchEnabled = true
    stack.axis = .vertical; stack.spacing = 10; stack.distribution = .fillEqually
    addSubview(stack); stack.translatesAutoresizingMaskIntoConstraints = false
    NSLayoutConstraint.activate([
      stack.topAnchor.constraint(equalTo: topAnchor, constant: 4),
      stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -6),
      stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 6),
      stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -6)
    ])
    rebuild()
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
  override func didMoveToWindow() {
    super.didMoveToWindow()
    if window == nil { for id in Array(presses.keys) { cancelPress(id) }; stopDelete(); preview.removeFromSuperview() }
  }
  deinit { repeatTimer?.invalidate() }

  func rebuild() {
    guard accentBar == nil, presses.isEmpty else { rebuildPending = true; return }
    let signature = "\(model.page):\(model.shift):\(needsGlobe):\(returnType.rawValue)"
    guard layoutSignature != signature else { return }
    layoutSignature = signature
    preview.removeFromSuperview()
    stopDelete()
    stack.arrangedSubviews.forEach { $0.removeFromSuperview() }
    let rows = model.rows
    for (index, letters) in rows.enumerated() {
      let row = UIStackView(); row.axis = .horizontal; row.spacing = 6
      row.distribution = .fillEqually
      if index == 2 {
        let title = model.page == .letters ? "" : (model.page == .numbers ? "#+=" : "123")
        let mode = key(title, special: true) { [weak self] in self?.changeShiftOrSymbols() }
        if model.page == .letters {
          mode.setImage(UIImage(systemName: model.shift == .caps ? "capslock.fill" : (model.shift == .once ? "shift.fill" : "shift")), for: .normal)
          mode.accessibilityLabel = model.shift == .caps ? L("Desativar maiúsculas") : L("Maiúsculas")
        }
        row.addArrangedSubview(mode)
      }
      for text in letters {
        let button = key(text) { [weak self] in
          guard let self = self else { return }
          if self.suppressKey { self.suppressKey = false; return }
          let value = text.allSatisfy(\.isLetter) ? (self.model.shift == .off ? text.lowercased() : text.uppercased()) : text
          self.insert(value)
        }
        if !KeyboardState.accents(for: text).isEmpty {
          let long = UILongPressGestureRecognizer(target: self, action: #selector(accent(_:)))
          long.minimumPressDuration = 0.35; button.addGestureRecognizer(long)
          // VoiceOver exposes accents without requiring a drag.
          button.accessibilityCustomActions = KeyboardState.accents(for: text).dropFirst().map { value in
            UIAccessibilityCustomAction(name: value) { [weak self] _ in self?.insert(value); return true }
          }
        }
        row.addArrangedSubview(button)
      }
      if index == 2 {
        let delete = key("", special: true) {}
        delete.setImage(UIImage(systemName: "delete.left"), for: .normal); delete.accessibilityLabel = L("Apagar")
        delete.accessibleAction = { [weak self] in self?.onDelete?() }
        delete.addTarget(self, action: #selector(beginDelete), for: .touchDown)
        delete.addTarget(self, action: #selector(stopDelete), for: [.touchUpInside, .touchUpOutside, .touchCancel, .touchDragExit])
        row.addArrangedSubview(delete)
      }
      if index == 2, model.page == .letters {
        row.distribution = .fill
        let buttons = row.arrangedSubviews
        // The middle seven keys keep the first row's width. Separate gaps let
        // shift/delete keep the narrower proportions of the Apple reference.
        let middle = UIStackView(); middle.axis = .horizontal; middle.spacing = 6
        for button in buttons.dropFirst().dropLast() {
          row.removeArrangedSubview(button); button.removeFromSuperview(); middle.addArrangedSubview(button)
        }
        row.insertArrangedSubview(middle, at: 1); row.spacing = 14
        for button in middle.arrangedSubviews {
          button.widthAnchor.constraint(equalTo: row.widthAnchor, multiplier: 0.1, constant: -5.4).isActive = true
        }
        buttons.first!.widthAnchor.constraint(equalTo: buttons.last!.widthAnchor).isActive = true
      }
      let container = UIView(); container.addSubview(row); row.translatesAutoresizingMaskIntoConstraints = false
      let inset: CGFloat = model.page == .letters && index == 1 ? 19 : 0
      NSLayoutConstraint.activate([
        row.topAnchor.constraint(equalTo: container.topAnchor), row.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        row.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: inset),
        row.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -inset)
      ])
      stack.addArrangedSubview(container)
    }
    let bottom = UIStackView(); bottom.axis = .horizontal; bottom.spacing = 6
    // Attach the row before activating constraints against the outer stack.
    stack.addArrangedSubview(bottom)
    let mode = key(model.page == .letters ? "123" : "ABC", special: true) { [weak self] in
      guard let self = self else { return }
      self.model.page = self.model.page == .letters ? .numbers : .letters; self.rebuild()
    }
    bottom.addArrangedSubview(mode)
    mode.widthAnchor.constraint(equalTo: stack.widthAnchor, multiplier: 0.113).isActive = true
    if needsGlobe {
      let globe = key("", special: true) {}; globe.setImage(UIImage(systemName: "globe"), for: .normal)
      globe.isGlobe = true
      globe.accessibilityLabel = L("Próximo teclado")
      globe.accessibleAction = { [weak self, weak globe] in if let globe = globe { self?.onNextKeyboard?(globe, nil) } }
      globe.addTarget(self, action: #selector(nextKeyboard(_:event:)), for: .allTouchEvents)
      bottom.addArrangedSubview(globe); globe.widthAnchor.constraint(equalTo: mode.widthAnchor).isActive = true
    }
    bottom.addArrangedSubview(key(L("espaço")) { [weak self] in self?.insert(" ") })
    let returns: [UIReturnKeyType: String] = [.go: L("ir"), .search: L("buscar"), .send: L("enviar"), .next: L("próximo"), .done: "OK", .join: L("entrar"), .route: L("rota")]
    let enter = key(returns[returnType] ?? L("retorno"), special: true) { [weak self] in self?.insert("\n") }
    if returnType != .default {
      enter.restingColor = .systemBlue; enter.backgroundColor = .systemBlue; enter.setTitleColor(.white, for: .normal)
    }
    bottom.addArrangedSubview(enter); enter.widthAnchor.constraint(equalTo: stack.widthAnchor, multiplier: 0.23).isActive = true
    func buttons(in view: UIView) -> [KeyButton] {
      view.subviews.flatMap { child in
        if let key = child as? KeyButton { return [key] }
        return buttons(in: child)
      }
    }
    touchKeys = buttons(in: stack)
  }
  private func key(_ title: String, special: Bool = false, action: @escaping () -> Void) -> KeyButton {
    let button = KeyButton(type: .custom)
    button.grid = self; button.isMultipleTouchEnabled = true
    button.restingColor = UIColor { traits in
      // Lift the system material below each dark key instead of covering it
      // with a fixed gray that can match the host application's background.
      if traits.userInterfaceStyle == .dark {
        let stronger = traits.accessibilityContrast == .high
        return UIAccessibility.isReduceTransparencyEnabled
          ? UIColor(white: stronger ? 0.6 : 0.47, alpha: 1)
          : UIColor(white: 1, alpha: stronger ? 0.36 : 0.24)
      }
      return special ? UIColor(white: 0.68, alpha: 1) : .white
    }
    button.backgroundColor = button.restingColor; button.layer.cornerRadius = 10
    button.layer.cornerCurve = .continuous
    button.layer.shadowColor = UIColor.black.cgColor; button.layer.shadowOpacity = 0.12
    button.layer.shadowOffset = CGSize(width: 0, height: 1); button.layer.shadowRadius = 0
    button.setTitle(title, for: .normal); button.setTitleColor(.label, for: .normal); button.tintColor = .label
    button.titleLabel?.font = .systemFont(ofSize: title.count > 1 ? 16 : 25)
    button.accessibilityLabel = title; button.accessibilityTraits = .keyboardKey
    button.acceptsPoint = { [weak self, weak button] point in
      guard let self = self, let button = button else { return false }
      guard self.accentBar == nil, button.isDescendant(of: self.stack) else {
        return button.bounds.contains(point)
      }
      // UIButton uses point(inside:) again while tracking and on release.
      return self.nearestKey(at: button.convert(point, to: self)) === button
    }
    button.onHighlight = { [weak self] key, highlighted in
      guard let self = self else { return }
      if highlighted {
        self.onKeyPress?()
        if title.count == 1, self.accentBar == nil, let container = self.previewContainer {
          self.preview.show(title, key: key.convert(key.bounds, to: container), in: container, color: key.restingColor)
        }
      } else { self.preview.removeFromSuperview() }
    }
    button.addAction(UIAction { _ in action() }, for: .touchUpInside)
    return button
  }
  private func insert(_ text: String) { model.didInsert(text); onInsert?(text); rebuild() }
  private func changeShiftOrSymbols() {
    if model.page == .letters {
      let now = Date(); model.toggleShift(caps: now.timeIntervalSince(lastShift) < 0.3); lastShift = now
    } else { model.page = model.page == .numbers ? .symbols : .numbers }
    rebuild()
  }
  @objc private func nextKeyboard(_ button: UIButton, event: UIEvent?) { onNextKeyboard?(button, event) }
  @objc private func beginDelete() {
    stopDelete(); onDelete?()
    repeatTimer = Timer.scheduledTimer(withTimeInterval: 0.4, repeats: false) { [weak self] _ in
      guard let self = self else { return }; self.onDelete?()
      self.repeatTimer = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] _ in self?.onDelete?() }
    }
  }
  @objc private func stopDelete() { repeatTimer?.invalidate(); repeatTimer = nil }
  @objc private func accent(_ gesture: UILongPressGestureRecognizer) {
    guard let button = gesture.view as? UIButton, let title = button.title(for: .normal) else { return }
    if gesture.state == .began {
      preview.removeFromSuperview()
      suppressKey = true
      let choices = KeyboardState.accents(for: title)
      let bar = UIStackView(); bar.axis = .horizontal; bar.distribution = .fillEqually; bar.spacing = 2
      let width = min(bounds.width - 12, CGFloat(choices.count) * 42)
      let center = button.convert(CGPoint(x: button.bounds.midX, y: 0), to: self)
      bar.frame = CGRect(x: min(max(6, center.x - width / 2), bounds.width - width - 6), y: 0, width: width, height: 46)
      bar.backgroundColor = .secondarySystemBackground; bar.layer.cornerRadius = 8
      accentKeys = choices.map { value in let key = key(value) {}; bar.addArrangedSubview(key); return key }
      accentBar = bar; addSubview(bar); selectedAccent = title
    }
    if let bar = accentBar {
      let point = gesture.location(in: bar)
      let index = gesture.state == .began ? 0 : max(0, min(accentKeys.count - 1, Int(point.x / max(1, bar.bounds.width) * CGFloat(accentKeys.count))))
      for (i, key) in accentKeys.enumerated() { key.backgroundColor = i == index ? .systemBlue : .clear; key.setTitleColor(i == index ? .white : .label, for: .normal) }
      selectedAccent = accentKeys[index].title(for: .normal)
    }
    if [.ended, .cancelled, .failed].contains(gesture.state) {
      let selection = selectedAccent; accentBar?.removeFromSuperview(); accentBar = nil; accentKeys = []
      if gesture.state == .ended, let selection = selection { insert(selection) }
      // Long-press recognition cancels UIButton's touch-up, so the next tap is valid.
      suppressKey = false
    }
  }
}

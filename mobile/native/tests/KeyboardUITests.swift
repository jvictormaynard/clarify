import UIKit
import XCTest
@testable import KeyboardUI
import KeyboardHostSupport

@MainActor
private final class Field: NSObject, UITextDocumentProxy {
  var documentIdentifier = UUID()
  var before = ""
  var after = ""
  var documentContextBeforeInput: String? { before }
  var documentContextAfterInput: String? { after }
  var documentInputMode: UITextInputMode? { nil }
  var selectedText: String?
  var hasText: Bool { !before.isEmpty || !after.isEmpty }
  var autocorrectionType: UITextAutocorrectionType = .yes
  var spellCheckingType: UITextSpellCheckingType = .yes
  var keyboardType: UIKeyboardType = .default
  var isSecureTextEntry = false
  func insertText(_ text: String) { before += text }
  func deleteBackward() { if !before.isEmpty { before.removeLast() } }
  func adjustTextPosition(byCharacterOffset offset: Int) {}
  func setMarkedText(_ markedText: String, selectedRange: NSRange) {}
  func unmarkText() {}
}

@MainActor
private final class SelectionKeyboard: KeyboardViewController {
  let field = Field()
  var fullAccess = true
  override var textDocumentProxy: UITextDocumentProxy { field }
  override var hasFullAccess: Bool { fullAccess }
}

@MainActor
private final class ImpactFeedbackSpy: UIImpactFeedbackGenerator {
  var pulses = 0
  var preparations = 0
  override func impactOccurred() { pulses += 1 }
  override func prepare() { preparations += 1 }
}

final class KeyboardUITests: XCTestCase {
  @MainActor
  private func assertSavedTitleIsVisible(_ button: UIButton, in appearance: UIUserInterfaceStyle) throws {
    button.overrideUserInterfaceStyle = appearance; button.layoutIfNeeded()
    let label = try XCTUnwrap(button.titleLabel)
    let image = UIGraphicsImageRenderer(bounds: button.bounds).image { button.layer.render(in: $0.cgContext) }
    let cgImage = try XCTUnwrap(image.cgImage), width = cgImage.width, height = cgImage.height
    let bitmap = try XCTUnwrap(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
      bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
      bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue))
    bitmap.draw(cgImage, in: CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
    let data = try XCTUnwrap(bitmap.data).assumingMemoryBound(to: UInt8.self)
    let scale = image.scale, rect = label.convert(label.bounds, to: button).insetBy(dx: 1, dy: 1)
    guard !rect.isEmpty else { XCTFail("Saved title has no visible area"); return }
    var visiblePixels = 0
    for y in max(0, Int(rect.minY * scale))..<min(height, Int(rect.maxY * scale)) {
      for x in max(0, Int(rect.minX * scale))..<min(width, Int(rect.maxX * scale)) {
        let offset = (y * width + x) * 4
        let luminance = (Int(data[offset]) + Int(data[offset + 1]) + Int(data[offset + 2])) / 3
        if appearance == .dark ? luminance < 100 : luminance > 155 { visiblePixels += 1 }
      }
    }
    XCTAssertGreaterThan(visiblePixels, 5, "Saved must remain readable against the disabled capsule background")
  }
  func testDictionarySelectionSavesDisablesAndUpdatesWithoutChangingTheDocument() async throws {
    try await MainActor.run {
      let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
      try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
      defer { try? FileManager.default.removeItem(at: root) }
      let store = SharedState(root: root)
      try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: []))
      var snapshot = DictationSnapshot(); snapshot.sessionActive = true; snapshot.configured = true
      try store.write(snapshot, to: "state.json")
      let keyboard = SelectionKeyboard(); keyboard.store = store
      keyboard.overrideUserInterfaceStyle = .dark
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
      defer { window.isHidden = true }
      host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
      keyboard.view.frame = CGRect(x: 0, y: 574, width: 393, height: 278)
      func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
      let action = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.add-to-dictionary" })
      keyboard.field.before = "Untouched "
      keyboard.field.selectedText = "João Victor"; keyboard.selectionDidChange(nil)
      XCTAssertFalse(action.isHidden); XCTAssertTrue(action.isEnabled)
      for width in [CGFloat(320), 393, 852] {
        keyboard.view.frame.size.width = width; keyboard.view.layoutIfNeeded()
        XCTAssertTrue(keyboard.view.bounds.contains(action.frame))
        XCTAssertGreaterThan(action.bounds.width, 150)
        XCTAssertEqual(keyboard.view.bounds.height, 278)
      }
      keyboard.view.frame.size.width = 393; keyboard.view.layoutIfNeeded()
      let offered = XCTAttachment(image: UIGraphicsImageRenderer(bounds: keyboard.view.bounds).image { keyboard.view.layer.render(in: $0.cgContext) })
      offered.name = "dictionary-selection-offered"; offered.lifetime = .keepAlways; self.add(offered)
      action.sendActions(for: .touchUpInside)
      XCTAssertFalse(action.isEnabled); XCTAssertEqual(action.title(for: .normal), L("Salvo"))
      XCTAssertEqual(store.keyboardAdditions(scope: "guest").map { $0.1.term }, ["João Victor"])
      XCTAssertEqual(keyboard.field.before, "Untouched "); XCTAssertEqual(keyboard.field.selectedText, "João Victor")
      for selection in ["three selected words", "", "+ …"] {
        keyboard.field.selectedText = selection; keyboard.selectionDidChange(nil); XCTAssertTrue(action.isHidden)
      }
      keyboard.field.selectedText = "New"; keyboard.selectionDidChange(nil)
      XCTAssertFalse(action.isHidden); XCTAssertTrue(action.isEnabled)
      keyboard.field.isSecureTextEntry = true; keyboard.selectionDidChange(nil); XCTAssertTrue(action.isHidden)
      keyboard.field.isSecureTextEntry = false; keyboard.field.selectedText = "JOÃO VICTOR"; keyboard.selectionDidChange(nil)
      XCTAssertFalse(action.isHidden); XCTAssertFalse(action.isEnabled)
      for appearance in [UIUserInterfaceStyle.light, .dark] { try self.assertSavedTitleIsVisible(action, in: appearance) }
      keyboard.view.frame.size.width = 393; keyboard.view.layoutIfNeeded()
      let capture = XCTAttachment(image: UIGraphicsImageRenderer(bounds: keyboard.view.bounds).image { keyboard.view.layer.render(in: $0.cgContext) })
      capture.name = "dictionary-selection-saved"; capture.lifetime = .keepAlways; self.add(capture)
      keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
      snapshot.sessionActive = false; try store.write(snapshot, to: "state.json")
      keyboard.field.selectedText = "Other"
      keyboard.beginAppearanceTransition(true, animated: false); keyboard.endAppearanceTransition()
      defer { keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition() }
      for width in [CGFloat(320), 393] {
        keyboard.view.frame.size.width = width
        for language in ["pt", "en", "es"] {
          action.setTitle(L("Adicionar ao dicionário", language: language), for: .normal)
          keyboard.view.layoutIfNeeded()
          XCTAssertTrue(keyboard.view.bounds.contains(action.frame))
          XCTAssertLessThanOrEqual(action.frame.maxX, width - 136, "Do not overlap the inactive Start button")
          XCTAssertGreaterThan(action.bounds.width, 140)
        }
      }
      keyboard.fullAccess = false; keyboard.field.selectedText = "Restricted"; keyboard.selectionDidChange(nil)
      XCTAssertFalse(action.isEnabled)
    }
  }
  func testShortSelectionOffersDictionaryActionWithoutChangingTheDocument() async {
    await MainActor.run {
      let keyboard = SelectionKeyboard()
      keyboard.loadViewIfNeeded()
      keyboard.field.before = "Original text "
      keyboard.field.selectedText = "Clarify"
      keyboard.selectionDidChange(nil)
      func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
      let action = descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.add-to-dictionary" && !$0.isHidden }
      XCTAssertNotNil(action, "A selected word must offer the dictionary action")
      XCTAssertEqual(keyboard.field.before, "Original text ")
      XCTAssertEqual(keyboard.field.selectedText, "Clarify")
    }
  }
  func testKeyboardPublishesItsHeightBeforeAttachment() async {
    await MainActor.run {
      let keyboard = KeyboardViewController()
      keyboard.loadViewIfNeeded()
      XCTAssertEqual(keyboard.preferredContentSize.height, 278)
      XCTAssertEqual(keyboard.inputView?.bounds.height, 278)
      XCTAssertFalse(keyboard.view.autoresizingMask.contains(.flexibleHeight))
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host
      window.makeKeyAndVisible()
      host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
      keyboard.view.translatesAutoresizingMaskIntoConstraints = false
      NSLayoutConstraint.activate([
        keyboard.view.leadingAnchor.constraint(equalTo: host.view.leadingAnchor),
        keyboard.view.trailingAnchor.constraint(equalTo: host.view.trailingAnchor),
        keyboard.view.bottomAnchor.constraint(equalTo: host.view.bottomAnchor)
      ])
      for height in [CGFloat(852), 393, 956, 852] {
        host.view.frame.size.height = height
        host.view.setNeedsLayout(); host.view.layoutIfNeeded()
        XCTAssertEqual(keyboard.view.bounds.height, 278, accuracy: 0.5)
        XCTAssertEqual(keyboard.view.frame.maxY, host.view.bounds.maxY, accuracy: 0.5)
      }
      window.isHidden = true
    }
  }
  func testLegacySourceLookupFailsClosedWhenDetachedOrTheOSParentHasChanged() async {
    await MainActor.run {
      let keyboard = KeyboardViewController()
      XCTAssertNil(KBHostArbiterHook.legacyHostBundleID(for: keyboard))
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
      host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
      // A plain parent has no _hostPID. KVC must not crash the extension.
      XCTAssertNil(KBHostArbiterHook.legacyHostBundleID(for: keyboard))
      window.isHidden = true
    }
  }
  func testTypingAndRecordingUseOneStandardImpactPerEvent() async {
    await MainActor.run {
      let key = ImpactFeedbackSpy(style: .light), recording = ImpactFeedbackSpy(style: .medium)
      let feedback = HapticFeedback(key: key, recording: recording)
      feedback.prepare()
      feedback.type(); feedback.type()
      XCTAssertEqual(key.pulses, 2)
      XCTAssertEqual(recording.pulses, 0)
      for action in ["start", "lock", "finish"] { feedback.record(action) }
      XCTAssertEqual(recording.pulses, 3)
      for action in ["cancel", "invalid"] { feedback.record(action) }
      XCTAssertEqual(recording.pulses, 3)
      XCTAssertEqual(key.preparations, 3)
      XCTAssertEqual(recording.preparations, 4)
    }
  }
  func testKeysDoNotStretchDuringTheInitialHostHeightTransition() async {
    await MainActor.run {
      let keyboard = KeyboardViewController(); keyboard.loadViewIfNeeded()
      XCTAssertTrue((keyboard.view as? UIInputView)?.allowsSelfSizing == true)
      for height in [CGFloat(0), 278, 540, 956] {
        XCTAssertEqual(keyboard.view.systemLayoutSizeFitting(CGSize(width: 393, height: height)).height, 278)
        XCTAssertEqual(keyboard.view.systemLayoutSizeFitting(CGSize(width: 393, height: height),
          withHorizontalFittingPriority: .required, verticalFittingPriority: .fittingSizeLevel).height, 278)
      }
      keyboard.view.frame = CGRect(x: 0, y: 0, width: 393, height: 540)
      keyboard.view.layoutIfNeeded()
      func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
      let grid = descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first!
      XCTAssertEqual(grid.bounds.height, 220, accuracy: 0.5)
      let buttons = descendants(grid).compactMap { $0 as? UIButton }
      XCTAssertTrue(buttons.allSatisfy { $0.bounds.height < 50 })
    }
  }
  func testRecordingHintFitsInsideTheMicrophoneAndDisappearsOnLock() async {
    await MainActor.run {
      let glyph = RecordingGlyph(frame: CGRect(x: 0, y: 0, width: 44, height: 44))
      glyph.update(recording: true, locked: false, animated: false); glyph.layoutIfNeeded()
      let images = glyph.subviews.compactMap { $0 as? UIImageView }
      XCTAssertEqual(images.count, 2)
      XCTAssertTrue(images.allSatisfy { glyph.bounds.contains($0.frame) })
      XCTAssertTrue(images.allSatisfy { $0.alpha > 0 })
      let capture = XCTAttachment(image: UIGraphicsImageRenderer(bounds: glyph.bounds).image { glyph.layer.render(in: $0.cgContext) })
      capture.name = "recording-upward-hint"; capture.lifetime = .keepAlways; self.add(capture)
      glyph.update(recording: false, locked: true, animated: false)
      XCTAssertEqual(images.filter { $0.alpha > 0 }.count, 1)
    }
  }
  func testKeyPressRequestsFeedbackOncePerPress() async {
    await MainActor.run {
      let grid = KeyGridView()
      func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
      let button = descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == "A" }!
      var pulses = 0
      grid.onKeyPress = { pulses += 1 }
      button.isHighlighted = true
      button.isHighlighted = true
      XCTAssertEqual(pulses, 1)
      button.isHighlighted = false
      XCTAssertEqual(pulses, 1)
      button.isHighlighted = true
      XCTAssertEqual(pulses, 2)
    }
  }
  func testKeyGapsRouteToNearestKeyAndAcceptTheTouch() async {
    await MainActor.run {
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
      let grid = KeyGridView(); host.view.addSubview(grid)
      grid.frame = CGRect(x: 0, y: 200, width: 393, height: 218)
      grid.layoutIfNeeded()
      func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
      let buttons = descendants(grid).compactMap { $0 as? UIButton }
      let q = buttons.first { $0.title(for: .normal) == "Q" }!
      let w = buttons.first { $0.title(for: .normal) == "W" }!
      let qFrame = q.convert(q.bounds, to: grid), wFrame = w.convert(w.bounds, to: grid)
      let gap = wFrame.minX - qFrame.maxX
      XCTAssertGreaterThan(gap, 0)
      for (fraction, expected) in [(CGFloat(0.25), q), (CGFloat(0.75), w)] {
        let point = CGPoint(x: qFrame.maxX + gap * fraction, y: qFrame.midY)
        let hit = grid.hitTest(point, with: nil)
        XCTAssertTrue(hit === expected, "Gap must select its nearest key")
        XCTAssertTrue(expected.point(inside: expected.convert(point, from: grid), with: nil),
                      "UIButton must accept the expanded area throughout touch tracking")
      }
      var inserted: [String] = []
      grid.onInsert = { inserted.append($0) }
      let point = CGPoint(x: qFrame.maxX + gap * 0.75, y: qFrame.midY)
      (grid.hitTest(point, with: nil) as? UIButton)?.sendActions(for: .touchUpInside)
      XCTAssertEqual(inserted, ["W"])
      for page in [KeyboardState.Page.letters, .numbers, .symbols] {
        grid.model.page = page; grid.rebuild()
        for width in [CGFloat(320), 393, 852] {
          grid.frame.size.width = width; grid.layoutIfNeeded()
          for y in stride(from: CGFloat(1), to: grid.bounds.height, by: 12) {
            for x in stride(from: CGFloat(1), to: width, by: 12) {
              let point = CGPoint(x: x, y: y)
              guard let hit = grid.hitTest(point, with: nil) as? UIButton else {
                XCTFail("Dead area at \(point), page \(page), width \(width)"); return
              }
              XCTAssertTrue(hit.point(inside: hit.convert(point, from: grid), with: nil))
            }
          }
        }
      }
      XCTAssertNil(grid.hitTest(CGPoint(x: -1, y: 100), with: nil))
      XCTAssertNil(grid.hitTest(CGPoint(x: 100, y: -1), with: nil))
      grid.isUserInteractionEnabled = false
      XCTAssertNil(grid.hitTest(CGPoint(x: 100, y: 100), with: nil))
      window.isHidden = true
    }
  }
  func testKeyboardDoesNotCoverSystemMaterialWithAnOpaqueBackground() async {
    await MainActor.run {
      let keyboard = KeyboardViewController()
      keyboard.loadViewIfNeeded()
      XCTAssertTrue(keyboard.view is UIInputView)
      XCTAssertFalse(keyboard.view.isOpaque)
      for appearance in [UIUserInterfaceStyle.light, .dark] {
        let traits = UITraitCollection(userInterfaceStyle: appearance)
        let color = keyboard.view.backgroundColor?.resolvedColor(with: traits)
        XCTAssertEqual(color?.cgColor.alpha, 0)
      }
    }
  }
  func testLocalDictionaryCorrectionAndUndo() async {
    await MainActor.run {
      let field = Field(), assistant = TypingAssistant()
      let portuguese = UITextChecker.availableLanguages.contains { $0.hasPrefix("pt") }
      field.before = portuguese ? "obrigaddo" : "helllo"
      let expected = portuguese ? "obrigado" : "hello"
      XCTAssertTrue(assistant.suggestions(field).contains { $0.value == expected })
      let original = field.before
      assistant.insert(" ", into: field)
      XCTAssertEqual(field.before, expected + " ")
      assistant.delete(in: field)
      XCTAssertEqual(field.before, original)
      assistant.insert(" ", into: field)
      XCTAssertEqual(field.before, original + " ")
    }
  }
  func testFieldsThatDisableCorrectionAndEmailRemainUntouched() async {
    await MainActor.run {
      let field = Field(), assistant = TypingAssistant()
      field.before = "obrigaddo"; field.autocorrectionType = .no
      XCTAssertTrue(assistant.suggestions(field).isEmpty)
      assistant.insert(" ", into: field); XCTAssertEqual(field.before, "obrigaddo ")
      field.autocorrectionType = .yes; field.before = "victor@obrigaddo"
      assistant.insert(" ", into: field); XCTAssertEqual(field.before, "victor@obrigaddo ")
    }
  }
  func testKeyboardLayoutAndPressPreviewInBothAppearances() async {
    await MainActor.run {
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
      let keyboard = KeyboardViewController()
      host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
      keyboard.view.translatesAutoresizingMaskIntoConstraints = false
      NSLayoutConstraint.activate([
        keyboard.view.leadingAnchor.constraint(equalTo: host.view.leadingAnchor),
        keyboard.view.trailingAnchor.constraint(equalTo: host.view.trailingAnchor),
        keyboard.view.bottomAnchor.constraint(equalTo: host.view.bottomAnchor)
      ])
      host.view.layoutIfNeeded()
      func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
      for appearance in [UIUserInterfaceStyle.light, .dark] {
        keyboard.view.overrideUserInterfaceStyle = appearance
        guard let grid = descendants(keyboard.view).compactMap({ $0 as? KeyGridView }).first else {
          XCTFail("Missing key grid"); return
        }
        for page in [KeyboardState.Page.letters, .numbers, .symbols] {
          grid.model.page = page; grid.rebuild(); host.view.layoutIfNeeded()
          let buttons = descendants(grid).compactMap { $0 as? UIButton }
          XCTAssertGreaterThan(buttons.count, 25)
          XCTAssertTrue(buttons.allSatisfy { $0.bounds.width > 20 && $0.bounds.height > 30 })
        }
        grid.model.page = .letters; grid.rebuild(); host.view.layoutIfNeeded()
        let button = descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == "A" }!
        button.isHighlighted = true
        let preview = descendants(keyboard.view).compactMap { $0 as? KeyPreview }.first
        XCTAssertNotNil(preview)
        if let preview = preview {
          XCTAssertTrue(keyboard.view.bounds.contains(preview.frame))
          // The A preview extends above the first key row, as in the reference.
          XCTAssertLessThan(preview.frame.minY, grid.frame.minY)
        }
        let renderer = UIGraphicsImageRenderer(bounds: keyboard.view.bounds)
        let image = renderer.image { keyboard.view.layer.render(in: $0.cgContext) }
        let capture = XCTAttachment(image: image)
        capture.name = appearance == .dark ? "keyboard-dark-press" : "keyboard-light-press"
        capture.lifetime = .keepAlways; self.add(capture)
        button.isHighlighted = false
        XCTAssertFalse(descendants(keyboard.view).contains { $0 is KeyPreview })
      }
      window.isHidden = true
    }
  }
}

import UIKit
import XCTest
@testable import KeyboardUI
import KeyboardHostSupport

@MainActor
private final class Field: NSObject, UITextDocumentProxy {
  var documentIdentifier = UUID()
  var before = ""
  var after = ""
  var contextAvailable = true
  var contextLimit = 50
  var documentContextBeforeInput: String? { contextAvailable ? String(before.suffix(contextLimit)) : nil }
  var documentContextAfterInput: String? { contextAvailable ? String(after.prefix(contextLimit)) : nil }
  var documentInputMode: UITextInputMode? { nil }
  var selectedText: String?
  var hasText: Bool { !before.isEmpty || !after.isEmpty }
  var autocorrectionType: UITextAutocorrectionType = .yes
  var spellCheckingType: UITextSpellCheckingType = .yes
  var keyboardType: UIKeyboardType = .default
  var isSecureTextEntry = false
  var autocapitalizationType: UITextAutocapitalizationType = .sentences
  func insertText(_ text: String) { before += text; selectedText = nil }
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
private final class InputField: UITextField {
  let keyboard = KeyboardViewController()
  override var inputViewController: UIInputViewController? { keyboard }
}

@MainActor
private final class ImpactFeedbackSpy: UIImpactFeedbackGenerator {
  var pulses = 0
  var preparations = 0
  override func impactOccurred() { pulses += 1 }
  override func prepare() { preparations += 1 }
}

final class KeyboardUITests: XCTestCase {
  func testOwnTypingCapitalizesTheNextSentenceWithoutAHostNotification() async throws {
    try await MainActor.run {
      let keyboard = SelectionKeyboard(); keyboard.loadViewIfNeeded()
      let grid = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first)
      for punctuation in [".", "?", "!"] {
        keyboard.field.before = "Olá" + punctuation; keyboard.textDidChange(nil)
        let space = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == L("espaço") })
        space.sendActions(for: .touchUpInside)
        XCTAssertEqual(grid.model.shift, .once)
        let letter = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal)?.lowercased() == "q" })
        letter.sendActions(for: .touchUpInside)
        XCTAssertEqual(keyboard.field.before, "Olá" + punctuation + " Q")
      }
    }
  }
  func testUnchangedLayoutKeepsTheKeysThatMayStillBeTrackingAnotherFinger() async throws {
    try await MainActor.run {
      let grid = KeyGridView(); let before = self.descendants(grid).compactMap { $0 as? UIButton }
      grid.rebuild()
      XCTAssertTrue(before.allSatisfy { $0.isDescendant(of: grid) }, "A refresh must not discard live key controls")
    }
  }
  func testEmptyFieldWithoutContextCapitalizesButUnknownNonemptyContextDoesNot() async throws {
    try await MainActor.run {
      let keyboard = SelectionKeyboard(); keyboard.loadViewIfNeeded()
      let grid = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first)
      keyboard.field.contextAvailable = false; grid.model.shift = .off
      keyboard.textDidChange(nil); XCTAssertEqual(grid.model.shift, .once)
      keyboard.field.before = "word"; grid.model.shift = .off
      keyboard.textDidChange(nil); XCTAssertEqual(grid.model.shift, .off)
      keyboard.field.before = ""; keyboard.field.autocapitalizationType = .none
      keyboard.textDidChange(nil); XCTAssertEqual(grid.model.shift, .off)
    }
  }
  func testLocalAutocorrectionUsesPortugueseEnglishAndSpanishContext() async {
    await MainActor.run {
      let examples = [("pt", "Muito obrigaddo", "Muito obrigado "),
        ("en", "I would say helllo", "I would say hello "),
        ("es", "Nos vemos mañanna", "Nos vemos mañana ")]
      for (language, original, expected) in examples where UITextChecker.availableLanguages.contains(where: { $0.hasPrefix(language) }) {
        let field = Field(), assistant = TypingAssistant(); field.before = original
        assistant.insert(" ", into: field); XCTAssertEqual(field.before, expected, language)
      }
    }
  }
  func testSlidingReleaseOverlapsAndCancelledTouchesDoNotLoseOrDuplicateLetters() async throws {
    try await MainActor.run {
      let grid = KeyGridView(frame: CGRect(x: 0, y: 0, width: 393, height: 220)); grid.layoutIfNeeded()
      @MainActor func key(_ title: String) throws -> UIButton {
        try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == title })
      }
      @MainActor func center(_ key: UIButton) -> CGPoint { key.convert(CGPoint(x: key.bounds.midX, y: key.bounds.midY), to: grid) }
      let q = try key("Q"), w = try key("W")
      let qPoint = center(q), wPoint = center(w)
      var text = ""; grid.onInsert = { text += $0 }
      grid.beginPress(1, at: qPoint); grid.movePress(1, to: wPoint); grid.endPress(1, at: wPoint)
      XCTAssertEqual(text, "W", "Sliding onto a neighbouring key must insert it exactly once")
      grid.layoutIfNeeded()
      let a = try key("a"), s = try key("s")
      grid.beginPress(2, at: center(a)); grid.beginPress(3, at: center(s))
      grid.endPress(2, at: center(a)); grid.model.shift = .once; grid.rebuild()
      XCTAssertTrue(s.isDescendant(of: grid), "Keep the second finger's key during a casing update")
      grid.endPress(3, at: center(s)); XCTAssertEqual(text, "WaS")
      grid.layoutIfNeeded()
      grid.beginPress(4, at: qPoint); grid.cancelPress(4); grid.endPress(4, at: qPoint)
      XCTAssertEqual(text, "WaS", "System cancellations must not insert a key")
      grid.beginPress(5, at: CGPoint(x: 1, y: qPoint.y))
      grid.endPress(5, at: CGPoint(x: -4, y: qPoint.y))
      XCTAssertEqual(text.lowercased(), "wasq", "Small edge drift must not discard a tap")
      grid.model.shift = .once; grid.rebuild(); grid.layoutIfNeeded()
      let upperQ = try key("Q"), upperW = try key("W")
      let first = center(upperQ), second = center(upperW)
      grid.beginPress(6, at: first); grid.beginPress(7, at: second)
      grid.endPress(6, at: first); grid.endPress(7, at: second)
      XCTAssertTrue(text.hasSuffix("Qw"), "Two overlapping fingers consume one-shot shift only once")
    }
  }
  func testCustomVocabularyIsNotReplacedAndQuotedWordsStillCorrect() async {
    await MainActor.run {
      let field = Field(), assistant = TypingAssistant()
      assistant.protectVocabulary(["helllo", "obrigaddo"])
      for word in ["helllo", "obrigaddo"] {
        field.before = word; assistant.insert(" ", into: field); XCTAssertEqual(field.before, word + " ")
      }
      assistant.protectVocabulary([]); field.before = "“helllo"
      assistant.insert(" ", into: field); XCTAssertEqual(field.before, "“hello ")
    }
  }
  @MainActor
  private func makeDictationFixture() throws -> (SelectionKeyboard, SharedState, UIWindow) {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    let store = SharedState(root: root)
    var state = DictationSnapshot(); state.sessionActive = true; state.configured = true
    try store.write(state, to: "state.json")
    let keyboard = SelectionKeyboard(); keyboard.store = store
    let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
    let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
    host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
    keyboard.view.frame = CGRect(x: 0, y: 574, width: 393, height: 278)
    keyboard.beginAppearanceTransition(true, animated: false); keyboard.endAppearanceTransition()
    return (keyboard, store, window)
  }
  @MainActor
  private func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
  @MainActor
  private func publish(_ text: String, to keyboard: SelectionKeyboard, store: SharedState) throws {
    // The real containing app refreshes its heartbeat during editing. This
    // isolated fixture has no audio session or background heartbeat producer.
    var live = store.snapshot(); live.heartbeat = Date().timeIntervalSince1970
    try store.write(live, to: "state.json"); keyboard.viewWillAppear(false)
    let mic = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
    XCTAssertTrue(mic.accessibilityActivate())
    XCTAssertTrue(mic.accessibilityActivate(), "Finish the locked recording before publishing its result")
    let command = try XCTUnwrap(store.commands().last?.1)
    XCTAssertEqual(command.action, "finish")
    var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970
    state.operationID = command.operationID; state.phase = .ready; state.text = text
    try store.write(state, to: "state.json")
    keyboard.viewWillAppear(false)
    XCTAssertEqual(store.receipt(), command.operationID)
  }
  func testDictationUndoRedoPreservesExistingTextAndStopsAfterTyping() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      let edit = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.undo-dictation" })
      XCTAssertTrue(edit.isHidden)
      keyboard.field.before = "Keep this. "; keyboard.field.after = " Keep this too."
      let text = String(repeating: "Texto com ação e 👨‍👩‍👧‍👦. ", count: 60)
      try self.publish(text, to: keyboard, store: store)
      XCTAssertFalse(edit.isHidden); XCTAssertEqual(edit.accessibilityLabel, L("Desfazer ditado"))
      XCTAssertEqual(keyboard.field.before, "Keep this. " + text)
      for _ in 0..<3 {
        edit.sendActions(for: .touchUpInside)
        XCTAssertEqual(keyboard.field.before, "Keep this. ")
        XCTAssertEqual(keyboard.field.after, " Keep this too.")
        XCTAssertEqual(edit.accessibilityLabel, L("Refazer ditado")); XCTAssertFalse(edit.isHidden)
        edit.sendActions(for: .touchUpInside)
        XCTAssertEqual(keyboard.field.before, "Keep this. " + text)
        XCTAssertEqual(edit.accessibilityLabel, L("Desfazer ditado"))
      }
      keyboard.view.layoutIfNeeded()
      let capture = XCTAttachment(image: UIGraphicsImageRenderer(bounds: keyboard.view.bounds).image { keyboard.view.layer.render(in: $0.cgContext) })
      capture.name = "dictation-undo"; capture.lifetime = .keepAlways; self.add(capture)
      let key = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == "Q" })
      key.sendActions(for: .touchUpInside)
      XCTAssertTrue(edit.isHidden)
      let current = keyboard.field.before; edit.sendActions(for: .touchUpInside)
      XCTAssertEqual(keyboard.field.before, current, "A stale action must never delete typed text")
      keyboard.field.before = ""; keyboard.field.after = ""
      try self.publish("Empty field", to: keyboard, store: store)
      edit.sendActions(for: .touchUpInside); XCTAssertEqual(keyboard.field.before, "")
      edit.sendActions(for: .touchUpInside); XCTAssertEqual(keyboard.field.before, "Empty field")
      keyboard.field.before = "Prefix "; keyboard.field.selectedText = "original selection"
      try self.publish("Replacement", to: keyboard, store: store)
      edit.sendActions(for: .touchUpInside); XCTAssertEqual(keyboard.field.before, "Prefix original selection")
      edit.sendActions(for: .touchUpInside); XCTAssertEqual(keyboard.field.before, "Prefix Replacement")
    }
  }
  func testDictationEditInvalidatesForExternalEditsSelectionAndAnotherDocument() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      let edit = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.undo-dictation" })
      try self.publish("Result", to: keyboard, store: store)
      keyboard.field.before += "x"
      let external = keyboard.field.before; edit.sendActions(for: .touchUpInside)
      XCTAssertEqual(keyboard.field.before, external, "Validate again on tap even before the host notifies the keyboard")
      keyboard.textDidChange(nil); XCTAssertTrue(edit.isHidden)
      try self.publish("Next", to: keyboard, store: store)
      keyboard.field.selectedText = "Next"; keyboard.selectionDidChange(nil); XCTAssertTrue(edit.isHidden)
      keyboard.field.selectedText = nil
      try self.publish("Other", to: keyboard, store: store)
      keyboard.field.documentIdentifier = UUID(); keyboard.textDidChange(nil); XCTAssertTrue(edit.isHidden)
      let current = keyboard.field.before; edit.sendActions(for: .touchUpInside)
      XCTAssertEqual(keyboard.field.before, current)
      keyboard.field.contextAvailable = false
      try self.publish("Unavailable", to: keyboard, store: store); XCTAssertTrue(edit.isHidden)
    }
  }
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
      XCTAssertEqual(action.titleLabel?.text, L("Salvo"), "The rendered label must confirm Saved immediately")
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
  func testKeyboardPublishesHeightBeforeTheSystemLoadsItsView() async {
    await MainActor.run {
      let keyboard = KeyboardViewController()
      XCTAssertFalse(keyboard.isViewLoaded)
      XCTAssertEqual(keyboard.preferredContentSize.height, 278,
        "The host needs the final height before it measures the unloaded extension")
      keyboard.loadViewIfNeeded()
      for proposedHeight in [CGFloat(0), 278, 540, 956] {
        keyboard.view.bounds.size = CGSize(width: 393, height: proposedHeight)
        XCTAssertEqual(keyboard.view.sizeThatFits(CGSize(width: 393, height: proposedHeight)).height, 278,
          "A temporary host frame must not become the requested keyboard height")
      }
    }
  }
  @MainActor
  func testRepeatedOpeningThroughTheSystemInputHostKeepsOneHeight() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let window = UIWindow(frame: UIScreen.main.bounds)
    let host = UIViewController(); window.rootViewController = host
    let field = InputField(frame: CGRect(x: 20, y: 100, width: 250, height: 44))
    field.keyboard.store = SharedState(root: root)
    host.view.addSubview(field); window.makeKeyAndVisible()
    defer { field.resignFirstResponder(); window.isHidden = true }
    var heights: [CGFloat] = []
    var requestedHeights: [CGFloat] = []
    let frameObserver = NotificationCenter.default.addObserver(forName: UIResponder.keyboardWillChangeFrameNotification,
      object: nil, queue: .main) { note in
        guard field.isFirstResponder,
              let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect,
              frame.height > 0 else { return }
        requestedHeights.append(frame.height)
      }
    defer { NotificationCenter.default.removeObserver(frameObserver) }
    for _ in 0..<3 {
      let shown = expectation(description: "System keyboard finished presenting")
      var didShow = false
      let observer = NotificationCenter.default.addObserver(forName: UIResponder.keyboardDidShowNotification,
        object: nil, queue: .main) { note in
          guard !didShow else { return }
          didShow = true
          if let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect {
            heights.append(frame.height)
          }
          shown.fulfill()
        }
      XCTAssertTrue(field.becomeFirstResponder(), "The fixture must reach the real input host")
      await fulfillment(of: [shown], timeout: 5)
      NotificationCenter.default.removeObserver(observer)
      XCTAssertEqual(field.keyboard.view.bounds.height, 278, accuracy: 0.5)
      let hidden = expectation(description: "System keyboard finished dismissing")
      var didHide = false
      let hideObserver = NotificationCenter.default.addObserver(forName: UIResponder.keyboardDidHideNotification,
        object: nil, queue: .main) { _ in
          guard !didHide else { return }
          didHide = true; hidden.fulfill()
        }
      field.resignFirstResponder()
      await fulfillment(of: [hidden], timeout: 5)
      NotificationCenter.default.removeObserver(hideObserver)
    }
    XCTAssertEqual(heights.count, 3)
    if let height = heights.first {
      XCTAssertLessThan(height, window.bounds.height / 2, "Opening must not reserve a screen-sized keyboard")
      XCTAssertTrue(heights.allSatisfy { abs($0 - height) < 0.5 })
      XCTAssertFalse(requestedHeights.isEmpty)
      XCTAssertTrue(requestedHeights.allSatisfy { $0 <= height + 0.5 }, "No presentation frame may reserve an oversized keyboard")
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
        // Capture keys against lighter host materials as well as the transparent
        // fixture. A fixed dark-gray fill can disappear against these surfaces.
        for background in [CGFloat(0.12), 0.28, 0.4] where appearance == .dark {
          keyboard.view.backgroundColor = UIColor(white: background, alpha: 1)
          let material = XCTAttachment(image: renderer.image { keyboard.view.layer.render(in: $0.cgContext) })
          material.name = "keyboard-dark-material-\(background)"
          material.lifetime = .keepAlways; self.add(material)
        }
        keyboard.view.backgroundColor = .clear
      }
      window.isHidden = true
    }
  }
}

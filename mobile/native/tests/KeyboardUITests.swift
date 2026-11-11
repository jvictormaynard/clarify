import UIKit
import XCTest
@testable import KeyboardUI
import KeyboardHostSupport

private final class AccentGesture: UILongPressGestureRecognizer {
  var sampleState: UIGestureRecognizer.State = .possible
  var samplePoint = CGPoint.zero
  override var state: UIGestureRecognizer.State {
    get { sampleState }
    set { sampleState = newValue }
  }
  override func location(in view: UIView?) -> CGPoint { samplePoint }
}

private final class SourceProcessState: NSObject {
  var pid: Int32 = 5127
  var source: Any? = "com.clarify.fixture.host"
  var replacementPID: Int32?
  @objc var processIdentifier: Int32 { pid }
  @objc var sourceBundleIdentifier: Any? {
    if let replacementPID { pid = replacementPID }
    return source
  }
}

private final class UnexpectedSourceProcessState: NSObject {
  @objc var processIdentifier: String { "5127" }
  @objc var sourceBundleIdentifier: String { "com.clarify.fixture.host" }
}

@MainActor
private final class Field: NSObject, UITextDocumentProxy {
  var documentIdentifier = UUID()
  var before = ""
  var after = ""
  var contextAvailable = true
  var contextLimit = 50
  var afterContextLimit: Int?
  var deferCaretContext = false
  var retainedCaretContext: (before: String, after: String)?
  func flushCaretContext() { retainedCaretContext = nil }
  var documentContextBeforeInput: String? { contextAvailable ? String((retainedCaretContext?.before ?? before).suffix(contextLimit)) : nil }
  var documentContextAfterInput: String? { contextAvailable ? String((retainedCaretContext?.after ?? after).prefix(afterContextLimit ?? contextLimit)) : nil }
  var documentInputMode: UITextInputMode? { nil }
  var selectedText: String?
  var hasText: Bool { !before.isEmpty || !after.isEmpty }
  var autocorrectionType: UITextAutocorrectionType = .yes
  var spellCheckingType: UITextSpellCheckingType = .yes
  var keyboardType: UIKeyboardType = .default
  var keyboardAppearance: UIKeyboardAppearance = .default
  var returnKeyType: UIReturnKeyType = .default
  var isSecureTextEntry = false
  var autocapitalizationType: UITextAutocapitalizationType = .sentences
  var didInsert: ((String) -> Void)?
  var didAdjust: (() -> Void)?
  func insertText(_ text: String) {
    before += text; selectedText = nil; didInsert?(before)
  }
  func deleteBackward() { if !before.isEmpty { before.removeLast() } }
  func adjustTextPosition(byCharacterOffset offset: Int) {
    if deferCaretContext, retainedCaretContext == nil { retainedCaretContext = (before, after) }
    let text = before + after
    let position = min(text.utf16.count, max(0, before.utf16.count + offset))
    let index16 = text.utf16.index(text.utf16.startIndex, offsetBy: position)
    guard let index = String.Index(index16, within: text) else { return }
    before = String(text[..<index]); after = String(text[index...])
    didAdjust?()
  }
  func setMarkedText(_ markedText: String, selectedRange: NSRange) {}
  func unmarkText() {}
}

@MainActor
private final class SelectionKeyboard: KeyboardViewController {
  let field = Field()
  var fullAccess = true
  override var textDocumentProxy: UITextDocumentProxy { field }
  override var hasFullAccess: Bool { fullAccess }
  // This ordinary child-controller fixture has no system input-mode host.
  // The real InputField and opening diagnostic retain UIKit's host query.
  override var needsInputModeSwitchKey: Bool { false }
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
  func testAutocorrectIsOptInAndKeepsTheOutputCapsuleVisible() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      XCTAssertFalse(store.keyboardAutocorrectEnabled())
      let assistant = TypingAssistant(autocorrectionEnabled: store.keyboardAutocorrectEnabled())
      let field = Field(); field.before = "I would say helllo"
      XCTAssertTrue(assistant.suggestions(field).isEmpty)
      assistant.insert(" ", into: field)
      XCTAssertEqual(field.before, "I would say helllo ")
      let row = try XCTUnwrap(self.descendants(keyboard.view).first { $0.accessibilityIdentifier == "clarify.keyboard.suggestions" })
      keyboard.refreshFromStore(); XCTAssertTrue(row.isHidden)
      try store.setKeyboardAutocorrectEnabled(true)
      XCTAssertTrue(SharedState(root: store.root).keyboardAutocorrectEnabled())
      keyboard.field.before = "I would say helllo"
      keyboard.refreshFromStore()
      let capsule = try self.outputCapsule(keyboard)
      for width in [CGFloat(320), 393, 430] {
        for button in (row as? UIStackView)?.arrangedSubviews.compactMap({ $0 as? UIButton }) ?? [] {
          button.setTitle("extraordinarilylongsuggestion", for: .normal)
        }
        keyboard.view.frame.size.width = width; keyboard.view.layoutIfNeeded()
        XCTAssertFalse(row.isHidden)
        XCTAssertEqual(capsule.bounds.width, capsule.intrinsicContentSize.width, accuracy: 1,
          "Long suggestions must not compress the capsule or add empty side space")
        XCTAssertLessThanOrEqual(capsule.frame.maxX, row.frame.minX)
        let compactWidth = capsule.bounds.width
        keyboard.field.selectedText = "Clarify"; keyboard.selectionDidChange(nil)
        keyboard.view.layoutIfNeeded(); capsule.layoutIfNeeded()
        XCTAssertNotNil(capsule.configuration?.image)
        XCTAssertGreaterThan(capsule.bounds.width, compactWidth,
          "Selecting text must expand the capsule to fit the wand")
        XCTAssertEqual(capsule.bounds.width, capsule.intrinsicContentSize.width, accuracy: 1)
        keyboard.field.selectedText = nil; keyboard.selectionDidChange(nil)
        keyboard.view.layoutIfNeeded(); capsule.layoutIfNeeded()
        XCTAssertNil(capsule.configuration?.image)
        XCTAssertEqual(capsule.bounds.width, compactWidth, accuracy: 1,
          "Clearing selection must restore the compact width")
      }
      assistant.autocorrectionEnabled = true
      field.before = "I would say helllo"; assistant.insert(" ", into: field)
      XCTAssertEqual(field.before, "I would say hello ")
      assistant.autocorrectionEnabled = false
      assistant.delete(in: field)
      XCTAssertEqual(field.before, "I would say hello", "Disabling must discard correction undo state")
      try store.setKeyboardAutocorrectEnabled(false)
      keyboard.refreshFromStore(); XCTAssertTrue(row.isHidden)
      XCTAssertFalse(SharedState(root: store.root).keyboardAutocorrectEnabled())
    }
  }
  func testInactiveMicrophoneErrorLeavesTypingAvailableAcrossKeyboardOpenings() async throws {
    try await MainActor.run {
      let (original, store, window) = try self.makeDictationFixture()
      var keyboard = original
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      for expiredHeartbeat in [false, true] {
        var state = store.snapshot(); state.phase = .error
        state.message = L("O áudio foi interrompido. Abra o Clarify para reativar o microfone.")
        state.sessionActive = expiredHeartbeat
        state.heartbeat = Date().timeIntervalSince1970 - (expiredHeartbeat ? 4 : 0)
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        for _ in 0..<2 {
          keyboard = try self.replaceKeyboard(keyboard, store: store, window: window)
          keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
          let panel = try XCTUnwrap(self.descendants(keyboard.view).first { $0.accessibilityIdentifier == "clarify.keyboard.recording-panel" })
          let grid = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first)
          XCTAssertTrue(panel.isHidden, "An inactive microphone must not require dismissing an error")
          XCTAssertFalse(grid.isHidden)
          let key = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.currentTitle?.lowercased() == "a" })
          let before = keyboard.field.before
          key.sendActions(for: .touchUpInside)
          XCTAssertEqual(keyboard.field.before.lowercased(), before.lowercased() + "a")
          XCTAssertTrue(store.commands().isEmpty, "Typing must not start dictation")
        }
      }
    }
  }
  func testErrorCauseRemainsVisibleBesidePermanentCapsuleAndRecoverableText() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      let caption = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UILabel }.first { $0.accessibilityIdentifier == "clarify.keyboard.recording-status" })
      let panel = try XCTUnwrap(self.descendants(keyboard.view).first { $0.accessibilityIdentifier == "clarify.keyboard.recording-panel" })
      let capsule = try self.outputCapsule(keyboard)
      for language in ["pt", "en", "es"] {
        for width in [CGFloat(320), 375, 430] {
          var state = store.snapshot(); state.phase = .error; state.operationID = UUID().uuidString
          state.message = L("A reescrita falhou. Você pode inserir a transcrição original.", language: language)
          state.text = "Preserved original"; state.heartbeat = Date().timeIntervalSince1970
          try store.write(state, to: "state.json"); keyboard.refreshFromStore()
          keyboard.view.frame.size.width = width; keyboard.view.layoutIfNeeded()
          XCTAssertFalse(caption.isHidden); XCTAssertEqual(caption.text, state.message)
          XCTAssertFalse(capsule.isHidden); XCTAssertEqual(capsule.accessibilityHint, state.message)
          let genericHeight = (caption.text! as NSString).boundingRect(with: CGSize(width: caption.bounds.width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: [.font: caption.font!], context: nil).height
          // Use UILabel's drawing metrics for clipping; NSString's optional
          // font leading is retained only as diagnostic data.
          let required = caption.textRect(forBounds: CGRect(x: 0, y: 0, width: caption.bounds.width,
            height: .greatestFiniteMagnitude), limitedToNumberOfLines: 0).height
          XCTAssertEqual(caption.numberOfLines, 0)
          XCTAssertLessThanOrEqual(ceil(required), caption.bounds.height + 1)
          XCTAssertTrue(panel.bounds.contains(caption.convert(caption.bounds, to: panel)))
          XCTAssertEqual(keyboard.view.bounds.height, KeyboardInputView.contentHeight)
          XCTAssertTrue(keyboard.view.bounds.contains(capsule.frame))
          let captureName = "error-caption-\(language)-\(Int(width))"
          let capture = XCTAttachment(image: UIGraphicsImageRenderer(bounds: keyboard.view.bounds).image { keyboard.view.layer.render(in: $0.cgContext) })
          capture.name = captureName; capture.lifetime = .keepAlways; self.add(capture)
          let metrics = XCTAttachment(string: "UILabel=\(required), NSStringWithLeading=\(genericHeight), available=\(caption.bounds.height)")
          metrics.name = captureName + "-metrics"; metrics.lifetime = .keepAlways; self.add(metrics)
        }
      }
    }
  }
  @MainActor
  func testReopeningAppliesHostInputTraitsWithoutATextChange() throws {
    let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 402, height: 874))
    let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
    defer { window.isHidden = true }
    let keyboard = SelectionKeyboard()
    host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
    let grid = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first)
    keyboard.field.before = "Q"
    let cases: [(UIKeyboardAppearance, UIReturnKeyType, UIUserInterfaceStyle)] = [
      (.light, .search, .dark), (.dark, .done, .light), (.default, .default, .dark)
    ]
    for (appearance, returnType, expectedStyle) in cases {
      // The remote proxy can lag behind the host's current appearance.
      keyboard.field.keyboardAppearance = appearance; keyboard.field.returnKeyType = returnType
      host.setOverrideTraitCollection(UITraitCollection(userInterfaceStyle: expectedStyle), forChild: keyboard)
      keyboard.beginAppearanceTransition(true, animated: false); keyboard.endAppearanceTransition()
      keyboard.view.layoutIfNeeded()
      XCTAssertEqual(keyboard.traitCollection.userInterfaceStyle, expectedStyle)
      XCTAssertEqual(keyboard.view.overrideUserInterfaceStyle, .unspecified)
      XCTAssertEqual(keyboard.view.traitCollection.userInterfaceStyle, expectedStyle)
      XCTAssertEqual(grid.traitCollection.userInterfaceStyle, expectedStyle)
      XCTAssertEqual(grid.returnType, returnType)
      XCTAssertEqual(keyboard.field.before, "Q", "Applying input traits must not modify the draft")
      keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
    }
  }
  func testOwnTypingCapitalizesTheNextSentenceWithoutAHostNotification() async throws {
    try await MainActor.run {
      let keyboard = SelectionKeyboard(); keyboard.loadViewIfNeeded()
      let grid = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first)
      for punctuation in [".", "?", "!"] {
        keyboard.field.before = "Olá" + punctuation; keyboard.textDidChange(nil)
        let space = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("espaço") })
        space.sendActions(for: .touchUpInside)
        XCTAssertEqual(grid.model.shift, .once)
        let letter = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal)?.lowercased() == "q" })
        letter.sendActions(for: .touchUpInside)
        XCTAssertEqual(keyboard.field.before, "Olá" + punctuation + " Q")
      }
      let cases: [(UITextAutocapitalizationType, String, KeyboardState.Shift)] = [
        (.sentences, "", .once), (.sentences, "word ", .off), (.words, "", .off),
        (.none, "", .off), (.allCharacters, "", .caps)
      ]
      for (type, prefix, expected) in cases {
        keyboard.field.autocapitalizationType = type
        keyboard.field.before = prefix; keyboard.textDidChange(nil)
        let mode = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == "123" })
        mode.sendActions(for: .touchUpInside)
        let digit = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == "1" })
        digit.sendActions(for: .touchUpInside)
        XCTAssertEqual(keyboard.field.before, prefix + "1")
        XCTAssertEqual(grid.model.shift, expected, "Apply host capitalization to local digit insertion without a notification")
        let letters = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.title(for: .normal) == "ABC" })
        letters.sendActions(for: .touchUpInside)
        XCTAssertNotNil(self.descendants(grid).compactMap { $0 as? UIButton }.first {
          $0.title(for: .normal) == (expected == .off ? "q" : "Q")
        })
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
      let letters = text
      let mode = try key("123"), modePoint = center(mode)
      grid.beginPress("number-tap", at: modePoint)
      XCTAssertEqual(grid.model.page, .numbers, "Show the number page while the finger is held")
      XCTAssertTrue(mode.isDescendant(of: grid), "Keep UIKit's original touch receiver attached")
      grid.endPress("number-tap", at: modePoint)
      XCTAssertEqual(grid.model.page, .numbers, "A plain 123 tap must keep the number page")
      XCTAssertEqual(text, letters)
      try key("ABC").sendActions(for: .touchUpInside)
      grid.beginPress("number-slide", at: center(try key("123")))
      let one = center(try key("1"))
      grid.movePress("number-slide", to: one); grid.endPress("number-slide", at: one)
      grid.endPress("number-slide", at: one)
      XCTAssertEqual(text, letters + "1", "A number slide inserts its release target exactly once")
      XCTAssertEqual(grid.model.page, .letters)
      for cancel in [true, false] {
        grid.beginPress("aborted-slide", at: center(try key("123")))
        let point = center(try key("1")); grid.movePress("aborted-slide", to: point)
        if cancel { grid.cancelPress("aborted-slide") }
        else { grid.endPress("aborted-slide", at: CGPoint(x: -30, y: -30)) }
        grid.endPress("aborted-slide", at: point)
        XCTAssertEqual(text, letters + "1", "Cancelled or outside slides must not insert")
        XCTAssertEqual(grid.model.page, .letters)
      }
      grid.beginPress("number-owner", at: center(try key("123")))
      let held = try key("1"), heldPoint = center(held), two = center(try key("2"))
      grid.beginPress("held-digit", at: heldPoint)
      grid.movePress("number-owner", to: two); grid.endPress("number-owner", at: two)
      XCTAssertTrue(held.isDescendant(of: grid), "Defer the return to letters until the other finger finishes")
      grid.endPress("held-digit", at: heldPoint)
      XCTAssertEqual(text, letters + "121", "Changing the page must not lose another finger's digit")
      XCTAssertEqual(grid.model.page, .letters)
      grid.onInsert = { [weak grid] value in
        text += value; grid?.returnType = .search; grid?.rebuild()
      }
      grid.beginPress("space-slide", at: center(try key("123")))
      let space = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("espaço") })
      grid.endPress("space-slide", at: center(space))
      XCTAssertEqual(text, letters + "121 ")
      XCTAssertEqual(grid.model.page, .letters)
      XCTAssertNotNil(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("buscar") },
                      "Apply host traits to the retained row when insertion changes pages")
      grid.onInsert = { text += $0 }
      @MainActor func shiftKey() throws -> UIButton {
        try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("Maiúsculas") })
      }
      let beforeShift = text, shift = try shiftKey(), lowerQ = try key("q"), lowerFrame = lowerQ.frame
      let shiftPoint = center(shift), letterPoint = center(lowerQ)
      grid.beginPress("shift-slide", at: shiftPoint)
      XCTAssertTrue(shift.isDescendant(of: grid) && lowerQ.isDescendant(of: grid), "Casing must keep both UIKit touch receivers attached")
      XCTAssertEqual(lowerQ.title(for: .normal), "Q")
      XCTAssertEqual(lowerQ.frame, lowerFrame, "A casing change must keep the key's hit bounds")
      let accent = try key("A")
      XCTAssertTrue(accent.accessibilityCustomActions?.contains { $0.name == "Á" } == true)
      grid.endPress("shift-slide", at: letterPoint); grid.endPress("shift-slide", at: letterPoint)
      XCTAssertEqual(text, beforeShift + "Q", "A Shift slide inserts its capital exactly once")
      XCTAssertEqual(lowerQ.title(for: .normal), "q")
      grid.model.toggleShift(); grid.model.toggleShift(); grid.rebuild()
      for cancel in [true, false] {
        grid.beginPress("aborted-shift", at: center(try shiftKey()))
        if cancel { grid.cancelPress("aborted-shift") }
        else { grid.endPress("aborted-shift", at: CGPoint(x: -30, y: -30)) }
        grid.endPress("aborted-shift", at: letterPoint)
        XCTAssertEqual(text, beforeShift + "Q")
        XCTAssertEqual(grid.model.shift, .off)
        XCTAssertTrue(grid.model.shiftIsManual, "Cancelled Shift must preserve the user's explicit lowercase choice")
      }
      let chordShift = try shiftKey(), chordPoint = center(chordShift)
      grid.beginPress("shift-chord", at: chordPoint)
      for title in ["Q", "W"] {
        let point = center(try key(title))
        grid.beginPress("chord-letter", at: point); grid.endPress("chord-letter", at: point)
        XCTAssertTrue(chordShift.isDescendant(of: grid))
      }
      grid.endPress("shift-chord", at: chordPoint)
      XCTAssertEqual(text, beforeShift + "QQW")
      XCTAssertEqual(grid.model.shift, .off, "A consumed Shift chord must not arm the next letter")
      grid.beginPress("cancelled-owner", at: center(try shiftKey()))
      let heldLetter = try key("Q"), heldLetterPoint = center(heldLetter)
      grid.beginPress("held-letter", at: heldLetterPoint); grid.cancelPress("cancelled-owner")
      XCTAssertTrue(heldLetter.isDescendant(of: grid))
      grid.endPress("held-letter", at: heldLetterPoint)
      XCTAssertEqual(text, beforeShift + "QQWq", "Releasing Shift must not lose another finger's letter")
      let tapPoint = center(try shiftKey())
      grid.beginPress("shift-tap", at: tapPoint); grid.endPress("shift-tap", at: tapPoint)
      XCTAssertEqual(grid.model.shift, .once, "A plain Shift tap still arms one capital")
      let capitalPoint = center(try key("Q"))
      grid.beginPress("capital", at: capitalPoint); grid.endPress("capital", at: capitalPoint)
      XCTAssertEqual(text, beforeShift + "QQWqQ")
      XCTAssertEqual(grid.model.shift, .off)
      let pageShift = center(try shiftKey()), pageMode = center(try key("123"))
      grid.beginPress("page-shift", at: pageShift); grid.beginPress("page-mode", at: pageMode)
      grid.endPress("page-mode", at: pageMode); grid.endPress("page-shift", at: pageShift)
      XCTAssertEqual(grid.model.page, .numbers, "A late Shift release must not toggle another finger's page choice")
      XCTAssertEqual(text, beforeShift + "QQWqQ")
      grid.model.page = .letters; grid.model.shift = .off; grid.rebuild(); grid.layoutIfNeeded()
      @MainActor func emit(_ gesture: AccentGesture, _ phase: UIGestureRecognizer.State, at point: CGPoint = .zero) {
        gesture.sampleState = phase; gesture.samplePoint = point
        _ = grid.perform(NSSelectorFromString("accent:"), with: gesture)
      }
      @MainActor func startAccent(_ title: String = "e") throws -> AccentGesture {
        let letter = try key(title), gesture = AccentGesture()
        letter.addGestureRecognizer(gesture)
        grid.beginPress("accent", at: center(letter)); emit(gesture, .began)
        // UIKit cancels the key's original touch when its recognizer accepts.
        grid.cancelPress("accent"); grid.layoutIfNeeded()
        return gesture
      }
      @MainActor func accentPoint(_ title: String) throws -> CGPoint {
        let picker = try XCTUnwrap(grid.subviews.compactMap { $0 as? UIStackView }.first {
          $0.arrangedSubviews.contains { ($0 as? UIButton)?.title(for: .normal) == title }
        })
        picker.layoutIfNeeded()
        let choice = try XCTUnwrap(picker.arrangedSubviews.compactMap { $0 as? UIButton }.first {
          $0.title(for: .normal) == title
        })
        return choice.convert(CGPoint(x: choice.bounds.midX, y: choice.bounds.midY), to: picker)
      }
      let beforeAccent = text, stationary = try startAccent(), otherChoice = try accentPoint("è")
      emit(stationary, .ended, at: otherChoice); emit(stationary, .ended, at: otherChoice)
      XCTAssertEqual(text, beforeAccent + "e", "Release must commit the displayed base letter exactly once")
      let nextPoint = center(try key("q"))
      grid.beginPress("after-accent", at: nextPoint); grid.endPress("after-accent", at: nextPoint)
      XCTAssertEqual(text, beforeAccent + "eq", "Accent recognition must not suppress the next tap")
      let dragged = try startAccent(), foreign = AccentGesture()
      try key("a").addGestureRecognizer(foreign)
      emit(foreign, .began); emit(foreign, .ended)
      XCTAssertEqual(text, beforeAccent + "eq", "Another recognizer must not consume the active picker")
      emit(dragged, .changed, at: try accentPoint("è")); emit(dragged, .ended)
      emit(dragged, .ended)
      XCTAssertEqual(text, beforeAccent + "eqè", "Release must keep the last highlighted drag choice")
      for phase in [UIGestureRecognizer.State.cancelled, .failed] {
        let cancelled = try startAccent()
        emit(cancelled, .changed, at: try accentPoint("é")); emit(cancelled, phase)
        emit(cancelled, .ended)
        XCTAssertEqual(text, beforeAccent + "eqè", "Cancelled and stale callbacks must not insert")
      }
      let reentrant = try startAccent(), beforeCallback = text
      grid.onInsert = { value in
        text += value
        if value == "e" {
          guard let next = try? key("q") else { XCTFail("Missing next key during insertion"); return }
          let point = center(next)
          grid.beginPress("reentrant-next", at: point); grid.endPress("reentrant-next", at: point)
        }
      }
      emit(reentrant, .ended)
      XCTAssertEqual(text, beforeCallback + "eq", "Insertion callbacks must see the completed accent's suppression cleared")
      grid.onInsert = { text += $0 }
      let pickerHost = UIView(frame: CGRect(x: 0, y: 0, width: grid.bounds.width, height: grid.bounds.height + 58))
      let toolbarCover = UIView(frame: CGRect(x: 0, y: 7, width: grid.bounds.width, height: 44))
      grid.frame.origin.y = 58
      pickerHost.addSubview(grid); pickerHost.addSubview(toolbarCover)
      for (title, width) in [("e", CGFloat(393)), ("u", 393), ("e", 320)] {
        pickerHost.frame.size.width = width; toolbarCover.frame.size.width = width
        grid.frame.size.width = width; grid.layoutIfNeeded()
        let letter = try key(title), beforeJitter = text, held = try startAccent(title)
        let picker = try XCTUnwrap(grid.subviews.compactMap { $0 as? UIStackView }.first {
          $0.arrangedSubviews.contains { ($0 as? UIButton)?.title(for: .normal) == title }
        })
        let basePoint = try accentPoint(title)
        let sourcePoint = letter.convert(CGPoint(x: letter.bounds.midX, y: letter.bounds.midY), to: picker)
        XCTAssertEqual(basePoint.x, sourcePoint.x, accuracy: 0.5, "The base choice must align with the held key")
        XCTAssertLessThanOrEqual(picker.frame.maxY, letter.convert(letter.bounds, to: grid).minY)
        XCTAssertGreaterThanOrEqual(picker.frame.minX, 6); XCTAssertLessThanOrEqual(picker.frame.maxX, grid.bounds.width - 6)
        XCTAssertTrue(pickerHost.subviews.last === grid, "Sibling toolbars must not cover the picker above the held key")
        let pickerPoint = picker.convert(basePoint, to: pickerHost)
        let receiver = try XCTUnwrap(pickerHost.hitTest(pickerPoint, with: nil))
        XCTAssertTrue(receiver === picker || receiver.isDescendant(of: picker), "A second finger on the picker must not reach toolbar actions")
        grid.isUserInteractionEnabled = false
        XCTAssertTrue(pickerHost.hitTest(pickerPoint, with: nil) === toolbarCover)
        grid.isUserInteractionEnabled = true
        let foreignPoint = picker.convert(basePoint, to: grid)
        grid.beginPress("picker-foreign", at: foreignPoint); grid.endPress("picker-foreign", at: foreignPoint)
        XCTAssertEqual(text, beforeJitter, "Only the held accent gesture may insert a choice")
        emit(held, .changed, at: CGPoint(x: sourcePoint.x + 1, y: sourcePoint.y))
        emit(held, .ended)
        XCTAssertEqual(text, beforeJitter + title, "Small finger movement must retain the displayed base choice")
      }
      for choice in ["ę", "ė", "ē"] {
        let letter = try key("e"), beforeChoice = text
        XCTAssertTrue(letter.accessibilityCustomActions?.contains { $0.name == choice } == true)
        let held = try startAccent()
        emit(held, .changed, at: try accentPoint(choice)); emit(held, .ended); emit(held, .ended)
        XCTAssertEqual(text, beforeChoice + choice, "A newly offered accent must commit exactly once")
      }
      let cancellationWindow = UIWindow(frame: pickerHost.bounds)
      cancellationWindow.addSubview(pickerHost)
      defer { withExtendedLifetime(cancellationWindow) { pickerHost.removeFromSuperview() } }
      for cancellation in ["all", "hide", "detach"] {
        XCTAssertNotNil(grid.window)
        let beforeCancellation = text, held = try startAccent()
        emit(held, .changed, at: try accentPoint("é"))
        let picker = try XCTUnwrap(grid.subviews.compactMap { $0 as? UIStackView }.first {
          $0.arrangedSubviews.contains { ($0 as? UIButton)?.title(for: .normal) == "é" }
        })
        grid.model.shift = .caps; grid.rebuild()
        switch cancellation {
        case "hide": grid.isHidden = true
        case "detach": grid.removeFromSuperview()
        default: grid.cancelAllPresses()
        }
        XCTAssertNil(picker.superview, "Cancelling the keyboard must remove its accent picker: \(cancellation)")
        emit(held, .changed); emit(held, .ended)
        XCTAssertEqual(text, beforeCancellation, "A cancelled accent must reject late callbacks: \(cancellation)")
        _ = try key("Q")
        grid.isHidden = false
        if grid.superview == nil { pickerHost.addSubview(grid) }
        grid.model.shift = .off; grid.rebuild(); grid.layoutIfNeeded()
        let restarted = try startAccent()
        emit(held, .ended); emit(restarted, .ended)
        let next = center(try key("q"))
        grid.beginPress("after-cancellation", at: next); grid.endPress("after-cancellation", at: next)
        XCTAssertEqual(text, beforeCancellation + "eq", "A stale owner must not consume a new picker or tap")
      }
      var clock: TimeInterval = 100, offsets: [Int] = [], finishes = 0
      grid.cursorUptime = { clock }; grid.onMoveCursor = { offsets.append($0); return true }
      grid.onEndCursor = { finishes += 1 }
      @MainActor func spacePoint() throws -> CGPoint {
        center(try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("espaço") }))
      }
      let cursorPoint = try spacePoint(), beforeCursor = text
      grid.beginPress("cursor", at: cursorPoint); clock += 0.1; grid.updateSpaceHold()
      grid.endPress("cursor", at: cursorPoint)
      XCTAssertEqual(text, beforeCursor + " ", "A short Space press still inserts")
      let afterTap = text
      grid.beginPress("cursor", at: try spacePoint()); clock += 1; grid.updateSpaceHold()
      let heldSpace = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("espaço") })
      grid.model.shift = .once; grid.rebuild()
      XCTAssertTrue(heldSpace.isDescendant(of: grid), "Cursor mode must keep the original UIKit receiver attached")
      let other = center(try key("q"))
      grid.beginPress("foreign", at: other); grid.cancelPress("foreign"); grid.endPress("foreign", at: other)
      grid.movePress("cursor", to: cursorPoint.applying(CGAffineTransform(translationX: -12, y: -100)))
      grid.movePress("cursor", to: cursorPoint)
      grid.endPress("cursor", at: cursorPoint); grid.endPress("cursor", at: other)
      XCTAssertEqual(offsets, [-2, 2]); XCTAssertEqual(text, afterTap, "Held release and a second finger must not insert")
      XCTAssertEqual(grid.model.shift, .once)
      for cancelled in [true, false] {
        let point = try spacePoint()
        grid.beginPress("cancel-cursor", at: point); clock += 1; grid.updateSpaceHold()
        if cancelled { grid.cancelPress("cancel-cursor") } else { grid.isHidden = true; grid.isHidden = false }
        grid.movePress("cancel-cursor", to: other); grid.endPress("cancel-cursor", at: other)
        XCTAssertEqual(text, afterTap, "Cancellation, hiding and late releases must not insert")
      }
      let completed = finishes
      grid.beginPress("early", at: try spacePoint()); grid.cancelPress("early")
      grid.beginPress("early", at: try spacePoint()); grid.updateSpaceHold()
      grid.endPress("early", at: try spacePoint())
      XCTAssertEqual(text, afterTap + " ", "A reused touch ID must get a new hold interval")
      XCTAssertEqual(finishes, completed + 2)
      grid.model.shift = .off; grid.rebuild()
      let beforeOverlap = text, overlapSpace = try spacePoint(), overlapQ = center(try key("q"))
      grid.beginPress("pending-space", at: overlapSpace); grid.beginPress("overlap-letter", at: overlapQ)
      clock += 1; grid.updateSpaceHold()
      grid.endPress("overlap-letter", at: overlapQ); grid.endPress("pending-space", at: overlapSpace)
      XCTAssertEqual(text, beforeOverlap + "q ", "An overlapping tap must keep normal typing instead of entering cursor mode")
      let beforeReentry = text, point = try spacePoint()
      grid.onMoveCursor = { _ in grid.cancelPress("reentrant-cursor"); return true }
      grid.beginPress("reentrant-cursor", at: point); clock += 1; grid.updateSpaceHold()
      grid.movePress("reentrant-cursor", to: CGPoint(x: point.x - 20, y: point.y))
      grid.endPress("reentrant-cursor", at: other)
      XCTAssertEqual(text, beforeReentry, "Movement callbacks must not revive a cancelled owner")
    }
  }
  func testHeldDeleteDoesNotRestartAfterReentrantCancellation() async throws {
    for cancelOnDelete in [1, 2] {
      let cancelled = expectation(description: "Delete callback cancels its press")
      let lateDelete = expectation(description: "Cancelled hold must not delete again")
      lateDelete.isInverted = true
      let grid = await MainActor.run { KeyGridView(frame: CGRect(x: 0, y: 0, width: 393, height: 220)) }
      let cancelAction = try await MainActor.run {
        grid.layoutIfNeeded()
        let key = try XCTUnwrap(self.descendants(grid).compactMap { $0 as? UIButton }.first { $0.accessibilityLabel == L("Apagar") })
        let begin = try XCTUnwrap(key.actions(forTarget: grid, forControlEvent: .touchDown)?.first)
        let cancel = try XCTUnwrap(key.actions(forTarget: grid, forControlEvent: .touchCancel)?.first)
        var deletions = 0
        grid.onDelete = { [weak grid] in
          deletions += 1
          if deletions == cancelOnDelete {
            _ = grid?.perform(NSSelectorFromString(cancel)); cancelled.fulfill()
          } else if deletions > cancelOnDelete { lateDelete.fulfill() }
        }
        // Unhosted UIKit tests have no UIApplication to dispatch target actions.
        _ = grid.perform(NSSelectorFromString(begin))
        XCTAssertEqual(deletions, 1, "Delete must begin before observing repeat cancellation")
        return cancel
      }
      await fulfillment(of: [cancelled], timeout: 2)
      await fulfillment(of: [lateDelete], timeout: 0.55)
      await MainActor.run { _ = grid.perform(NSSelectorFromString(cancelAction)); grid.onDelete = nil }
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
  func testWordSavedFromTheKeyboardIsProtectedBeforeTheNextSpace() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: []))
      keyboard.field.before = "helllo"; keyboard.field.selectedText = "helllo"
      keyboard.selectionDidChange(nil)
      let save = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.output-preferences" })
      XCTAssertTrue(save.isEnabled); keyboard.saveSelectedTerm()
      XCTAssertEqual(store.keyboardAdditions(scope: "guest").map { $0.1.term }, ["helllo"])
      keyboard.field.selectedText = nil; keyboard.selectionDidChange(nil)
      let space = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityLabel == L("espaço") })
      space.sendActions(for: .touchUpInside)
      XCTAssertEqual(keyboard.field.before, "helllo ", "A newly saved word must not wait for the vocabulary cache to expire")
    }
  }
  @MainActor
  private func makeDictationFixture() throws -> (SelectionKeyboard, SharedState, UIWindow) {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    let store = SharedState(root: root)
    var state = DictationSnapshot(); state.sessionActive = true; state.configured = true
    state.textActions = .unsupported; state.legacyRewriteReady = true; state.legacyTranslateReady = true
    state.outputPreferencesSupported = true; state.toneAllowed = true
    state.dictationMode = "clarity"; state.dictationModes = ["legacy", "natural", "preserve", "light", "clarity", "action"]
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
  private func replaceKeyboard(_ keyboard: SelectionKeyboard, store: SharedState, window: UIWindow) throws -> SelectionKeyboard {
    let host = try XCTUnwrap(window.rootViewController)
    keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
    keyboard.willMove(toParent: nil); keyboard.view.removeFromSuperview(); keyboard.removeFromParent()
    let replacement = SelectionKeyboard(); replacement.store = SharedState(root: store.root)
    replacement.field.before = keyboard.field.before; replacement.field.after = keyboard.field.after
    replacement.field.documentIdentifier = keyboard.field.documentIdentifier
    host.addChild(replacement); host.view.addSubview(replacement.view); replacement.didMove(toParent: host)
    replacement.view.frame = CGRect(x: 0, y: 574, width: 393, height: 278)
    replacement.beginAppearanceTransition(true, animated: false); replacement.endAppearanceTransition()
    return replacement
  }
  @MainActor
  private func descendants(_ view: UIView) -> [UIView] { view.subviews.flatMap { [$0] + descendants($0) } }
  @MainActor private func outputCapsule(_ keyboard: KeyboardViewController) throws -> UIButton {
    try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.output-preferences" })
  }
  @MainActor private func menuElements(_ menu: UIMenu?) -> [UIMenuElement] {
    (menu?.children ?? []).flatMap { [$0] + (($0 as? UIMenu).map { menuElements($0) } ?? []) }
  }
  @MainActor private func invoke(_ action: UIAction) {
    UIButton(type: .system, primaryAction: action).sendActions(for: .primaryActionTriggered)
  }
  @MainActor
  private func attemptExplicitInsertion(_ keyboard: KeyboardViewController) {
    // Invoke the same private Objective-C action as the Insert button.
    let action = NSSelectorFromString("insertResult")
    XCTAssertTrue(keyboard.responds(to: action))
    _ = keyboard.perform(action)
  }
  @MainActor
  private func beginProcessing(in keyboard: SelectionKeyboard, store: SharedState) throws -> String {
    var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970
    try store.write(state, to: "state.json")
    let beforeRefresh = Date().timeIntervalSince1970
    keyboard.refreshFromStore()
    let afterRefresh = Date().timeIntervalSince1970
    let mic = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
    let beforeActivation = Date().timeIntervalSince1970
    let microphoneEnabled = mic.isEnabled; let microphoneHidden = mic.isHidden
    XCTAssertTrue(mic.accessibilityActivate())
    let commands = store.commands()
    if commands.isEmpty {
      // Keep metadata only. A true accessibility return does not prove that
      // the controller accepted Start or that its command file was readable.
      var report = [
        "heartbeatAgeBeforeRefresh=\(beforeRefresh - state.heartbeat)",
        "heartbeatAgeAfterRefresh=\(afterRefresh - state.heartbeat)",
        "heartbeatAgeBeforeActivation=\(beforeActivation - state.heartbeat)",
        "microphoneEnabled=\(microphoneEnabled), microphoneHidden=\(microphoneHidden)",
        "sessionActive=\(state.sessionActive), configured=\(state.configured), phase=\(state.phase.rawValue)"
      ]
      do {
        _ = try JSONDecoder().decode(DictationSnapshot.self, from: Data(contentsOf: store.root.appendingPathComponent("state.json")))
        let files = try FileManager.default.contentsOfDirectory(at: store.root, includingPropertiesForKeys: nil)
          .filter { $0.lastPathComponent.hasPrefix("command-") && $0.pathExtension == "json" }
        report.append("commandFiles=\(files.count)")
        for file in files.prefix(8) {
          do { _ = try JSONDecoder().decode(DictationCommand.self, from: Data(contentsOf: file)); report.append("commandDecode=ok") }
          catch { report.append("commandDecode=\(String(reflecting: type(of: error)))") }
        }
      } catch { report.append("fixtureRead=\(String(reflecting: type(of: error)))") }
      let attachment = XCTAttachment(string: report.joined(separator: "\n"))
      attachment.name = "dictation-start-fixture"; attachment.lifetime = .keepAlways; add(attachment)
    }
    let start = try XCTUnwrap(commands.last?.1, "Start command missing; see dictation-start-fixture attachment")
    XCTAssertEqual(start.action, "start")
    state.operationID = start.operationID; state.phase = .recording; state.text = nil
    state.heartbeat = Date().timeIntervalSince1970
    try store.write(state, to: "state.json"); keyboard.refreshFromStore()
    let finish = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? UIButton }
      .first { $0.accessibilityIdentifier == "clarify.keyboard.finish" })
    XCTAssertTrue(finish.isEnabled); finish.sendActions(for: .touchUpInside)
    XCTAssertEqual(store.commands().last?.1.action, "finish")
    state.phase = .transcribing; state.heartbeat = Date().timeIntervalSince1970
    try store.write(state, to: "state.json"); keyboard.refreshFromStore()
    return start.operationID
  }
  @MainActor
  private func publish(_ text: String, to keyboard: SelectionKeyboard, store: SharedState) throws {
    // The real containing app refreshes its heartbeat during editing. This
    // isolated fixture has no audio session or background heartbeat producer.
    var live = store.snapshot(); live.heartbeat = Date().timeIntervalSince1970
    try store.write(live, to: "state.json"); keyboard.refreshFromStore()
    let mic = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
    XCTAssertTrue(mic.accessibilityActivate())
    let start = try XCTUnwrap(store.commands().last?.1)
    var recording = store.snapshot(); recording.heartbeat = Date().timeIntervalSince1970
    recording.operationID = start.operationID; recording.phase = .recording
    try store.write(recording, to: "state.json"); keyboard.refreshFromStore()
    let finish = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.keyboard.finish" })
    XCTAssertTrue(finish.isEnabled); finish.sendActions(for: .touchUpInside)
    let command = try XCTUnwrap(store.commands().last?.1)
    XCTAssertEqual(command.action, "finish")
    var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970
    state.operationID = command.operationID; state.phase = .ready; state.text = text
    try store.write(state, to: "state.json")
    keyboard.refreshFromStore()
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
  @MainActor
  func testDictationAndUndoRefreshSentenceCasingWithoutAHostNotification() async throws {
    let (keyboard, store, window) = try makeDictationFixture()
    defer {
      keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
      window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
    }
    keyboard.field.before = "hello"; keyboard.textDidChange(nil)
    let grid = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? KeyGridView }.first)
    XCTAssertEqual(grid.model.shift, .off)
    // Cold simulator setup can outlast the three-second session heartbeat.
    // This fixture has no containing app to refresh it during keyboard setup.
    var live = store.snapshot(); live.heartbeat = Date().timeIntervalSince1970
    try store.write(live, to: "state.json"); keyboard.refreshFromStore()
    XCTAssertTrue(store.snapshot().isLive, "The isolated containing-app heartbeat must be current before recording")
    let mic = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
    XCTAssertTrue(mic.accessibilityActivate())
    let start = try XCTUnwrap(store.commands().last?.1)
    var recording = store.snapshot(); recording.heartbeat = Date().timeIntervalSince1970
    recording.operationID = start.operationID; recording.phase = .recording
    try store.write(recording, to: "state.json"); keyboard.refreshFromStore()
    let finish = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.keyboard.finish" })
    XCTAssertTrue(finish.isEnabled); finish.sendActions(for: .touchUpInside)
    let command = try XCTUnwrap(store.commands().last?.1)
    XCTAssertEqual(command.action, "finish")
    var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970
    state.operationID = command.operationID; state.phase = .ready; state.text = " world. "
    let inserted = expectation(description: "The periodic refresh inserts the ready dictation")
    keyboard.field.didInsert = { [weak field = keyboard.field] text in
      guard text == "hello world. " else { return }
      field?.didInsert = nil
      inserted.fulfill()
    }
    defer { keyboard.field.didInsert = nil }
    try store.write(state, to: "state.json")
    await fulfillment(of: [inserted], timeout: 5)
    XCTAssertEqual(grid.model.shift, .once)
    let undo = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? UIButton }
      .first { $0.accessibilityIdentifier == "clarify.undo-dictation" })
    undo.sendActions(for: .touchUpInside)
    XCTAssertEqual(keyboard.field.before, "hello"); XCTAssertEqual(grid.model.shift, .off)
    undo.sendActions(for: .touchUpInside)
    XCTAssertEqual(keyboard.field.before, "hello world. "); XCTAssertEqual(grid.model.shift, .once)
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
  func testDictionaryMenuSavesOnceOfflineWithoutChangingTheSelection() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: []))
      var state = store.snapshot(); state.sessionActive = false
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      keyboard.field.before = "Untouched "; keyboard.field.selectedText = "João Victor"; keyboard.selectionDidChange(nil)
      let capsule = try self.outputCapsule(keyboard)
      let save = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIAction }.first { $0.title == L("Adicionar ao dicionário") })
      self.invoke(save)
      XCTAssertEqual(store.keyboardAdditions(scope: "guest").map { $0.1.term }, ["João Victor"])
      let saved = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIAction }.first { $0.title == L("Salvo") })
      XCTAssertTrue(saved.attributes.contains(.disabled)); self.invoke(save)
      XCTAssertEqual(store.keyboardAdditions(scope: "guest").count, 1)
      XCTAssertEqual(keyboard.field.before, "Untouched "); XCTAssertEqual(keyboard.field.selectedText, "João Victor")
      for selection in ["three selected words", "", "+ …"] {
        keyboard.field.selectedText = selection; keyboard.selectionDidChange(nil)
        XCTAssertFalse(capsule.isHidden)
        XCTAssertFalse(self.menuElements(capsule.menu).contains { ($0 as? UIAction)?.title == L("Adicionar ao dicionário") })
      }
      keyboard.field.selectedText = "New"; keyboard.field.isSecureTextEntry = true; keyboard.selectionDidChange(nil)
      XCTAssertFalse(capsule.isHidden); XCTAssertNil(capsule.configuration?.image)
      XCTAssertFalse(self.menuElements(capsule.menu).contains { ($0 as? UIAction)?.title == L("Adicionar ao dicionário") })
      keyboard.fullAccess = false; keyboard.selectionDidChange(nil); XCTAssertFalse(capsule.isEnabled)
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
        .first { $0.accessibilityIdentifier == "clarify.output-preferences" && !$0.isHidden }
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
      XCTAssertNil(KBHostArbiterHook.currentHostBundleID(for: keyboard))
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
      host.addChild(keyboard); host.view.addSubview(keyboard.view); keyboard.didMove(toParent: host)
      // A plain parent has no _hostPID. KVC must not crash the extension.
      XCTAssertNil(KBHostArbiterHook.legacyHostBundleID(for: keyboard))
      XCTAssertNil(KBHostArbiterHook.currentHostBundleID(for: keyboard))
      window.isHidden = true
    }
  }
  func testCurrentSourceStateRequiresTheCurrentHostProcess() throws {
    let state = SourceProcessState()
    XCTAssertEqual(KBHostArbiterHook.sourceBundleID(from: state, matchingProcessID: 5127), "com.clarify.fixture.host")
    XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: state, matchingProcessID: 5128), "Reject a previous app's state")
    XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: state, matchingProcessID: 0))
    state.pid = 0
    XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: state, matchingProcessID: 5127))
    state.pid = 5127
    let invalidSources: [Any] = ["", "unknown", NSNumber(value: 5127), try XCTUnwrap(Bundle.main.bundleIdentifier)]
    for source in invalidSources {
      state.source = source
      XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: state, matchingProcessID: 5127))
    }
    state.source = "com.clarify.fixture.host"; state.replacementPID = 5128
    XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: state, matchingProcessID: 5127), "Reject identity changes during the read")
    XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: NSObject(), matchingProcessID: 5127))
    XCTAssertNil(KBHostArbiterHook.sourceBundleID(from: UnexpectedSourceProcessState(), matchingProcessID: 5127), "Do not invoke an unexpected runtime signature")
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
  func testRecordingWaveformFollowsTheDesktopAttackReleaseAndIndependentBars() async {
    await MainActor.run {
      let waveform = RecordingWaveform(frame: CGRect(x: 0, y: 0, width: 144, height: 56))
      waveform.update(level: 1, recording: true, reduceMotion: false)
      waveform.advanceFrame(by: 0.016)
      XCTAssertEqual(waveform.displayedLevel, 0.38, accuracy: 0.0001, "Speech attacks on the desktop's 16 ms clock")
      let first = waveform.subviews.map { $0.frame.height }
      waveform.update(level: 0, recording: true, reduceMotion: false)
      waveform.advanceFrame(by: 0.016)
      XCTAssertEqual(waveform.displayedLevel, 0.3344, accuracy: 0.0001, "Release must be slower than attack")
      for _ in 0..<45 { waveform.advanceFrame(by: 0.016) }
      let resting = waveform.subviews.map { $0.frame.height }
      XCTAssertEqual(resting.count, 12)
      XCTAssertTrue(zip(first, resting).contains { $0.0 > $0.1 + 4 }, "Measured speech must expand the bars")
      XCTAssertTrue(resting.allSatisfy { $0 >= 6.4 && $0 <= 39.2 }, "The desktop envelope stays bounded at silence")
      waveform.advanceFrame(by: 0.08)
      XCTAssertNotEqual(resting, waveform.subviews.map { $0.frame.height }, "Neighbouring bars need independent motion, rather than one static pulse")
      waveform.update(level: AudioLevel.measure([Float](repeating: 0.01, count: 2048)), recording: true, reduceMotion: true)
      XCTAssertEqual(waveform.displayedLevel, 0.16, accuracy: 0.000001, "The same RMS input must have the desktop's gain, including quiet speech")
      waveform.update(level: .nan, recording: true, reduceMotion: true)
      XCTAssertEqual(waveform.displayedLevel, 0)
      XCTAssertTrue(waveform.subviews.allSatisfy { $0.frame.height.isFinite })
    }
  }
  func testWaveformClockStopsForHiddenDetachedProcessingAndReducedMotion() async {
    await MainActor.run {
      let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
      let host = UIViewController(); window.rootViewController = host; window.makeKeyAndVisible()
      defer { window.isHidden = true }
      let waveform = RecordingWaveform(frame: CGRect(x: 0, y: 0, width: 144, height: 56))
      host.view.addSubview(waveform)
      waveform.update(level: 1, recording: true, reduceMotion: false)
      XCTAssertTrue(waveform.isAnimating)
      waveform.isHidden = true; XCTAssertFalse(waveform.isAnimating)
      waveform.isHidden = false; XCTAssertTrue(waveform.isAnimating)
      waveform.update(level: 1, recording: true, reduceMotion: true)
      XCTAssertFalse(waveform.isAnimating, "Reduced motion must not leave a background animation clock")
      NotificationCenter.default.post(name: UIAccessibility.reduceMotionStatusDidChangeNotification, object: nil)
      XCTAssertEqual(waveform.isAnimating, !UIAccessibility.isReduceMotionEnabled, "A runtime accessibility change must reconcile the active clock")
      waveform.update(level: 1, recording: true, reduceMotion: false)
      waveform.removeFromSuperview(); XCTAssertFalse(waveform.isAnimating)
      host.view.addSubview(waveform); XCTAssertTrue(waveform.isAnimating)
      waveform.update(level: 1, recording: false, reduceMotion: false)
      XCTAssertFalse(waveform.isAnimating); XCTAssertEqual(waveform.displayedLevel, 0)
    }
  }
  func testTapRecordingPanelUsesAcknowledgedStateAndMeasuredEnergy() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      var live = store.snapshot(); live.heartbeat = Date().timeIntervalSince1970
      try store.write(live, to: "state.json"); keyboard.refreshFromStore()
      let mic = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
      mic.sendActions(for: .touchDown)
      XCTAssertTrue(store.commands().isEmpty, "Touch down does not start a held gesture")
      mic.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().map { $0.1.action }, ["start"])
      XCTAssertFalse(mic.accessibilityActivate(), "Pending start cannot submit a duplicate clip")
      let views = self.descendants(keyboard.view)
      let panel = try XCTUnwrap(views.first { $0.accessibilityIdentifier == "clarify.keyboard.recording-panel" })
      let label = try XCTUnwrap(views.compactMap { $0 as? UILabel }.first { $0.accessibilityIdentifier == "clarify.keyboard.recording-status" })
      let finish = try XCTUnwrap(views.compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.keyboard.finish" })
      let waveform = try XCTUnwrap(views.compactMap { $0 as? RecordingWaveform }.first)
      XCTAssertFalse(panel.isHidden); XCTAssertEqual(label.text, L("Preparando…")); XCTAssertFalse(finish.isEnabled)
      XCTAssertEqual(waveform.displayedLevel, 0); XCTAssertFalse(waveform.isAnimating)
      let command = try XCTUnwrap(store.commands().last?.1)
      var state = store.snapshot(); state.phase = .recording; state.operationID = command.operationID
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json")
      try store.publishAudioMeter(AudioMeterReading(operationID: command.operationID, measuredAt: Date().timeIntervalSince1970, level: 0))
      keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
      XCTAssertTrue(finish.isEnabled); XCTAssertEqual(label.text, L("Ouvindo…"))
      XCTAssertEqual(keyboard.view.bounds.height, 278)
      XCTAssertTrue(try XCTUnwrap(views.compactMap { $0 as? KeyGridView }.first).isHidden)
      for appearance in [UIUserInterfaceStyle.light, .dark] {
        keyboard.view.overrideUserInterfaceStyle = appearance
        for (name, level) in [("quiet", 0.0), ("voice", AudioLevel.measure([Float](repeating: 0.1, count: 2048)))] {
          state.heartbeat = Date().timeIntervalSince1970
          try store.write(state, to: "state.json")
          try store.publishAudioMeter(AudioMeterReading(operationID: command.operationID, measuredAt: Date().timeIntervalSince1970, level: level))
          keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
          // Advance the actual presentation boundary without a timing-sensitive
          // sleep or a live microphone; the store still supplies measured RMS.
          for _ in 0..<48 { waveform.advanceFrame(by: 0.016) }
          if level == 0 { XCTAssertLessThan(waveform.displayedLevel, 0.01) } else { XCTAssertGreaterThan(waveform.displayedLevel, 0.9) }
          let image = UIGraphicsImageRenderer(bounds: keyboard.view.bounds).image { keyboard.view.layer.render(in: $0.cgContext) }
          let capture = XCTAttachment(image: image)
          capture.name = "recording-\(name)-\(appearance == .dark ? "dark" : "light")"; capture.lifetime = .keepAlways; self.add(capture)
        }
      }
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json")
      try store.publishAudioMeter(AudioMeterReading(operationID: "another", measuredAt: Date().timeIntervalSince1970, level: 1))
      keyboard.refreshFromStore()
      for _ in 0..<48 { waveform.advanceFrame(by: 0.016) }
      XCTAssertLessThan(waveform.displayedLevel, 0.01, "A different operation cannot sustain a speech level")
      try store.publishAudioMeter(AudioMeterReading(operationID: command.operationID, measuredAt: Date().timeIntervalSince1970 - 1, level: 1))
      keyboard.refreshFromStore()
      for _ in 0..<48 { waveform.advanceFrame(by: 0.016) }
      XCTAssertLessThan(waveform.displayedLevel, 0.01, "A stale meter cannot restore a speech level")
      finish.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().map { $0.1.action }, ["start", "finish"])
      XCTAssertFalse(finish.isEnabled); XCTAssertEqual(waveform.displayedLevel, 0); XCTAssertFalse(waveform.isAnimating)
      state.phase = .transcribing; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertFalse(panel.isHidden); XCTAssertEqual(label.text, L("Transcrevendo…"))
      let cancel = try XCTUnwrap(views.compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.keyboard.cancel" })
      cancel.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().last?.1.action, "cancel")
      state.phase = .idle; state.operationID = nil; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertTrue(panel.isHidden); XCTAssertEqual(waveform.displayedLevel, 0); XCTAssertFalse(waveform.isAnimating)
      XCTAssertFalse(try XCTUnwrap(views.compactMap { $0 as? KeyGridView }.first).isHidden)
    }
  }
  func testRecreatedKeyboardCanFinishWithoutPublishingIntoAnotherDocument() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      var state = store.snapshot(); state.phase = .recording; state.operationID = "resumed"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      let finish = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.keyboard.finish" })
      XCTAssertTrue(finish.isEnabled); finish.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().last?.1.operationID, "resumed")
      state.phase = .ready; state.text = "Must not auto-insert"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertNil(store.receipt()); XCTAssertFalse(keyboard.field.before.contains("Must not auto-insert"))
      self.attemptExplicitInsertion(keyboard); self.attemptExplicitInsertion(keyboard); keyboard.refreshFromStore()
      XCTAssertEqual(keyboard.field.before, "Must not auto-insert", "Explicit insertion remains available exactly once")
      XCTAssertEqual(store.receipt(), "resumed")
    }
  }
  func testCancelAfterCompletionBeforePollSuppressesAutomaticAndExplicitInsertion() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      keyboard.field.before = "Keep this"; keyboard.field.after = " and this"
      try store.acknowledge("previous")
      let id = try self.beginProcessing(in: keyboard, store: store)
      let cancel = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.keyboard.cancel" })
      let insert = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.title(for: .normal) == L("Inserir") })
      var state = store.snapshot(); state.phase = .ready; state.text = "Cancelled result"
      state.heartbeat = Date().timeIntervalSince1970
      // Do not poll here: the app completes while the keyboard still shows Cancel.
      try store.write(state, to: "state.json")
      XCTAssertTrue(cancel.isEnabled); cancel.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().last?.1.action, "cancel")
      XCTAssertEqual(store.commands().last?.1.operationID, id)
      XCTAssertEqual(keyboard.field.before, "Keep this")
      XCTAssertEqual(store.receipt(), "previous", "Cancel must not claim an insertion receipt")
      // AudioSession.cancel leaves an already completed result in ready and
      // acknowledges the command by publishing a fresh heartbeat.
      for _ in 0..<3 {
        state.heartbeat = Date().timeIntervalSince1970
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        XCTAssertTrue(insert.isHidden)
        insert.sendActions(for: .touchUpInside); self.attemptExplicitInsertion(keyboard)
        XCTAssertEqual(keyboard.field.before, "Keep this")
        XCTAssertEqual(keyboard.field.after, " and this")
        XCTAssertEqual(store.receipt(), "previous")
      }
      state.phase = .error; state.text = "Cancelled rewrite fallback"
      try store.write(state, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
      XCTAssertTrue(insert.isHidden); XCTAssertEqual(keyboard.field.before, "Keep this")
      XCTAssertEqual(store.receipt(), "previous")
    }
  }
  func testCancelledReadyResultCannotBeInsertedByReplacementKeyboard() async throws {
    try await MainActor.run {
      for delivery in ["cached heartbeat expired", "pending", "acknowledged", "command expired", "session expired"] {
        let (original, store, window) = try self.makeDictationFixture()
        var keyboard = original
        defer {
          keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
          window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
        }
        keyboard.field.before = "Keep this"; keyboard.field.after = " and this"
        try store.acknowledge("previous")
        let id = try self.beginProcessing(in: keyboard, store: store)
        let cancel = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
          .first { $0.accessibilityIdentifier == "clarify.keyboard.cancel" })
        if delivery == "cached heartbeat expired" {
          var expired = store.snapshot(); expired.heartbeat = Date().timeIntervalSince1970 - 4
          try store.write(expired, to: "state.json"); keyboard.refreshFromStore()
          XCTAssertFalse(store.snapshot().isLive, delivery)
        }
        var result = store.snapshot(); result.phase = .ready; result.text = "Cancelled result"
        result.heartbeat = Date().timeIntervalSince1970
        // Publish a fresh result without refreshing the controller's cached snapshot.
        XCTAssertTrue(cancel.isEnabled, delivery)
        try store.write(result, to: "state.json"); cancel.sendActions(for: .touchUpInside)
        XCTAssertTrue(store.commands().contains { $0.1.action == "cancel" && $0.1.operationID == id }, delivery)
        XCTAssertTrue(store.isCancelled(id), "Cancel must persist intent before recreating the keyboard: \(delivery)")
        XCTAssertEqual(store.receipt(), "previous", "Cancel must not claim an insertion receipt")
        keyboard = try self.replaceKeyboard(keyboard, store: store, window: window)
        self.attemptExplicitInsertion(keyboard)
        XCTAssertEqual(keyboard.field.before, "Keep this", delivery)
        XCTAssertEqual(store.receipt(), "previous", "Recreation before app acknowledgement cannot restore Insert")
        if delivery == "acknowledged" {
          var acknowledged = result; acknowledged.phase = .idle; acknowledged.operationID = nil; acknowledged.text = nil
          acknowledged.heartbeat = Date().timeIntervalSince1970
          try store.write(acknowledged, to: "state.json"); keyboard.refreshFromStore()
        }
        if delivery == "session expired" {
          var expired = result; expired.heartbeat -= 4
          try store.write(expired, to: "state.json"); keyboard.refreshFromStore()
        }
        if delivery != "pending" {
          // The app consumes acknowledged commands and discards expired ones.
          for (url, _) in store.commands() { try FileManager.default.removeItem(at: url) }
        }
        for phase in [DictationPhase.ready, .error] {
          result.phase = phase; result.heartbeat = Date().timeIntervalSince1970
          try store.write(result, to: "state.json")
          keyboard = try self.replaceKeyboard(keyboard, store: store, window: window)
          let insert = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
            .first { $0.title(for: .normal) == L("Inserir") })
          XCTAssertTrue(insert.isHidden, delivery)
          insert.sendActions(for: .touchUpInside); self.attemptExplicitInsertion(keyboard); keyboard.refreshFromStore()
          XCTAssertEqual(keyboard.field.before, "Keep this", delivery)
          XCTAssertEqual(keyboard.field.after, " and this", delivery)
          XCTAssertEqual(store.receipt(), "previous", delivery)
        }
        try self.publish("New result", to: keyboard, store: store)
        let next = try XCTUnwrap(store.receipt()); XCTAssertNotEqual(next, id)
        keyboard = try self.replaceKeyboard(keyboard, store: store, window: window)
        self.attemptExplicitInsertion(keyboard); keyboard.refreshFromStore()
        XCTAssertEqual(keyboard.field.before, "Keep thisNew result", "The new operation inserts exactly once")
        result.heartbeat = Date().timeIntervalSince1970
        try store.write(result, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
        XCTAssertEqual(keyboard.field.before, "Keep thisNew result", delivery)
        XCTAssertEqual(store.receipt(), next, "A cancelled operation cannot replace the new receipt")
      }
    }
  }
  func testCancelWithExpiredCachedHeartbeatKeepsItsOwnedOperationTarget() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      keyboard.field.before = "Keep this"; keyboard.field.after = " and this"
      try store.acknowledge("previous")
      let id = try self.beginProcessing(in: keyboard, store: store)
      let cancel = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.keyboard.cancel" })
      var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970 - 4
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertFalse(store.snapshot().isLive)
      let next = UUID().uuidString
      state.operationID = next; state.phase = .ready; state.text = "New result"
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); cancel.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().filter { $0.1.action == "cancel" }.map { $0.1.operationID }, [id])
      XCTAssertTrue(store.isCancelled(id)); XCTAssertFalse(store.isCancelled(next))
      XCTAssertEqual(store.receipt(), "previous")
      self.attemptExplicitInsertion(keyboard); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
      XCTAssertEqual(keyboard.field.before, "Keep thisNew result")
      XCTAssertEqual(keyboard.field.after, " and this")
      XCTAssertEqual(store.receipt(), next, "Cancelling the owned operation must not cancel the newer result")
    }
  }
  func testLateReadyAfterAcknowledgedCancelAllowsAnotherClipExactlyOnce() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      var inserted: [String] = []; keyboard.field.didInsert = { inserted.append($0) }
      defer { keyboard.field.didInsert = nil }
      let id = try self.beginProcessing(in: keyboard, store: store)
      let cancel = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.keyboard.cancel" })
      cancel.sendActions(for: .touchUpInside); cancel.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.commands().filter { $0.1.action == "cancel" }.count, 1)
      var state = store.snapshot(); state.phase = .idle; state.operationID = nil; state.text = nil
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      let mic = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
      XCTAssertTrue(mic.isEnabled)
      state.operationID = id; state.phase = .ready; state.text = "Late cancelled result"
      try store.write(state, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
      XCTAssertTrue(inserted.isEmpty); XCTAssertNil(store.receipt())
      try self.publish("New result", to: keyboard, store: store)
      let next = try XCTUnwrap(store.receipt()); XCTAssertNotEqual(next, id)
      keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard); keyboard.refreshFromStore()
      XCTAssertEqual(inserted, ["New result"]); XCTAssertEqual(keyboard.field.before, "New result")
      // A stale cancelled result must not overwrite the new operation's receipt.
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
      XCTAssertEqual(store.receipt(), next); XCTAssertEqual(inserted, ["New result"])
    }
  }
  func testCancelledResultStaysSuppressedWhenTheSessionExpiresAndReturns() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      _ = try self.beginProcessing(in: keyboard, store: store)
      let cancel = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.accessibilityIdentifier == "clarify.keyboard.cancel" })
      cancel.sendActions(for: .touchUpInside)
      var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970 - 4
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      state.phase = .ready; state.text = "Late result after expiry"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
      XCTAssertEqual(keyboard.field.before, ""); XCTAssertNil(store.receipt())
      let mic = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
      XCTAssertTrue(mic.isEnabled, "Expired command state must not block another operation")
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
          let currentButtons = descendants(grid).compactMap { $0 as? UIButton }
          if page == .letters {
            let q = currentButtons.first { $0.title(for: .normal)?.lowercased() == "q" }!
            let a = currentButtons.first { $0.title(for: .normal)?.lowercased() == "a" }!
            let l = currentButtons.first { $0.title(for: .normal)?.lowercased() == "l" }!
            let z = currentButtons.first { $0.title(for: .normal)?.lowercased() == "z" }!
            XCTAssertEqual(a.bounds.width, q.bounds.width, accuracy: 0.5)
            XCTAssertEqual(z.bounds.width, q.bounds.width, accuracy: 0.5)
            let qRect = q.convert(q.bounds, to: grid), aRect = a.convert(a.bounds, to: grid)
            XCTAssertEqual(aRect.midX, qRect.midX + (q.bounds.width + 6) / 2, accuracy: 0.5)
            // Each row owns its side margins, including points near its top and
            // bottom. A global rectangle search can select the row above here.
            for (x, expected) in [(CGFloat(1), a), (width - 1, l)] {
              for y in [aRect.minY + 1, aRect.midY, aRect.maxY - 1] {
                let point = CGPoint(x: x, y: y)
                XCTAssertTrue(grid.hitTest(point, with: nil) === expected,
                              "Row margin selected another row at \(point), width \(width)")
                inserted = []
                grid.beginPress("row-margin", at: point); grid.endPress("row-margin", at: point)
                XCTAssertEqual(inserted.map { $0.lowercased() }, [expected.title(for: .normal)!.lowercased()])
              }
            }
          }
          for y in stride(from: CGFloat(1), to: grid.bounds.height, by: 12) {
            for x in stride(from: CGFloat(1), to: width, by: 12) {
              let point = CGPoint(x: x, y: y)
              guard let hit = grid.hitTest(point, with: nil) as? UIButton else {
                XCTFail("Dead area at \(point), page \(page), width \(width)"); return
              }
              XCTAssertTrue(hit.point(inside: hit.convert(point, from: grid), with: nil))
              // Exercise the touch owner too. Calling sendActions alone does
              // not prove that a touch in the expanded area inserts anything.
              if let title = hit.title(for: .normal), title.count == 1 {
                inserted = []
                grid.beginPress("gap-sweep", at: point); grid.endPress("gap-sweep", at: point)
                XCTAssertEqual(inserted.map { $0.lowercased() }, [title.lowercased()])
              }
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
      var time: TimeInterval = 10
      let shortcut = TypingAssistant(autocorrectionEnabled: false, now: { time })
      @MainActor func start(_ text: String = "word") {
        shortcut.reset(); field.before = text; field.after = ""; field.selectedText = nil
        field.contextAvailable = true; field.isSecureTextEntry = false; field.keyboardType = .default
        field.didInsert = nil; field.didAdjust = nil; field.deferCaretContext = false
        field.afterContextLimit = nil; field.flushCaretContext(); time += 1
      }
      start("1QQQQeq"); shortcut.insert(" ", into: field); time += 0.1
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "1QQQQeq. ")
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "1QQQQeq.  ")
      start(String(repeating: "word ", count: 20) + "word")
      shortcut.insert(" ", into: field); shortcut.insert(" ", into: field)
      XCTAssertTrue(field.before.hasSuffix("word. "), "Bounded proxy context must support the shortcut")
      for text in ["", "word.", "word!", "word ", "\n"] {
        start(text); shortcut.insert(" ", into: field); shortcut.insert(" ", into: field)
        XCTAssertEqual(field.before, text + "  ")
      }
      start(); shortcut.insert(" ", into: field); time += 1
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "word  ")
      start(); shortcut.insert(" ", into: field); field.documentIdentifier = UUID()
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "word  ")
      start(); shortcut.insert(" ", into: field); field.after = "changed"
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "word  ")
      start(); shortcut.insert(" ", into: field); field.selectedText = "selection"
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "word  ")
      start(); shortcut.insert(" ", into: field); shortcut.reset()
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "word  ")
      start(); shortcut.insert(" ", into: field); shortcut.delete(in: field); field.before = "word "
      shortcut.insert(" ", into: field); XCTAssertEqual(field.before, "word  ")
      for type in [UIKeyboardType.emailAddress, .URL, .numberPad] {
        start(); field.keyboardType = type
        shortcut.insert(" ", into: field); shortcut.insert(" ", into: field)
        XCTAssertEqual(field.before, "word  ")
      }
      start(); field.isSecureTextEntry = true
      shortcut.insert(" ", into: field); shortcut.insert(" ", into: field)
      XCTAssertEqual(field.before, "word  ")
      start(); field.contextAvailable = false
      shortcut.insert(" ", into: field); shortcut.insert(" ", into: field)
      XCTAssertEqual(field.before, "word  ")
      start(); field.didInsert = { value in
        if value == "word " { shortcut.insert("q", into: field) }
      }
      shortcut.insert(" ", into: field); field.didInsert = nil; field.before = "word "
      shortcut.insert(" ", into: field)
      XCTAssertEqual(field.before, "word  ", "Reentrant input must invalidate the earlier Space")
      start(); shortcut.insert(" ", into: field); shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); XCTAssertEqual(field.before, "word"); XCTAssertEqual(field.after, " ")
      XCTAssertTrue(shortcut.moveCursor(1, in: field)); shortcut.endCursor()
      shortcut.insert(" ", into: field)
      XCTAssertEqual(field.before, "word  ", "Moving away and back must invalidate the pending double-Space shortcut")
      for change in 0..<6 {
        start(); shortcut.prepareCursor(in: field)
        switch change {
        case 0: field.documentIdentifier = UUID()
        case 1: field.selectedText = "selected"
        case 2: field.isSecureTextEntry = true
        case 3: field.contextAvailable = false
        case 4: field.after = "external edit"
        default: shortcut.reset()
        }
        XCTAssertFalse(shortcut.moveCursor(-1, in: field))
        XCTAssertEqual(field.before, "word", "Changed or unavailable documents must not move")
      }
      start(); field.didAdjust = { shortcut.endCursor() }; shortcut.prepareCursor(in: field)
      XCTAssertFalse(shortcut.moveCursor(-1, in: field)); field.didAdjust = nil
      XCTAssertFalse(shortcut.moveCursor(1, in: field), "A cancelled movement callback must not rearm the cursor session")
      for text in ["abcdef", String(repeating: "abcdefghij", count: 12)] {
        start(text); field.deferCaretContext = true; shortcut.prepareCursor(in: field)
        XCTAssertTrue(shortcut.moveCursor(-1, in: field))
        field.flushCaretContext()
        XCTAssertTrue(shortcut.moveCursor(-1, in: field), "A later proxy update must recognize the first owned movement")
        XCTAssertTrue(shortcut.moveCursor(-1, in: field), "Further movement must work while context is delayed")
        XCTAssertEqual(field.before, String(text.dropLast(3))); XCTAssertEqual(field.after, String(text.suffix(3)))
        field.flushCaretContext()
        XCTAssertTrue(shortcut.moveCursor(2, in: field))
        field.flushCaretContext(); shortcut.endCursor()
        XCTAssertEqual(field.before, String(text.dropLast())); XCTAssertEqual(field.after, String(text.suffix(1)))
      }
      start("abcdef"); field.deferCaretContext = true; shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); XCTAssertTrue(shortcut.moveCursor(1, in: field))
      field.retainedCaretContext = ("abcde", "f")
      XCTAssertTrue(shortcut.moveCursor(-1, in: field), "An intermediate proxy update after a round trip must remain owned")
      field.flushCaretContext()
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); XCTAssertEqual(field.before, "abcd"); XCTAssertEqual(field.after, "ef")
      start("a👩🏼‍🏫e\u{301}"); shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); XCTAssertEqual(field.before, "a👩🏼‍🏫")
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); XCTAssertEqual(field.before, "a")
      XCTAssertTrue(shortcut.moveCursor(2, in: field)); XCTAssertEqual(field.before, "a👩🏼‍🏫e\u{301}")
      start("abcdef"); field.deferCaretContext = true; shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); field.flushCaretContext(); field.after = "external edit"
      XCTAssertFalse(shortcut.moveCursor(-1, in: field)); XCTAssertEqual(field.before, "abcde")
      for editBefore in [true, false] {
        start("abcdef"); field.after = "ghi"; shortcut.prepareCursor(in: field)
        if editBefore { field.before = "Xabcdef" } else { field.after = "ghij" }
        XCTAssertFalse(shortcut.moveCursor(-1, in: field), "A baseline must reject prefix- or suffix-preserving external edits")
        XCTAssertEqual(field.before, editBefore ? "Xabcdef" : "abcdef")
      }
      start("abcdef"); field.deferCaretContext = true; shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); field.flushCaretContext(); field.after = "foo"
      XCTAssertFalse(shortcut.moveCursor(-1, in: field), "A left move must not permit an external extension on the right")
      XCTAssertEqual(field.before, "abcde")
      start("1QQQQeq. Q"); shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(-1, in: field)); XCTAssertTrue(shortcut.moveCursor(-1, in: field))
      field.afterContextLimit = 1
      XCTAssertTrue(shortcut.moveCursor(-2, in: field), "A confirmed left move must tolerate a shorter following window")
      XCTAssertTrue(shortcut.moveCursor(-2, in: field)); XCTAssertEqual(field.before, "1QQQ")
      start("1QQQQeq.X"); field.after = " Q"; field.afterContextLimit = 1
      shortcut.prepareCursor(in: field)
      field.didAdjust = { field.retainedCaretContext = (field.before, "") }
      XCTAssertTrue(shortcut.moveCursor(1, in: field)); XCTAssertEqual(field.before, "1QQQQeq.X ")
      field.didAdjust = nil; field.flushCaretContext()
      XCTAssertTrue(shortcut.moveCursor(1, in: field), "A confirmed right move must accept newly exposed following text")
      XCTAssertEqual(field.before, "1QQQQeq.X Q"); XCTAssertEqual(field.after, "")
      for change in 0..<6 {
        start("abcdef"); field.after = "ghi"; shortcut.prepareCursor(in: field)
        XCTAssertTrue(shortcut.moveCursor(1, in: field))
        switch change {
        case 0: field.documentIdentifier = UUID()
        case 1: field.selectedText = "selected"
        case 2: field.isSecureTextEntry = true
        case 3: field.contextAvailable = false
        case 4: field.after = "unrelated"
        default: field.before = "external"
        }
        XCTAssertFalse(shortcut.moveCursor(1, in: field), "A window refresh must retain the other cursor guards")
      }
      start("abcdef"); field.after = "g"; shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(1, in: field)); field.after = String(repeating: "h", count: 65)
      field.afterContextLimit = 65
      XCTAssertFalse(shortcut.moveCursor(1, in: field), "A newly exposed tail must stay within the refresh bound")
      start("abcdef"); field.after = "g"; shortcut.prepareCursor(in: field)
      XCTAssertTrue(shortcut.moveCursor(1, in: field)); shortcut.endCursor(); field.after = "h"
      XCTAssertFalse(shortcut.moveCursor(1, in: field), "Refresh permission must end with the cursor gesture")
    }
  }
  func testInsertionRejectsAResultClearedByAnotherDestinationBeforeTheNextPoll() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      let id = try self.beginProcessing(in: keyboard, store: store)
      var state = store.snapshot(); state.phase = .error; state.text = "Former result"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertNotEqual(store.receipt(), id)
      state.processingContext = "other-destination"; state.operationID = nil; state.text = nil; state.phase = .idle
      try store.write(state, to: "state.json")
      self.attemptExplicitInsertion(keyboard)
      XCTAssertFalse(keyboard.field.before.contains("Former result")); XCTAssertNotEqual(store.receipt(), id)
    }
  }
  func testSelectedTextInBothDestinationsReusesCommandsAndRejectsChangedDocument() async throws {
    try await MainActor.run {
      for computerMode in [false, true] {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      let context = computerMode ? "computer-fixture" : "account-fixture"
      var state = store.snapshot(); state.computerMode = computerMode; state.processingContext = context
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      keyboard.field.selectedText = "Selected text with several words"
      keyboard.selectionDidChange(nil)
      let button = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.output-preferences" })
      XCTAssertFalse(button.isHidden); XCTAssertTrue(button.showsMenuAsPrimaryAction); XCTAssertNotNil(button.menu)
      keyboard.processSelection("translate", language: "es")
      let command = try XCTUnwrap(store.commands().last?.1)
      XCTAssertEqual(command.action, "translate"); XCTAssertEqual(command.language, "es")
        XCTAssertEqual(command.outputPreferences?.language, .es)
        XCTAssertEqual(store.outputPreferences().language, .es)
      XCTAssertEqual(command.text, "Selected text with several words"); XCTAssertEqual(command.context, context)
      state.operationID = command.operationID; state.textOperation = true; state.phase = .rewriting
      state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      keyboard.field.documentIdentifier = UUID(); keyboard.selectionDidChange(nil)
      XCTAssertTrue(store.isCancelled(command.operationID))
      state.phase = .ready; state.text = "Old translation"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
      XCTAssertFalse(keyboard.field.before.contains("Old translation"))
      }
    }
  }
  func testPermanentCapsuleCapturesAtCompactWidthsBothThemesAndExpandedText() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      _ = try store.setOutputPreference("language", value: "ru")
      _ = try store.setOutputPreference("style", value: "very_casual")
      let capsule = try self.outputCapsule(keyboard)
      for expanded in [false, true] {
        window.rootViewController!.setOverrideTraitCollection(UITraitCollection(preferredContentSizeCategory: expanded ? .accessibilityExtraExtraExtraLarge : .large), forChild: keyboard)
        for appearance in [UIUserInterfaceStyle.light, .dark] {
          keyboard.overrideUserInterfaceStyle = appearance
          for width in [CGFloat(320), 375, 430] {
            var plainWidth: CGFloat = 0
            for selected in [false, true] {
              keyboard.field.selectedText = selected ? "Clarify" : nil; keyboard.selectionDidChange(nil)
              keyboard.view.frame.size.width = width; keyboard.view.layoutIfNeeded(); capsule.layoutIfNeeded()
              XCTAssertFalse(capsule.isHidden); XCTAssertTrue(capsule.showsMenuAsPrimaryAction)
              XCTAssertEqual(capsule.configuration?.title, "🇷🇺 " + OutputStyle.very_casual.title)
              XCTAssertEqual(capsule.configuration?.image != nil, selected)
              if !selected { plainWidth = capsule.bounds.width }
              else if capsule.intrinsicContentSize.width < width - 80 {
                XCTAssertGreaterThan(capsule.bounds.width, plainWidth)
                XCTAssertEqual(capsule.bounds.width, capsule.intrinsicContentSize.width, accuracy: 1,
                  "A long label and wand must fit when toolbar space is available")
              }
              XCTAssertEqual(capsule.accessibilityLabel, L("Saída do ditado") + ": Русский, " + OutputStyle.very_casual.title)
              XCTAssertTrue(keyboard.view.bounds.contains(capsule.frame)); XCTAssertGreaterThanOrEqual(capsule.bounds.height, 44)
              XCTAssertEqual(keyboard.view.bounds.height, 278); XCTAssertFalse(capsule.hasAmbiguousLayout)
              let title = try XCTUnwrap(capsule.titleLabel)
              let titleRect = title.textRect(forBounds: CGRect(x: 0, y: 0, width: title.bounds.width,
                height: .greatestFiniteMagnitude), limitedToNumberOfLines: 0)
              XCTAssertLessThanOrEqual(ceil(titleRect.height), ceil(title.font.lineHeight) + 1,
                "The output style must stay on one line after width, selection and text-size changes")
              let capture = XCTAttachment(image: UIGraphicsImageRenderer(bounds: keyboard.view.bounds).image { keyboard.view.layer.render(in: $0.cgContext) })
              capture.name = "output-capsule-\(Int(width))-\(appearance == .dark ? "dark" : "light")-\(selected ? "selection" : "no-selection")-\(expanded ? "expanded" : "normal")"
              capture.lifetime = .keepAlways; self.add(capture)
            }
          }
        }
      }
      var state = store.snapshot(); state.phase = .recording; state.operationID = UUID().uuidString
      try store.write(state, to: "state.json"); keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
      XCTAssertFalse(capsule.isHidden); XCTAssertTrue(keyboard.view.bounds.contains(capsule.frame))
      XCTAssertFalse(self.menuElements(capsule.menu).compactMap { $0 as? UIAction }.filter { $0.title == L("Reescrever") }.contains { !$0.attributes.contains(.disabled) })
    }
  }
  func testTranslationMenuSurvivesRefreshAndStillCancelsWhenSelectionChanges() async throws {
    try await MainActor.run {
      for computerMode in [false, true] {
        let (keyboard, store, window) = try self.makeDictationFixture()
        defer {
          keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
          window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
        }
        var state = store.snapshot(); state.computerMode = computerMode
        // Window setup does not run the containing app's heartbeat producer.
        state.heartbeat = Date().timeIntervalSince1970
        state.processingContext = computerMode ? "computer-fixture" : "account-fixture"
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        keyboard.field.before = "Prefix "; keyboard.field.selectedText = "Original selection"
        keyboard.selectionDidChange(nil)
        let button = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.output-preferences" })
        let menu = try XCTUnwrap(button.menu)
        let translate = try XCTUnwrap(self.menuElements(menu).compactMap { $0 as? UIMenu }.first { $0.title == L("Traduzir") })
        let spanish = try XCTUnwrap(translate.children.compactMap { $0 as? UIAction }.first { $0.title == "🇪🇸 Español" })
        XCTAssertFalse(spanish.attributes.contains(.disabled)); XCTAssertTrue(button.isEnabled)
        for _ in 0..<20 {
          state.heartbeat = Date().timeIntervalSince1970; state.libraryRevision += 1
          try store.write(state, to: "state.json"); keyboard.refreshFromStore()
          keyboard.selectionDidChange(nil); keyboard.textDidChange(nil)
          XCTAssertTrue(button.menu === menu, "Polling must preserve the menu that owns the open language submenu")
          XCTAssertTrue(self.menuElements(button.menu).contains { $0 === translate })
          XCTAssertEqual(keyboard.field.selectedText, "Original selection"); XCTAssertTrue(store.commands().isEmpty)
        }
        // Invoke the retained language action through UIKit's public control event.
        let choice = UIButton(type: .system, primaryAction: spanish)
        choice.sendActions(for: .primaryActionTriggered)
        let command = try XCTUnwrap(store.commands().last?.1)
        XCTAssertEqual(command.action, "translate"); XCTAssertEqual(command.language, "es")
        XCTAssertEqual(command.outputPreferences?.language, .es)
        XCTAssertEqual(store.outputPreferences().language, .es)
        XCTAssertEqual(command.text, "Original selection"); XCTAssertEqual(command.context, state.processingContext)
        state.operationID = command.operationID; state.textOperation = true; state.phase = .rewriting
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        keyboard.field.selectedText = "Changed selection"; keyboard.selectionDidChange(nil)
        XCTAssertTrue(store.isCancelled(command.operationID))
        state.phase = .ready; state.text = "Stale translation"; state.heartbeat = Date().timeIntervalSince1970
        try store.write(state, to: "state.json"); keyboard.refreshFromStore(); self.attemptExplicitInsertion(keyboard)
        XCTAssertEqual(keyboard.field.before, "Prefix "); XCTAssertEqual(keyboard.field.selectedText, "Changed selection")
        XCTAssertNotEqual(store.receipt(), command.operationID)
      }
    }
  }
  func testCapsuleSeparatesPreferencesFromSelectionAndNeverFallsBackForEmptyOrUnavailableCatalog() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      let capsule = try self.outputCapsule(keyboard)
      keyboard.field.selectedText = nil; keyboard.selectionDidChange(nil)
      XCTAssertFalse(capsule.isHidden); XCTAssertNil(capsule.configuration?.image)
      XCTAssertEqual(capsule.configuration?.title, "🌐 " + OutputStyle.default.title)
      XCTAssertFalse(self.menuElements(capsule.menu).contains { ($0 as? UIMenu)?.title == L("Texto selecionado") })
      let outputLanguage = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIMenu }.first { $0.title == L("Idioma de saída") })
      XCTAssertEqual(outputLanguage.children.compactMap { ($0 as? UIAction)?.title }, OutputLanguage.allCases.map(\.menuTitle))
      let german = try XCTUnwrap(outputLanguage.children.compactMap { $0 as? UIAction }.first { $0.title == "🇩🇪 Deutsch" })
      self.invoke(german); XCTAssertEqual(store.outputPreferences().language, .de)
      keyboard.field.selectedText = "Original"; keyboard.selectionDidChange(nil)
      let translation = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIMenu }.first { $0.title == L("Traduzir") })
      XCTAssertEqual(translation.children.compactMap { ($0 as? UIAction)?.title }, OutputLanguage.allCases.map(\.menuTitle))
      let spanish = try XCTUnwrap(translation.children.compactMap { $0 as? UIAction }.first { $0.title == "🇪🇸 Español" })
      keyboard.field.selectedText = "Changed before poll"
      self.invoke(spanish); XCTAssertTrue(store.commands().isEmpty, "A retained closure cannot adopt a changed selection")
      keyboard.selectionDidChange(nil)
      for catalog in [TextActionCatalog(status: .ready, actions: []), .unavailable, .loading] {
        var state = store.snapshot(); state.textActions = catalog
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        XCTAssertFalse(self.menuElements(capsule.menu).contains { ($0 as? UIAction)?.title == L("Reescrever") })
        XCTAssertFalse(self.menuElements(capsule.menu).contains { ($0 as? UIMenu)?.title == L("Traduzir") })
      }
      let custom = TextActionDescriptor(id: "summary", revision: "9223372036854775807", name: "Summary", kind: "custom", enabled: true, ready: true)
      var state = store.snapshot(); state.textActions = TextActionCatalog(status: .ready, actions: [custom])
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      let selectedText = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIMenu }.first { $0.title == L("Texto selecionado") })
      let action = try XCTUnwrap(selectedText.children.compactMap { $0 as? UIAction }.first { $0.title == "Summary" })
      let menu = capsule.menu; keyboard.refreshFromStore(); XCTAssertTrue(capsule.menu === menu)
      self.invoke(action)
      let command = try XCTUnwrap(store.commands().last?.1)
      XCTAssertEqual(command.action, "text_action"); XCTAssertEqual(command.actionID, custom.id); XCTAssertEqual(command.actionRevision, custom.revision)
      XCTAssertEqual(command.outputPreferences?.language, .de)
      XCTAssertEqual(command.language, "de"); XCTAssertEqual(store.outputPreferences().language, .de)
      // Complete this operation before testing another settings change.
      state.operationID = command.operationID; state.textOperation = true; state.phase = .ready
      state.text = "Summary result"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertEqual(store.receipt(), command.operationID)
      let commandCount = store.commands().count
      for (mode, title) in [("legacy", "Usar configuração do destino"), ("natural", "Usar instruções de ditado"), ("light", "Ajustar apenas espaços")] {
        state.dictationMode = mode
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        let compatibility = self.menuElements(capsule.menu).compactMap { $0 as? UIAction }.filter { $0.title == L(title) }
        XCTAssertEqual(compatibility.count, 1)
        XCTAssertTrue(try XCTUnwrap(compatibility.first).attributes.contains(.disabled))
        XCTAssertEqual(compatibility.first?.state, .on)
        let more = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIMenu }.first { $0.title == L("Mais opções") })
        XCTAssertFalse(self.menuElements(more).contains { ($0 as? UIAction)?.title == L(title) })
        XCTAssertEqual(store.commands().count, commandCount)
      }
      for style in [OutputStyle.very_casual, .informal, .organized] {
        _ = try store.setOutputPreference("style", value: style.rawValue); keyboard.refreshFromStore()
        let oldTone = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIAction }.first { $0.title == style.title })
        XCTAssertEqual(oldTone.state, .on); XCTAssertTrue(oldTone.attributes.contains(.disabled))
        XCTAssertEqual(store.outputPreferences().style, style)
      }
      state.dictationMode = "action"; state.dictationActionID = custom.id
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      let turnOff = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIAction }.first { $0.title == L("Não aplicar ação automaticamente") })
      XCTAssertFalse(turnOff.attributes.contains(.disabled)); self.invoke(turnOff)
      let policyCommand = try XCTUnwrap(store.commands().last?.1)
      XCTAssertEqual(policyCommand.action, "dictation_policy"); XCTAssertEqual(policyCommand.text, "clarity")
      XCTAssertEqual(store.outputPreferences().style, .organized)
    }
  }
  func testAccountSelectedTextMenuPreservesDictionaryAndRejectsSecureOrOversizedSelections() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      try store.publishKeyboardDictionary(KeyboardDictionaryContext(scope: "guest", words: []))
      keyboard.field.selectedText = "Clarify"; keyboard.selectionDidChange(nil)
      let button = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }.first { $0.accessibilityIdentifier == "clarify.output-preferences" })
      XCTAssertFalse(button.isHidden); XCTAssertTrue(button.showsMenuAsPrimaryAction)
      keyboard.view.layoutIfNeeded(); button.layoutIfNeeded()
      XCTAssertEqual(button.configuration?.title, "🌐 " + OutputStyle.default.title)
      let menu = try XCTUnwrap(button.menu)
      XCTAssertTrue(self.menuElements(menu).contains { ($0 as? UIAction)?.title == L("Reescrever") })
      XCTAssertTrue(self.menuElements(menu).contains { ($0 as? UIMenu)?.title == L("Traduzir") })
      XCTAssertTrue(self.menuElements(menu).contains { ($0 as? UIAction)?.title == L("Adicionar ao dicionário") })
      button.sendActions(for: .touchUpInside)
      XCTAssertTrue(store.keyboardAdditions(scope: "guest").isEmpty, "Opening the menu must not save a word")
      keyboard.saveSelectedTerm()
      XCTAssertEqual(store.keyboardAdditions(scope: "guest").map { $0.1.term }, ["Clarify"])
      let saved = try XCTUnwrap(self.menuElements(button.menu).compactMap { $0 as? UIAction }.first { $0.title == L("Salvo") })
      XCTAssertTrue(saved.attributes.contains(.disabled))
      XCTAssertFalse(button.menu === menu, "Saving must update the dictionary entry in the selected-text menu")
      let savedMenu = button.menu
      keyboard.refreshFromStore(); XCTAssertTrue(button.menu === savedMenu)
      var renewed = store.snapshot(); renewed.processingContext = "renewed-account-session"
      try store.write(renewed, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertFalse(button.menu === savedMenu, "A new destination or session must invalidate the old menu")
      XCTAssertEqual(keyboard.field.selectedText, "Clarify"); XCTAssertTrue(store.commands().isEmpty)
      for width in [CGFloat(320), 393, 852] {
        keyboard.view.frame.size.width = width; keyboard.view.layoutIfNeeded()
        XCTAssertTrue(keyboard.view.bounds.contains(button.frame)); XCTAssertEqual(keyboard.view.bounds.height, 278)
      }
      keyboard.field.isSecureTextEntry = true; keyboard.selectionDidChange(nil)
      XCTAssertFalse(button.isHidden); XCTAssertNil(button.configuration?.image)
      keyboard.processSelection("translate", language: "en"); XCTAssertTrue(store.commands().isEmpty)
      keyboard.field.isSecureTextEntry = false; keyboard.field.selectedText = String(repeating: "é", count: 8001)
      keyboard.selectionDidChange(nil); XCTAssertFalse(button.isHidden); XCTAssertNil(button.configuration?.image)
      keyboard.processSelection("rewrite", language: "pt"); XCTAssertTrue(store.commands().isEmpty)
      keyboard.field.selectedText = "Text"; keyboard.fullAccess = false; keyboard.selectionDidChange(nil)
      XCTAssertFalse(button.isEnabled)
      keyboard.processSelection("translate", language: "en"); XCTAssertTrue(store.commands().isEmpty)
    }
  }
  func testCommandKeepsTheKeyboardContextWhenTheAppChangesDestinationBeforeSend() async throws {
    try await MainActor.run {
      for action in ["start", "rewrite"] {
        let (keyboard, store, window) = try self.makeDictationFixture()
        defer {
          keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
          window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
        }
        var state = store.snapshot(); state.computerMode = true; state.processingContext = "computer-A"
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        keyboard.field.selectedText = "Text authorized for computer A"
        // The containing app publishes B before the extension's next timer poll.
        state.processingContext = "computer-B"
        try store.write(state, to: "state.json")
        if action == "rewrite" { keyboard.processSelection(action, language: "pt") }
        else {
          let mic = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
          XCTAssertTrue(mic.accessibilityActivate())
        }
        let command = try XCTUnwrap(store.commands().last?.1)
        XCTAssertEqual(command.action, action)
        XCTAssertEqual(command.text, action == "rewrite" ? "Text authorized for computer A" : nil)
        XCTAssertEqual(command.context, "computer-A", "Delivery must retain the destination that authorized the action")
        XCTAssertNotEqual(command.context, store.snapshot().processingContext, "The app must see this command as stale")
      }
    }
  }
  func testRecoveredSelectionResultHidesInsertAfterSelectionOrDocumentChanges() async throws {
    try await MainActor.run {
      for changeDocument in [false, true] {
        let (keyboard, store, window) = try self.makeDictationFixture()
        defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
        keyboard.field.selectedText = "Original"
        keyboard.processSelection("rewrite", language: "pt")
        let command = try XCTUnwrap(store.commands().last?.1)
        var state = store.snapshot(); state.operationID = command.operationID
        state.textOperation = true; state.phase = .error; state.text = "Original"
        state.message = L(OutputPreferences.unappliedMessage); state.heartbeat = Date().timeIntervalSince1970
        try store.write(state, to: "state.json"); keyboard.refreshFromStore()
        let insert = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
          .first { $0.title(for: .normal) == L("Inserir") })
        XCTAssertFalse(insert.isHidden)
        if changeDocument { keyboard.field.documentIdentifier = UUID() }
        else { keyboard.field.selectedText = "Changed" }
        keyboard.selectionDidChange(nil); keyboard.refreshFromStore()
        XCTAssertTrue(insert.isHidden)
        self.attemptExplicitInsertion(keyboard)
        XCTAssertEqual(keyboard.field.before, "")
        XCTAssertNotEqual(store.receipt(), command.operationID)
      }
    }
  }
  func testOutputPreferenceWriteFailureIsVisibleAndClearsAfterSuccessfulSave() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      keyboard.field.selectedText = nil; keyboard.selectionDidChange(nil)
      let capsule = try self.outputCapsule(keyboard)
      let language = try XCTUnwrap(self.menuElements(capsule.menu).compactMap { $0 as? UIMenu }.first { $0.title == L("Idioma de saída") })
      let german = try XCTUnwrap(language.children.compactMap { $0 as? UIAction }.first { $0.title == "🇩🇪 Deutsch" })
      let blocked = store.root.appendingPathComponent("output-preferences.json")
      try FileManager.default.createDirectory(at: blocked, withIntermediateDirectories: false)
      self.invoke(german)
      let status = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UILabel }
        .first { $0.accessibilityIdentifier == "clarify.keyboard.recording-status" })
      let panel = try XCTUnwrap(status.superview)
      XCTAssertFalse(panel.isHidden)
      XCTAssertEqual(status.text, L("Não foi possível salvar a preferência de saída. Tente novamente."))
      XCTAssertEqual(store.outputPreferences().language, .auto)
      try FileManager.default.removeItem(at: blocked)
      self.invoke(german)
      XCTAssertEqual(store.outputPreferences().language, .de)
      XCTAssertTrue(panel.isHidden)
      XCTAssertNotEqual(capsule.accessibilityHint, L("Não foi possível salvar a preferência de saída. Tente novamente."))
    }
  }
  func testSelectedTextResultInBothDestinationsInsertsOnlyIntoOriginalSelection() async throws {
    try await MainActor.run {
      for computerMode in [false, true] {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer { window.isHidden = true; try? FileManager.default.removeItem(at: store.root) }
      var state = store.snapshot(); state.computerMode = computerMode; state.processingContext = computerMode ? "computer-fixture" : "account-fixture"
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      keyboard.field.selectedText = "Original"
      keyboard.processSelection("rewrite", language: "pt")
      let command = try XCTUnwrap(store.commands().last?.1)
      state.operationID = command.operationID; state.textOperation = true; state.phase = .ready
      state.text = "Revised"; state.heartbeat = Date().timeIntervalSince1970
      try store.write(state, to: "state.json"); keyboard.refreshFromStore()
      XCTAssertEqual(keyboard.field.before, "Revised"); XCTAssertEqual(store.receipt(), command.operationID)
      self.attemptExplicitInsertion(keyboard); XCTAssertEqual(keyboard.field.before, "Revised")
      }
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
        guard let button = descendants(grid).compactMap({ $0 as? UIButton }).first(where: { $0.title(for: .normal)?.lowercased() == "a" }) else {
          XCTFail("Missing A key"); return
        }
        button.isHighlighted = true
        let preview = descendants(keyboard.view).compactMap { $0 as? KeyPreview }.first
        XCTAssertNotNil(preview)
        if let preview = preview {
          XCTAssertTrue(keyboard.view.bounds.contains(preview.frame))
          // The grid includes a top inset; compare with an actual first-row
          // key rather than treating the container's edge as the key row.
          let firstRowKey = descendants(grid).compactMap { $0 as? UIButton }
            .first { $0.title(for: .normal)?.lowercased() == "q" }
          XCTAssertNotNil(firstRowKey)
          if let firstRowKey = firstRowKey {
            XCTAssertLessThan(preview.frame.minY, firstRowKey.convert(firstRowKey.bounds, to: keyboard.view).minY)
          }
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

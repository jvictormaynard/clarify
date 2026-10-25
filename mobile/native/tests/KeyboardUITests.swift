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
  var didInsert: ((String) -> Void)?
  func insertText(_ text: String) {
    before += text; selectedText = nil; didInsert?(before)
  }
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
  func testErrorCauseFitsTheExistingToolbarWithoutChangingKeyboardHeight() async throws {
    try await MainActor.run {
      let (keyboard, store, window) = try self.makeDictationFixture()
      defer {
        keyboard.beginAppearanceTransition(false, animated: false); keyboard.endAppearanceTransition()
        window.isHidden = true; try? FileManager.default.removeItem(at: store.root)
      }
      let detail = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UILabel }.first { $0.accessibilityIdentifier == "clarify.keyboard.detail" })
      let status = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UILabel }.first { $0.accessibilityIdentifier == "clarify.keyboard.status" })
      let messages = ["Nenhuma fala foi reconhecida. Tente falar novamente.", "Não foi possível transcrever o áudio. Tente novamente.",
        "O processamento do Clarify está indisponível no momento.", "Esta solicitação não pode ser repetida. Inicie uma nova ação.",
        "A reescrita falhou. Você pode inserir a transcrição original."]
      for language in ["pt", "en", "es"] {
        for message in messages {
          for width in [CGFloat(320), 393, 852] {
            var state = store.snapshot(); state.heartbeat = Date().timeIntervalSince1970
            state.phase = .error; state.operationID = UUID().uuidString; state.message = L(message, language: language)
            state.text = message.hasPrefix("A reescrita") ? "Preserved original" : nil
            try store.write(state, to: "state.json"); keyboard.refreshFromStore()
            keyboard.view.frame.size.width = width; keyboard.view.layoutIfNeeded()
            XCTAssertFalse(detail.isHidden); XCTAssertTrue(status.isHidden)
            XCTAssertFalse(detail.hasAmbiguousLayout, "Wide errors and errors beside Insert need one stable layout")
            XCTAssertEqual(detail.text, state.message); XCTAssertEqual(detail.lineBreakMode, .byWordWrapping)
            let required = (detail.text! as NSString).boundingRect(with: CGSize(width: detail.bounds.width, height: .greatestFiniteMagnitude),
              options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: [.font: detail.font!], context: nil).height
            XCTAssertLessThanOrEqual(ceil(required), 44, "The complete cause must fit in the fixed toolbar: \(language), \(width)")
            XCTAssertGreaterThanOrEqual(detail.frame.minY, 6); XCTAssertLessThanOrEqual(detail.frame.maxY, 52)
            XCTAssertEqual(keyboard.view.bounds.height, KeyboardInputView.contentHeight)
            XCTAssertEqual(keyboard.preferredContentSize.height, KeyboardInputView.contentHeight)
          }
        }
      }
      var ready = store.snapshot(); ready.phase = .idle; ready.message = nil
      try store.write(ready, to: "state.json"); keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
      XCTAssertEqual(detail.numberOfLines, 1, "Restore the ordinary toolbar after the failure is cleared")
      XCTAssertFalse(detail.hasAmbiguousLayout, "Error-to-idle must restore a single vertical position")
      var expired = store.snapshot(); expired.phase = .error; expired.configured = false; expired.message = L("Entre na conta novamente.")
      try store.write(expired, to: "state.json"); keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
      XCTAssertFalse(detail.isHidden); XCTAssertEqual(detail.text, expired.message, "An expired account must not suggest switching to a personal key")
      expired.phase = .idle; expired.message = nil
      try store.write(expired, to: "state.json"); keyboard.refreshFromStore(); keyboard.view.layoutIfNeeded()
      XCTAssertEqual(status.text, L("Entre no Clarify"), "An unconfigured keyboard must lead to account sign-in")
    }
  }
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
        .first { $0.accessibilityIdentifier == "clarify.add-to-dictionary" })
      XCTAssertTrue(save.isEnabled); save.sendActions(for: .touchUpInside)
      XCTAssertEqual(store.keyboardAdditions(scope: "guest").map { $0.1.term }, ["helllo"])
      keyboard.field.selectedText = nil; keyboard.selectionDidChange(nil)
      let space = try XCTUnwrap(self.descendants(keyboard.view).compactMap { $0 as? UIButton }
        .first { $0.title(for: .normal) == L("espaço") })
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
    try store.write(state, to: "state.json"); keyboard.refreshFromStore()
    let mic = try XCTUnwrap(descendants(keyboard.view).compactMap { $0 as? RecordControl }.first)
    XCTAssertTrue(mic.accessibilityActivate())
    let start = try XCTUnwrap(store.commands().last?.1)
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
      for delivery in ["pending", "acknowledged", "command expired", "session expired"] {
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
        var result = store.snapshot(); result.phase = .ready; result.text = "Cancelled result"
        result.heartbeat = Date().timeIntervalSince1970
        // Complete before Cancel, while the controller still displays processing.
        try store.write(result, to: "state.json"); cancel.sendActions(for: .touchUpInside)
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
        guard let button = descendants(grid).compactMap({ $0 as? UIButton }).first(where: { $0.title(for: .normal)?.lowercased() == "a" }) else {
          XCTFail("Missing A key"); return
        }
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

import XCTest

final class KeyboardExtensionTests: XCTestCase {
  private var fixtureRoot: URL {
    URL(fileURLWithPath: Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyFixtureDirectory") as! String)
  }
  private func acceptSystemOpenPrompt() {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    let open = springboard.alerts.buttons["Open"]
    if open.waitForExistence(timeout: 5) { open.tap() }
  }
  func testActivationContainerReceivesOpenURL() throws {
    continueAfterFailure = false
    let app = XCUIApplication(); app.launch()
    app.buttons["Open activation fixture"].tap()
    acceptSystemOpenPrompt()
    let receipt = fixtureRoot.appendingPathComponent("return-trace.json")
    let delivered = expectation(for: NSPredicate { _, _ in FileManager.default.fileExists(atPath: receipt.path) }, evaluatedWith: nil)
    wait(for: [delivered], timeout: 10)
    try FileManager.default.copyItem(at: receipt, to: fixtureRoot.appendingPathComponent("container-preflight.json"))
    try FileManager.default.removeItem(at: receipt)
    app.activate()
  }
  private func open(_ title: String, in app: XCUIApplication) {
    // Keep a live query. Binding the row's snapshot identity can fail when
    // Settings rebuilds its SwiftUI list between finding a row and tapping it.
    // The keyboard settings page and its first row can both be titled
    // "Keyboards". Restrict the query to actionable rows, excluding headers.
    let row = app.cells.matching(NSPredicate(format: "label BEGINSWITH %@", title)).firstMatch
    let button = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@ OR identifier == %@", title, title)).firstMatch
    // Settings can finish its tap event before publishing the next list.
    // Wait for its rows before scrolling; an early swipe can dismiss the sheet.
    if !row.waitForExistence(timeout: 3) { _ = button.waitForExistence(timeout: 3) }
    for _ in 0..<8 {
      let item = row.exists ? row : button
      if item.exists && item.isHittable {
        item.tap()
        if ["General", "Keyboard", "Keyboards"].contains(title) {
          let titles = title == "Keyboard" ? ["Keyboard", "Keyboards"] : [title]
          let header = app.navigationBars.matching(NSPredicate(format: "identifier IN %@ OR label IN %@", titles, titles)).firstMatch
          XCTAssertTrue(header.waitForExistence(timeout: 10), "Settings navigation did not complete: \(title)")
        }
        return
      }
      app.swipeUp()
    }
    XCTFail("Settings item unavailable: \(title). \(app.debugDescription)")
  }
  private func checkTrace(in app: XCUIApplication, opening: String, strict: Bool = true) throws {
    let raw = try XCTUnwrap(app.staticTexts["keyboard-frames"].value as? String)
    let values = try JSONDecoder().decode([String: [Double]].self, from: Data(raw.utf8))
    let heights = values.values.flatMap { $0 }
    XCTAssertFalse(heights.isEmpty)
    let trace = XCTAttachment(string: "\(opening): \(raw)"); trace.name = opening
    trace.lifetime = .keepAlways; add(trace)
    continueAfterFailure = true
    defer { continueAfterFailure = false }
    if strict {
      XCTAssertTrue(heights.allSatisfy { $0 < 400 }, "\(opening): \(values)")
    }
    // Publication may defer the known transient overshoot, but must still
    // reject a keyboard that stays oversized or covers the bottom row.
    XCTAssertLessThan(values["displayFrames"]?.last ?? .infinity, 400, "The keyboard must settle at its usable height")
    XCTAssertGreaterThanOrEqual(values["displayFrames"]?.last ?? 0, 278, "The keyboard must remain fully visible")
  }
  private func expectText(_ text: String, in app: XCUIApplication) {
    let inserted = expectation(for: NSPredicate { _, _ in
      app.textFields["composer"].value as? String == text
    }, evaluatedWith: nil)
    wait(for: [inserted], timeout: 3)
  }
  func testNativeSystemKeyboardDoesNotReserveAnOversizedFrame() throws {
    continueAfterFailure = false
    let app = XCUIApplication(); app.launchArguments = ["--system-keyboard"]; app.launch()
    app.secureTextFields["composer"].tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
    try checkTrace(in: app, opening: "Native keyboard initial opening")
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.secureTextFields["composer"].tap()
      XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
      try checkTrace(in: app, opening: "Native keyboard opening \(index)")
    }
  }
  func testInstalledKeyboardTypingAndActivation() throws {
    continueAfterFailure = false
    executionTimeAllowance = 300
    let strictHeight = Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyStrictOpeningHeight") as? Bool ?? true
    let testFullAccess = true
    let app = XCUIApplication(); app.launch()
    let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
    settings.launch()
    open("General", in: settings)
    open("Keyboard", in: settings)
    open("Keyboards", in: settings)
    if !settings.cells.matching(NSPredicate(format: "label BEGINSWITH %@", "Clarify")).firstMatch.exists {
      let addKeyboard = settings.cells["AddNewKeyboard"]
      XCTAssertTrue(addKeyboard.waitForExistence(timeout: 5), settings.debugDescription); addKeyboard.tap()
      open("Clarify", in: settings)
    }
    if testFullAccess {
      open("Clarify", in: settings)
      let access = settings.switches["Allow Full Access"]
      XCTAssertTrue(access.waitForExistence(timeout: 5), settings.debugDescription)
      if access.value as? String != "1" {
        // New Settings exposes the whole labelled row as the switch's frame;
        // the control itself is at its trailing edge.
        access.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
        let allow = settings.alerts.buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
      }
      // The Settings switch can keep a stale AX value after its alert closes.
      // Verify the permission in the extension below, where it affects Start.
    }
    app.activate()
    app.textFields["composer"].tap()
    let keyboard = app.buttons["clarify.keyboard.record"]
    let globe = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", "next keyboard")).firstMatch
    // The first keyboard can still be loading after Settings changes its list.
    // Wait for either input view before deciding whether a switch is needed.
    let inputReady = expectation(for: NSPredicate { _, _ in keyboard.exists || globe.exists }, evaluatedWith: nil)
    wait(for: [inputReady], timeout: 30)
    if !keyboard.exists {
      XCTAssertTrue(globe.exists, app.debugDescription)
      globe.press(forDuration: 1)
      let clarify = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Clarify")).firstMatch
      XCTAssertTrue(clarify.waitForExistence(timeout: 5), app.debugDescription); clarify.tap()
    }
    XCTAssertTrue(keyboard.waitForExistence(timeout: 30), app.debugDescription)
    XCTAssertTrue(app.buttons["clarify.keyboard.start"].waitForExistence(timeout: 5),
                  "The installed extension must receive Full Access before testing activation")
    try checkTrace(in: app, opening: "Switching to the extension", strict: strictHeight)
    let letter = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "q", "Q")).firstMatch
    XCTAssertTrue(letter.waitForExistence(timeout: 5), app.debugDescription); letter.tap()
    expectText("Q", in: app)
    let space = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["space", "espaço", "espacio"])).firstMatch
    XCTAssertTrue(space.isHittable, "The bottom keyboard row must be usable")
    space.tap()
    expectText("Q ", in: app)
    let w = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "w", "W")).firstMatch
    letter.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 0.03,
      thenDragTo: w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)))
    expectText("Q w", in: app)
    var sentence = "Q w"
    for punctuation in [".", "?", "!"] {
      // Letter and number controls expose keyboardKey, not the button trait.
      app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "123")).firstMatch.tap()
      app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", punctuation)).firstMatch.tap()
      app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["space", "espaço", "espacio"])).firstMatch.tap()
      let capital = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "A")).firstMatch
      XCTAssertTrue(capital.waitForExistence(timeout: 5), "Sentence shift must activate after \(punctuation)")
      capital.tap()
      sentence += punctuation + " A"
      expectText(sentence, in: app)
    }
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.textFields["composer"].tap()
      XCTAssertTrue(keyboard.waitForExistence(timeout: 5), app.debugDescription)
      // Querying after presentation keeps every earlier WillChangeFrame notification.
      try checkTrace(in: app, opening: "Opening \(index)", strict: strictHeight)
      let capture = XCTAttachment(screenshot: app.screenshot()); capture.name = "extension-opening-\(index)"
      capture.lifetime = .keepAlways; add(capture)
    }
    let start = app.buttons["clarify.keyboard.start"]
    // The helper consumes the actual keyboard nonce and calls the production
    // bridge. A success return value alone cannot prove that the app opened.
    let container = XCUIApplication(bundleIdentifier: "com.clarify.fixture.container")
    let root = try XCTUnwrap(Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyFixtureDirectory") as? String)
    XCTAssertTrue(FileManager.default.fileExists(atPath: URL(fileURLWithPath: root).appendingPathComponent("container-ready.json").path),
                  "The isolated containing app must initialize before testing its activation URL")
    let receipt = URL(fileURLWithPath: root).appendingPathComponent("return-trace.json")
    for attempt in 0..<2 {
      if FileManager.default.fileExists(atPath: receipt.path) { try FileManager.default.removeItem(at: receipt) }
      XCTAssertTrue(start.waitForExistence(timeout: 5), app.debugDescription)
      start.tap(); acceptSystemOpenPrompt()
      let activated = expectation(for: NSPredicate { _, _ in FileManager.default.fileExists(atPath: receipt.path) }, evaluatedWith: nil)
      wait(for: [activated], timeout: 10)
      let diagnostic = XCTAttachment(string: (try? String(contentsOf: receipt, encoding: .utf8)) ?? container.debugDescription)
      diagnostic.name = "activation-return-\(attempt)"; diagnostic.lifetime = .keepAlways; add(diagnostic)
      let values = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: receipt))
      XCTAssertEqual(values["nonceConsumed"], "true", "The real activation request must be consumed")
      XCTAssertEqual(values["source"], "com.clarify.fixture.host", "Resolve the current origin, not an old app")
      XCTAssertEqual(values["opened"], "true", "The production return bridge must accept the source")
      let back = expectation(for: NSPredicate { _, _ in
        app.state == .runningForeground && container.state != .runningForeground
      }, evaluatedWith: nil)
      wait(for: [back], timeout: 10)
    }
  }
}

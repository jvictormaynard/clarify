import XCTest

final class KeyboardExtensionTests: XCTestCase {
  private func open(_ title: String, in app: XCUIApplication) {
    for _ in 0..<8 {
      let headerBottom = app.navigationBars.firstMatch.frame.maxY
      // Settings can expose the same row as Other or StaticText while its
      // snapshot changes. Bind by accessibility identity, not by list index.
      let candidates = app.descendants(matching: .any)
        .matching(NSPredicate(format: "label == %@ OR identifier == %@", title, title))
        .allElementsBoundByAccessibilityElement
      for item in candidates {
        guard item.exists else { continue }
        let frame = item.frame
        if !frame.isInfinite && frame.minY >= headerBottom && frame.maxY <= app.frame.maxY && item.isHittable {
          item.tap()
          if ["General", "Keyboard", "Keyboards"].contains(title) {
            let titles = title == "Keyboard" ? ["Keyboard", "Keyboards"] : [title]
            let header = app.navigationBars.matching(NSPredicate(format: "identifier IN %@ OR label IN %@", titles, titles)).firstMatch
            XCTAssertTrue(header.waitForExistence(timeout: 10), "Settings navigation did not complete: \(title)")
          }
          return
        }
      }
      app.swipeUp()
    }
    XCTFail("Settings item unavailable: \(title). \(app.debugDescription)")
  }
  private func checkTrace(in app: XCUIApplication, opening: String) throws {
    let raw = try XCTUnwrap(app.staticTexts["keyboard-frames"].value as? String)
    let values = try JSONDecoder().decode([String: [Double]].self, from: Data(raw.utf8))
    let heights = values.values.flatMap { $0 }
    XCTAssertFalse(heights.isEmpty)
    let trace = XCTAttachment(string: "\(opening): \(raw)"); trace.name = opening
    trace.lifetime = .keepAlways; add(trace)
    continueAfterFailure = true
    defer { continueAfterFailure = false }
    XCTAssertTrue(heights.allSatisfy { $0 < 400 }, "\(opening): \(values)")
    XCTAssertGreaterThanOrEqual(values["displayFrames"]?.last ?? 0, 278, "The keyboard must remain fully visible")
  }
  private func expectText(_ text: String, in app: XCUIApplication) {
    let inserted = expectation(for: NSPredicate { _, _ in
      (app.textFields["composer"].value as? String)?.lowercased() == text
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
  func testOpeningTheInstalledKeyboardExtensionDoesNotReserveAnOversizedFrame() throws {
    continueAfterFailure = false
    executionTimeAllowance = 300
    let testFullAccess = true
    let app = XCUIApplication(); app.launch()
    let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
    settings.launch()
    open("General", in: settings)
    open("Keyboard", in: settings)
    open("Keyboards", in: settings)
    if !settings.cells.matching(NSPredicate(format: "label BEGINSWITH %@", "Clarify")).firstMatch.exists {
      let addKeyboard = settings.buttons["AddNewKeyboard"]
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
      let granted = expectation(for: NSPredicate(format: "value == %@", "1"), evaluatedWith: access)
      wait(for: [granted], timeout: 5)
    }
    app.launch()
    app.textFields["composer"].tap()
    let keyboard = app.buttons["clarify.keyboard.record"]
    if !keyboard.waitForExistence(timeout: 2) {
      let globe = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", "next keyboard")).firstMatch
      XCTAssertTrue(globe.waitForExistence(timeout: 5), app.debugDescription)
      globe.press(forDuration: 1)
      let clarify = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Clarify")).firstMatch
      XCTAssertTrue(clarify.waitForExistence(timeout: 5), app.debugDescription); clarify.tap()
    }
    XCTAssertTrue(keyboard.waitForExistence(timeout: 30), app.debugDescription)
    try checkTrace(in: app, opening: "Switching to the extension")
    let letter = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "q", "Q")).firstMatch
    XCTAssertTrue(letter.waitForExistence(timeout: 5), app.debugDescription); letter.tap()
    expectText("q", in: app)
    let space = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["space", "espaço", "espacio"])).firstMatch
    XCTAssertTrue(space.isHittable, "The bottom keyboard row must be usable")
    space.tap()
    expectText("q ", in: app)
    let w = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "w", "W")).firstMatch
    letter.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 0.03,
      thenDragTo: w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)))
    expectText("q w", in: app)
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.textFields["composer"].tap()
      XCTAssertTrue(keyboard.waitForExistence(timeout: 5), app.debugDescription)
      // Querying after presentation keeps every earlier WillChangeFrame notification.
      try checkTrace(in: app, opening: "Opening \(index)")
      let capture = XCTAttachment(screenshot: app.screenshot()); capture.name = "extension-opening-\(index)"
      capture.lifetime = .keepAlways; add(capture)
    }
    if Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyDiagnosticVariant") as? String == "without-swiftui" { return }
    let start = app.buttons["clarify.keyboard.start"]
    XCTAssertTrue(start.waitForExistence(timeout: 5), app.debugDescription)
    start.tap()
    // The helper consumes the actual keyboard nonce and calls the production
    // bridge. A success return value alone cannot prove that the app opened.
    let container = XCUIApplication(bundleIdentifier: "com.clarify.fixture.container")
    let root = try XCTUnwrap(Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyFixtureDirectory") as? String)
    let receipt = URL(fileURLWithPath: root).appendingPathComponent("return-trace.json")
    let activated = expectation(for: NSPredicate { _, _ in FileManager.default.fileExists(atPath: receipt.path) }, evaluatedWith: nil)
    wait(for: [activated], timeout: 10)
    let diagnostic = XCTAttachment(string: (try? String(contentsOf: receipt, encoding: .utf8)) ?? container.debugDescription)
    diagnostic.name = "activation-return"; diagnostic.lifetime = .keepAlways; add(diagnostic)
    let back = expectation(for: NSPredicate(format: "state == %d", XCUIApplication.State.runningForeground.rawValue), evaluatedWith: app)
    wait(for: [back], timeout: 10)
    XCTAssertNotEqual(container.state, .runningForeground, "Activation must return to the original host")
  }
}

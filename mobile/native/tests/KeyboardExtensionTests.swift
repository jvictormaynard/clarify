import XCTest

final class KeyboardExtensionTests: XCTestCase {
  private func open(_ title: String, in app: XCUIApplication) {
    for _ in 0..<8 {
      let headerBottom = app.navigationBars.firstMatch.frame.maxY
      let candidates = app.buttons.matching(identifier: title).allElementsBoundByIndex + app.staticTexts.matching(identifier: title).allElementsBoundByIndex
      for item in candidates {
        let frame = item.frame
        if !frame.isInfinite && frame.minY >= headerBottom && frame.maxY <= app.frame.maxY && item.isHittable {
          item.tap(); return
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
  }
  func testOpeningTheInstalledKeyboardExtensionDoesNotReserveAnOversizedFrame() throws {
    continueAfterFailure = false
    executionTimeAllowance = 300
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
    app.launch()
    app.textFields["composer"].tap()
    if !app.staticTexts["Allow Full Access"].waitForExistence(timeout: 2) {
      let globe = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", "next keyboard")).firstMatch
      XCTAssertTrue(globe.waitForExistence(timeout: 5), app.debugDescription)
      globe.press(forDuration: 1)
      let clarify = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Clarify")).firstMatch
      XCTAssertTrue(clarify.waitForExistence(timeout: 5), app.debugDescription); clarify.tap()
    }
    XCTAssertTrue(app.staticTexts["Allow Full Access"].waitForExistence(timeout: 5), app.debugDescription)
    try checkTrace(in: app, opening: "Switching to the extension")
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.textFields["composer"].tap()
      XCTAssertTrue(app.staticTexts["Allow Full Access"].waitForExistence(timeout: 5), app.debugDescription)
      // Querying after presentation keeps every earlier WillChangeFrame notification.
      try checkTrace(in: app, opening: "Opening \(index)")
      let capture = XCTAttachment(screenshot: app.screenshot()); capture.name = "extension-opening-\(index)"
      capture.lifetime = .keepAlways; add(capture)
    }
  }
}

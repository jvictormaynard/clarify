import XCTest

final class KeyboardExtensionTests: XCTestCase {
  private func open(_ title: String, in app: XCUIApplication) {
    let item = app.tables.staticTexts[title].firstMatch
    for _ in 0..<8 {
      if item.exists && item.isHittable { item.tap(); return }
      app.swipeUp()
    }
    XCTFail("Settings item unavailable: \(title). \(app.debugDescription)")
  }
  func testOpeningTheInstalledKeyboardExtensionDoesNotReserveAnOversizedFrame() throws {
    continueAfterFailure = false
    let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
    settings.launch()
    open("General", in: settings)
    open("Keyboard", in: settings)
    open("Keyboards", in: settings)
    let addKeyboard = settings.tables.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Add New Keyboard")).firstMatch
    XCTAssertTrue(addKeyboard.waitForExistence(timeout: 5)); addKeyboard.tap()
    open("Clarify", in: settings)
    let app = XCUIApplication(); app.launch()
    app.textFields["composer"].tap()
    let globe = app.buttons["Next keyboard"].firstMatch
    XCTAssertTrue(globe.waitForExistence(timeout: 5), app.debugDescription)
    globe.press(forDuration: 1)
    let clarify = app.staticTexts["Clarify"].firstMatch
    XCTAssertTrue(clarify.waitForExistence(timeout: 5), app.debugDescription); clarify.tap()
    XCTAssertTrue(app.buttons["Start in Clarify"].waitForExistence(timeout: 5), app.debugDescription)
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.textFields["composer"].tap()
      XCTAssertTrue(app.buttons["Start in Clarify"].waitForExistence(timeout: 5))
      // Querying after presentation keeps every earlier WillChangeFrame notification.
      let raw = try XCTUnwrap(app.staticTexts["keyboard-frames"].value as? String)
      let values = try JSONDecoder().decode([String: [Double]].self, from: Data(raw.utf8))
      let heights = values.values.flatMap { $0 }
      XCTAssertFalse(heights.isEmpty)
      XCTAssertTrue(heights.allSatisfy { $0 < 400 }, "Opening \(index): \(heights)")
      let capture = XCTAttachment(screenshot: app.screenshot()); capture.name = "extension-opening-\(index)"
      capture.lifetime = .keepAlways; add(capture)
    }
  }
}

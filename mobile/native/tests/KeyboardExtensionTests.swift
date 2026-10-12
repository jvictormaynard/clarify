import XCTest

final class KeyboardExtensionTests: XCTestCase {
  func testOpeningTheInstalledKeyboardExtensionDoesNotReserveAnOversizedFrame() throws {
    continueAfterFailure = false
    let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
    settings.launch()
    settings.tables.staticTexts["General"].tap()
    settings.tables.staticTexts["Keyboard"].tap()
    settings.tables.staticTexts["Keyboards"].firstMatch.tap()
    settings.tables.staticTexts["Add New Keyboard…"].tap()
    settings.tables.staticTexts["Clarify"].tap()
    let app = XCUIApplication(); app.launch()
    app.textFields["composer"].tap()
    let globe = app.buttons["Next keyboard"].firstMatch
    XCTAssertTrue(globe.waitForExistence(timeout: 5), app.debugDescription)
    globe.press(forDuration: 1)
    let clarify = app.staticTexts["Clarify"].firstMatch
    XCTAssertTrue(clarify.waitForExistence(timeout: 5), app.debugDescription); clarify.tap()
    XCTAssertTrue(app.buttons["Começar no Clarify"].waitForExistence(timeout: 5), app.debugDescription)
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.textFields["composer"].tap()
      XCTAssertTrue(app.buttons["Começar no Clarify"].waitForExistence(timeout: 5))
      // Querying after presentation keeps every earlier WillChangeFrame notification.
      let raw = app.staticTexts["keyboard-frames"].label
      let heights = try JSONDecoder().decode([Double].self, from: Data(raw.utf8))
      XCTAssertFalse(heights.isEmpty)
      XCTAssertTrue(heights.allSatisfy { $0 < 400 }, "Opening \(index): \(heights)")
      let capture = XCTAttachment(screenshot: app.screenshot()); capture.name = "extension-opening-\(index)"
      capture.lifetime = .keepAlways; add(capture)
    }
  }
}

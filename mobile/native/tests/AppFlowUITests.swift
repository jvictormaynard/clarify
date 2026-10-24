import XCTest

final class AppFlowUITests: XCTestCase {
  let app = XCUIApplication(bundleIdentifier: "com.jvictormaynard.clarify")
  override func setUp() {
    super.setUp(); continueAfterFailure = false
    app.launchArguments = ["-AppleLanguages", "(pt)", "-AppleLocale", "pt_BR"]
  }
  func capture(_ name: String) {
    let attachment = XCTAttachment(screenshot: app.screenshot())
    attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
  }
  func diagnose(_ name: String) {
    capture(name)
    print("APP_UI_DIAGNOSTIC \(name)\n\(app.debugDescription)")
  }
  func press(_ identifier: String) {
    let button = app.buttons[identifier].firstMatch
    guard button.waitForExistence(timeout: 15) else {
      diagnose("missing-\(identifier)"); XCTFail("Missing action: \(identifier)"); return
    }
    let enabled = expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: button)
    guard XCTWaiter.wait(for: [enabled], timeout: 15) == .completed else {
      diagnose("disabled-\(identifier)"); XCTFail("Disabled action: \(identifier)"); return
    }
    if !button.isHittable { diagnose("before-scroll-\(identifier)"); app.swipeUp() }
    guard button.isHittable else {
      diagnose("unreachable-\(identifier)"); XCTFail("Unreachable action: \(identifier)"); return
    }
    button.tap()
  }
  func tab(_ label: String) {
    let button = app.tabBars.buttons[label].firstMatch
    XCTAssertTrue(button.waitForExistence(timeout: 20), "Missing tab: \(label)")
    button.tap()
  }
  func testFirstPresentationAccountNavigationAndExplicitReplay() {
    app.launch()
    XCTAssertTrue(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.waitForExistence(timeout: 30))
    capture("onboarding-first-open")
    press("onboarding.skip")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    app.terminate(); app.launch()
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 20))
    XCTAssertFalse(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.exists)
    app.textFields["account.email"].tap()
    app.textFields["account.email"].typeText("clarify-e2e@example.test")
    XCTAssertEqual(app.textFields["account.email"].value as? String, "clarify-e2e@example.test")
    press("account.requestCode")
    guard app.textFields["account.code"].waitForExistence(timeout: 15) else {
      diagnose("login-code-missing"); XCTFail("Login did not show the code field. Inspect the HTTP journal and app alert."); return
    }
    app.textFields["account.code"].tap(); app.textFields["account.code"].typeText("123456")
    press("account.verifyCode")
    tab("Início"); capture("home-dark")
    tab("Dicionário"); capture("dictionary-dark")
    tab("Snippets"); capture("snippets-dark")
    tab("Conta"); capture("account-dark")
    press("account.settings"); capture("settings-dark")
    app.navigationBars.buttons.firstMatch.tap()
    press("account.guide")
    XCTAssertTrue(app.descendants(matching: .any)["onboarding.keyboard"].firstMatch.waitForExistence(timeout: 15))
    capture("guide-keyboard-dark")
    app.navigationBars.buttons.firstMatch.tap()
    press("account.logout")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    app.terminate(); app.launch()
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 20))
    XCTAssertFalse(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.exists)
    capture("login-after-logout")
  }
}

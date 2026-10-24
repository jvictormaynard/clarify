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
  func press(_ identifier: String) {
    let button = app.buttons[identifier].firstMatch
    XCTAssertTrue(button.waitForExistence(timeout: 15), "Missing action: \(identifier)")
    if !button.isHittable { app.swipeUp() }
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
    press("account.requestCode")
    XCTAssertTrue(app.textFields["account.code"].waitForExistence(timeout: 15))
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

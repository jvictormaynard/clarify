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
  func press(_ identifier: String, allowScroll: Bool = true) {
    let button = app.buttons[identifier].firstMatch
    guard button.waitForExistence(timeout: 15) else {
      diagnose("missing-\(identifier)"); XCTFail("Missing action: \(identifier)"); return
    }
    let enabled = expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: button)
    guard XCTWaiter.wait(for: [enabled], timeout: 15) == .completed else {
      diagnose("disabled-\(identifier)"); XCTFail("Disabled action: \(identifier)"); return
    }
    if allowScroll && !button.isHittable { diagnose("before-scroll-\(identifier)"); app.swipeUp() }
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
  func pressWithKeyboard(_ identifier: String, field: XCUIElement, value: String) {
    let keyboard = app.keyboards.firstMatch
    XCTAssertTrue(keyboard.exists && keyboard.isHittable, "Keep the keyboard open for \(identifier)")
    let button = app.buttons[identifier].firstMatch
    XCTAssertTrue(button.waitForExistence(timeout: 15))
    if !button.isHittable {
      diagnose("keyboard-before-scroll-\(identifier)")
      let page = app.scrollViews.firstMatch
      XCTAssertTrue(page.exists && page.isHittable)
      page.swipeUp()
    }
    let reachable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true"), object: button)
    XCTAssertEqual(XCTWaiter.wait(for: [reachable], timeout: 5), .completed, "Reach \(identifier) with the keyboard open")
    XCTAssertTrue(keyboard.exists && keyboard.isHittable, "Scrolling must keep the keyboard open")
    XCTAssertTrue(field.isHittable, "Keep the input visible beside its action")
    XCTAssertEqual(field.value as? String, value, "Scrolling must retain the complete input")
    capture("keyboard-action-ready-\(identifier)")
    press(identifier, allowScroll: false)
  }
  func enter(_ value: String, in field: XCUIElement, name: String) {
    XCTAssertTrue(field.waitForExistence(timeout: 15))
    field.tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10))
    var expected = ""
    for character in value {
      expected += String(character)
      field.typeText(String(character))
      let updated = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", expected), object: field)
      guard XCTWaiter.wait(for: [updated], timeout: 5) == .completed else {
        diagnose("typing-\(name)"); XCTFail("Input did not retain the typed characters: \(name)"); return
      }
    }
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
    press("processing.computer")
    XCTAssertTrue(app.buttons["computer.scan"].waitForExistence(timeout: 10))
    XCTAssertFalse(app.textFields["account.email"].exists, "Computer pairing does not require hosted sign-in")
    XCTAssertFalse(app.tabBars.firstMatch.exists, "Choosing a mode alone does not authorize processing")
    press("processing.hosted")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 10))
    for provider in ["Google", "Microsoft", "GitHub"] {
      XCTAssertTrue(app.buttons["Continuar com \(provider)"].exists, "Social sign-in remains available")
    }
    enter("clarify-e2e@example.test", in: app.textFields["account.email"], name: "email")
    XCTAssertEqual(app.textFields["account.email"].value as? String, "clarify-e2e@example.test")
    capture("login-email-keyboard-visible")
    pressWithKeyboard("account.requestCode", field: app.textFields["account.email"], value: "clarify-e2e@example.test")
    guard app.textFields["account.code"].waitForExistence(timeout: 15) else {
      diagnose("login-code-missing"); XCTFail("Login did not show the code field. Inspect the HTTP journal and app alert."); return
    }
    enter("123456", in: app.textFields["account.code"], name: "code")
    capture("login-code-keyboard-visible")
    pressWithKeyboard("account.verifyCode", field: app.textFields["account.code"], value: "123456")
    tab("Início")
    XCTAssertFalse(app.buttons["home.account"].exists, "Account opens from the bottom tabs")
    XCTAssertEqual(app.tabBars.buttons.count, 4)
    capture("home-dark")
    tab("Dicionário")
    XCTAssertEqual(app.buttons.matching(identifier: "Snippets").count, 1, "Snippets has one destination in the bottom tabs")
    capture("dictionary-dark")
    tab("Snippets"); capture("snippets-dark")
    tab("Conta")
    XCTAssertTrue(app.descendants(matching: .any)["app.account"].firstMatch.waitForExistence(timeout: 15))
    let weeklyUsage = app.staticTexts["account.weeklyUsage"]
    XCTAssertTrue(weeklyUsage.waitForExistence(timeout: 15))
    XCTAssertEqual(weeklyUsage.label, "12,5% usados · 82,5% restantes", "Pending reservations must not count as consumed quota")
    XCTAssertTrue(app.staticTexts["Uso nesta semana"].exists)
    XCTAssertTrue(app.staticTexts["account.usageReset"].label.hasPrefix("Próxima renovação: "))
    XCTAssertFalse(app.staticTexts["A cota semanal não está disponível. Atualize para tentar novamente."].exists)
    capture("account-dark")
    press("account.settings"); capture("settings-dark")
    app.navigationBars.buttons.firstMatch.tap()
    XCTAssertTrue(app.tabBars.buttons["Conta"].isSelected)
    press("account.guide")
    XCTAssertTrue(app.descendants(matching: .any)["onboarding.keyboard"].firstMatch.waitForExistence(timeout: 15))
    capture("guide-keyboard-dark")
    app.navigationBars.buttons.firstMatch.tap()
    XCTAssertTrue(app.tabBars.buttons["Conta"].isSelected)
    tab("Início")
    XCTAssertFalse(app.buttons["home.account"].exists)
    tab("Conta")
    press("account.logout")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    app.terminate(); app.launch()
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 20))
    XCTAssertFalse(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.exists)
    capture("login-after-logout")
  }
}

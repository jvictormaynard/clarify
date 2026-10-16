import XCTest

// This runner opens the real, separately built Clarify app. It contains no
// product views, credentials, network mocks or screenshot overlays.
final class StoreScreenshots: XCTestCase {
  private let labels: [String: [String: String]] = [
    "pt": ["welcome": "Boas-vindas ao Clarify", "skip": "Continuar sem conta", "dictionary": "Dicionário", "account": "Conta", "login": "Entrar ou criar conta"],
    "en": ["welcome": "Welcome to Clarify", "skip": "Continue without an account", "dictionary": "Dictionary", "account": "Account", "login": "Sign in or create account"],
    "es": ["welcome": "Te damos la bienvenida a Clarify", "skip": "Continuar sin cuenta", "dictionary": "Diccionario", "account": "Cuenta", "login": "Entrar o crear cuenta"]
  ]

  override func setUpWithError() throws { continueAfterFailure = false }

  private func open(_ language: String, ready: Bool) -> XCUIApplication {
    let app = XCUIApplication(bundleIdentifier: "com.jvictormaynard.clarify")
    app.launchArguments = ["-AppleLanguages", "(\(language))", "-AppleLocale", language == "pt" ? "pt_BR" : language == "es" ? "es_ES" : "en_US"]
    // Standard launch defaults select the already-completed onboarding state.
    // No product code is changed and no API key/account is created.
    if ready { app.launchArguments += ["-clarify.onboarding.completed", "YES"] }
    app.launch()
    return app
  }

  private func capture(_ name: String, app: XCUIApplication) {
    XCTAssertEqual(app.alerts.count, 0, "Unexpected alert before store screenshot")
    XCTAssertEqual(app.keyboards.count, 0, "Keyboard must not obscure the screen")
    // Let native navigation and safe-area animations finish after the semantic
    // readiness checks. This does not replace those checks with a fixed sleep.
    RunLoop.current.run(until: Date().addingTimeInterval(1))
    let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
    attachment.name = name
    attachment.lifetime = .keepAlways
    add(attachment)
  }

  private func onboarding(_ language: String) {
    let app = open(language, ready: false)
    defer { app.terminate() }
    XCTAssertTrue(app.staticTexts[labels[language]!["welcome"]!].firstMatch.waitForExistence(timeout: 45))
    XCTAssertTrue(app.buttons[labels[language]!["skip"]!].firstMatch.waitForExistence(timeout: 10))
    capture("\(language)-01-onboarding", app: app)
  }

  private func screens(_ language: String) {
    let app = open(language, ready: true)
    defer { app.terminate() }
    XCTAssertTrue(app.tabBars.firstMatch.waitForExistence(timeout: 45))
    XCTAssertTrue(app.staticTexts[labels[language]!["welcome"]!].firstMatch.waitForExistence(timeout: 10))
    let historyRow = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Mobile")).firstMatch
    XCTAssertTrue(historyRow.waitForExistence(timeout: 10), "Seeded local history must be rendered by the real app")
    capture("\(language)-02-home", app: app)

    let dictionary = app.tabBars.buttons[labels[language]!["dictionary"]!].firstMatch
    XCTAssertTrue(dictionary.waitForExistence(timeout: 10))
    dictionary.tap()
    let vocabulary = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Open source")).firstMatch
    XCTAssertTrue(vocabulary.waitForExistence(timeout: 15), "Seeded vocabulary must be rendered by the real app")
    capture("\(language)-03-dictionary", app: app)

    let account = app.tabBars.buttons[labels[language]!["account"]!].firstMatch
    XCTAssertTrue(account.waitForExistence(timeout: 10))
    account.tap()
    XCTAssertTrue(app.buttons[labels[language]!["login"]!].firstMatch.waitForExistence(timeout: 15))
    capture("\(language)-04-account", app: app)
  }

  func testOnboardingPT() { onboarding("pt") }
  func testOnboardingEN() { onboarding("en") }
  func testOnboardingES() { onboarding("es") }
  func testScreensPT() { screens("pt") }
  func testScreensEN() { screens("en") }
  func testScreensES() { screens("es") }
}

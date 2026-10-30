import XCTest
import CoreFoundation

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
    let button = app.descendants(matching: .any)[identifier].firstMatch
    guard button.waitForExistence(timeout: 15) else {
      diagnose("missing-\(identifier)"); XCTFail("Missing action: \(identifier)"); return
    }
    let enabled = expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: button)
    guard XCTWaiter.wait(for: [enabled], timeout: 15) == .completed else {
      diagnose("disabled-\(identifier)"); XCTFail("Disabled action: \(identifier)"); return
    }
    if allowScroll {
      for _ in 0..<6 where !button.isHittable {
        if button.frame.midY < app.frame.midY { app.swipeDown() } else { app.swipeUp() }
      }
    }
    guard button.isHittable else {
      diagnose("unreachable-\(identifier)"); XCTFail("Unreachable action: \(identifier)"); return
    }
    button.tap()
  }
  func tab(_ label: String) {
    let button = app.tabBars.buttons[label].firstMatch
    XCTAssertTrue(button.waitForExistence(timeout: 20), "Missing tab: \(label)")
    let introduction = app.otherElements["UIContinuousPathIntroductionView"].firstMatch
    if introduction.exists {
      capture("system-keyboard-introduction")
      let proceed = introduction.buttons["Continue"].firstMatch
      guard proceed.waitForExistence(timeout: 5) && proceed.isHittable else {
        diagnose("keyboard-introduction-blocked"); XCTFail("Cannot finish the system keyboard introduction"); return
      }
      proceed.tap()
      let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: introduction)
      guard XCTWaiter.wait(for: [closed], timeout: 5) == .completed else {
        diagnose("keyboard-introduction-remains"); XCTFail("System keyboard introduction is still visible"); return
      }
    }
    let keyboard = app.keyboards.firstMatch
    if keyboard.exists {
      let page = app.descendants(matching: .any)["app.keyboard-page"].firstMatch.scrollViews.firstMatch
      guard page.exists && page.frame.intersects(app.frame) else {
        diagnose("keyboard-dismissal-page-missing"); XCTFail("Cannot reach the page to dismiss the keyboard"); return
      }
      // The center of the page can be an independently scrolling TextView.
      // Container isHittable does not establish whether its gutter can be dragged.
      // Use that gutter so the page's interactive dismissal runs.
      let start = page.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.2))
      // Interactive dismissal follows the touch. Cross the keyboard's top edge
      // instead of stopping inside the page that has already resized above it.
      let finish = app.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.95))
      start.press(forDuration: 0.1, thenDragTo: finish)
      let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: keyboard)
      guard XCTWaiter.wait(for: [dismissed], timeout: 5) == .completed else {
        diagnose("keyboard-obscures-tab-\(label)"); XCTFail("Dismiss the keyboard before choosing tab: \(label)"); return
      }
    }
    let reachable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true"), object: button)
    guard XCTWaiter.wait(for: [reachable], timeout: 5) == .completed else {
      diagnose("unreachable-tab-\(label)"); XCTFail("Unreachable tab: \(label)"); return
    }
    button.tap()
    let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "selected == true"), object: button)
    XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 5), .completed, "Select tab: \(label)")
  }
  func pressWithKeyboard(_ identifier: String, field: XCUIElement, value: String) {
    let keyboard = app.keyboards.firstMatch
    XCTAssertTrue(keyboard.exists && keyboard.isHittable, "Keep the keyboard open for \(identifier)")
    let button = app.buttons[identifier].firstMatch
    XCTAssertTrue(button.waitForExistence(timeout: 15))
    if !button.isHittable {
      diagnose("keyboard-before-scroll-\(identifier)")
      let page = app.descendants(matching: .any)["app.keyboard-page"].firstMatch.scrollViews.firstMatch
      XCTAssertTrue(page.exists && page.isHittable)
      let distance = min(max(button.frame.maxY - page.frame.maxY + 16, 16), page.frame.height * 0.6)
      let start = page.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.85))
      let finish = page.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.85 - distance / page.frame.height))
      start.press(forDuration: 0.1, thenDragTo: finish)
    }
    let reachable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true"), object: button)
    XCTAssertEqual(XCTWaiter.wait(for: [reachable], timeout: 5), .completed, "Reach \(identifier) with the keyboard open")
    XCTAssertTrue(keyboard.exists && keyboard.isHittable, "Scrolling must keep the keyboard open")
    XCTAssertTrue(field.isHittable, "Keep the input visible beside its action")
    XCTAssertEqual(field.value as? String, value, "Scrolling must retain the complete input")
    capture("keyboard-action-ready-\(identifier)")
    press(identifier, allowScroll: false)
  }
  func enter(_ value: String, in field: XCUIElement, name: String, replacing: Bool = false) {
    XCTAssertTrue(field.waitForExistence(timeout: 15))
    field.tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10))
    if replacing { field.typeKey("a", modifierFlags: .command) }
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
  func fixture(_ path: String, values: [String: Any]? = nil) -> [String: Any] {
    let completed = expectation(description: "Fixture \(path)")
    var output: [String: Any] = [:]
    var request = URLRequest(url: URL(string: "__CLARIFY_APP_UI_ENDPOINT__" + path)!)
    if let values {
      request.httpMethod = "POST"; request.httpBody = try! JSONSerialization.data(withJSONObject: values)
      request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    URLSession.shared.dataTask(with: request) { data, response, error in
      XCTAssertNil(error)
      XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
      if let data { output = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:] }
      completed.fulfill()
    }.resume()
    XCTAssertEqual(XCTWaiter.wait(for: [completed], timeout: 15), .completed)
    return output
  }
  func absent(_ element: XCUIElement) {
    let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: element)
    XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 15), .completed)
  }
  func back() { app.navigationBars.buttons.firstMatch.tap() }
  func chooseRewrite() {
    press("actions.choose")
    press("actions.option.saved:rewrite:1")
  }
  func verifyActions() {
    tab("Ações")
    let text = app.textViews["actions.text"]
    enter("cancelled-preparation", in: text, name: "composer")
    capture("actions-draft-keyboard")
    chooseRewrite()
    tab("Biblioteca"); tab("Ações")
    XCTAssertEqual(text.value as? String, "cancelled-preparation", "Tab navigation keeps the mounted draft")
    press("actions.refresh")
    XCTAssertEqual(text.value as? String, "cancelled-preparation")
    press("actions.choose"); press("Fechar")
    XCTAssertEqual(text.value as? String, "cancelled-preparation", "Sheet dismissal keeps the draft")
    let previousPosts = (fixture("/__fixture/state")["processing"] as? [Any])?.count
    _ = fixture("/__fixture/control", values: ["catalog": "slow"])
    press("actions.run")
    let progress = app.staticTexts.matching(NSPredicate(format: "identifier BEGINSWITH 'actions.operation.' AND identifier != 'actions.operation.starting'")).firstMatch
    XCTAssertTrue(progress.waitForExistence(timeout: 10), "Accepted UUID must arrive before discovery completes")
    let identifier = progress.identifier.replacingOccurrences(of: "actions.operation.", with: "")
    XCTAssertNotNil(UUID(uuidString: identifier))
    XCTAssertEqual(fixture("/__fixture/wait-catalog")["held"] as? Int, 1)
    XCTAssertFalse(app.buttons["actions.copy"].exists)
    capture("actions-slow-catalog-accepted")
    press("actions.cancel")
    absent(app.buttons["actions.cancel"])
    _ = fixture("/__fixture/control", values: ["release": true])
    XCTAssertEqual((fixture("/__fixture/state")["processing"] as? [Any])?.count, previousPosts)
    XCTAssertEqual(text.value as? String, "cancelled-preparation")
    XCTAssertFalse(app.buttons["actions.copy"].exists)
    // Reload the interrupted catalog before starting the next independent case.
    press("actions.refresh"); chooseRewrite()
    XCTAssertEqual(text.value as? String, "cancelled-preparation")
    enter("deactivated-preparation", in: text, name: "deactivated-composer", replacing: true)
    _ = fixture("/__fixture/control", values: ["catalog": "slow"])
    press("actions.run")
    XCTAssertTrue(progress.waitForExistence(timeout: 10))
    XCTAssertNotNil(UUID(uuidString: progress.identifier.replacingOccurrences(of: "actions.operation.", with: "")))
    XCTAssertEqual(fixture("/__fixture/wait-catalog")["held"] as? Int, 1)
    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
      CFNotificationName("com.clarify.app-flow.deactivate" as CFString), nil, nil, true)
    absent(app.buttons["actions.cancel"])
    _ = fixture("/__fixture/control", values: ["release": true])
    XCTAssertEqual((fixture("/__fixture/state")["processing"] as? [Any])?.count, previousPosts)
    XCTAssertFalse(app.buttons["actions.copy"].exists)
    capture("actions-deactivated-discovery")
    enter("cancelled-preparation", in: text, name: "cancelled-composer", replacing: true)
    for mode in ["empty", "failed"] {
      _ = fixture("/__fixture/control", values: ["catalog": mode])
      press("actions.refresh")
      let status = app.staticTexts["actions.catalog-status"]
      XCTAssertTrue(status.waitForExistence(timeout: 10))
      let expected = mode == "empty" ? "Nenhuma ação salva neste destino." : "Não foi possível carregar as ações. Atualize para tentar novamente."
      let updated = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", expected), object: status)
      XCTAssertEqual(XCTWaiter.wait(for: [updated], timeout: 15), .completed)
      XCTAssertFalse(app.buttons["actions.run"].isEnabled)
      XCTAssertEqual(text.value as? String, "cancelled-preparation")
      capture("actions-catalog-\(mode)")
    }
    _ = fixture("/__fixture/control", values: ["catalog": "ready"])
    press("actions.refresh"); chooseRewrite()
    enter("successful-action", in: text, name: "successful-composer", replacing: true)
    press("actions.run")
    XCTAssertTrue(app.staticTexts["actions.result"].waitForExistence(timeout: 15))
    XCTAssertEqual(app.staticTexts["actions.result"].label, "Fixture result: successful-action")
    press("actions.copy")
    capture("actions-owned-result")
    press("actions.choose"); press("actions.option.saved:translation:1")
    absent(app.staticTexts["actions.result"])
    press("actions.language")
    for language in ["pt", "en", "es", "de", "ru"] {
      XCTAssertTrue(app.descendants(matching: .any)["actions.target.\(language)"].firstMatch.exists)
    }
    press("actions.target.ru")
    press("actions.run")
    XCTAssertTrue(app.staticTexts["actions.result"].waitForExistence(timeout: 15))
    let posted = fixture("/__fixture/state")["processing"] as? [[String: Any]]
    let translation = posted?.last?["value"] as? [String: Any]
    XCTAssertEqual(translation?["language"] as? String, "ru")
    capture("actions-translation-russian")
    _ = fixture("/__fixture/control", values: ["revision": 2])
    press("actions.refresh")
    XCTAssertTrue(app.staticTexts["actions.catalog-status"].waitForExistence(timeout: 10))
    let stale = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == false"), object: app.buttons["actions.run"])
    XCTAssertEqual(XCTWaiter.wait(for: [stale], timeout: 15), .completed)
    capture("actions-stale-choice")
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
    tab("Ditado")
    XCTAssertEqual(app.tabBars.buttons.count, 4)
    XCTAssertFalse(app.buttons["home.account"].exists)
    capture("dictation")
    tab("Biblioteca")
    press("library.dictionary"); capture("dictionary")
    press("Adicionar palavra")
    let word = app.textFields["Palavra"]
    enter("Fixture draft", in: word, name: "dictionary-draft")
    capture("dictionary-editor-keyboard-dirty")
    press("Cancelar"); back()
    XCTAssertTrue(app.tabBars.buttons["Biblioteca"].isSelected)
    press("library.snippets"); capture("snippets")
    press("Adicionar snippet")
    let trigger = app.textFields["Frase de ativação"]
    enter("fixture phrase", in: trigger, name: "snippet-draft")
    capture("snippets-editor-keyboard-dirty")
    press("Cancelar"); back()
    tab("Ajustes"); capture("settings")
    press("settings.account")
    XCTAssertTrue(app.descendants(matching: .any)["app.account"].firstMatch.waitForExistence(timeout: 15))
    let weeklyUsage = app.staticTexts["account.weeklyUsage"]
    XCTAssertTrue(weeklyUsage.waitForExistence(timeout: 15))
    XCTAssertEqual(weeklyUsage.label, "12,5% usados · 82,5% restantes")
    XCTAssertTrue(app.staticTexts["account.usageReset"].label.hasPrefix("Próxima renovação: "))
    XCTAssertFalse(app.buttons["processing.computer"].exists, "Identity and usage do not become PC controls")
    capture("account"); back()
    XCTAssertTrue(app.tabBars.buttons["Ajustes"].isSelected)
    press("settings.processing"); capture("processing"); back()
    press("settings.output")
    press("output.language.de"); press("output.style.very_casual")
    capture("output-preferences")
    press("output.close")
    press("settings.output")
    let german = app.descendants(matching: .any)["output.language.de"].firstMatch
    XCTAssertTrue(german.waitForExistence(timeout: 15))
    XCTAssertTrue(german.isSelected)
    press("output.close")
    press("settings.microphone"); capture("microphone-keyboard"); back()
    press("settings.privacy"); capture("privacy"); back()
    press("settings.guide")
    XCTAssertTrue(app.descendants(matching: .any)["onboarding.keyboard"].firstMatch.waitForExistence(timeout: 15))
    capture("guide-keyboard"); back()
    XCTAssertTrue(app.tabBars.buttons["Ajustes"].isSelected)
    verifyActions()
    tab("Ajustes"); press("settings.output")
    let unchangedLanguage = app.descendants(matching: .any)["output.language.de"].firstMatch
    XCTAssertTrue(unchangedLanguage.waitForExistence(timeout: 15))
    XCTAssertTrue(unchangedLanguage.isSelected, "Translation target does not change dictation output")
    press("output.close"); press("settings.account")
    press("account.logout")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    app.terminate(); app.launch()
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 20))
    XCTAssertFalse(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.exists)
    capture("login-after-logout")
  }
}

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
  @discardableResult func reveal(_ element: XCUIElement, identifier: String) -> Bool {
    for attempt in 0...12 {
      let containingPage = app.scrollViews.containing(.any, identifier: identifier).firstMatch
      // Only absent AX targets need a fallback scroll search. Fixed sheet
      // headers are visible outside the scroll view and use window bounds.
      let page = containingPage.exists || element.exists ? containingPage : app.scrollViews.allElementsBoundByIndex.reversed().first {
        $0.exists && $0.isHittable && $0.frame.intersects(app.frame)
      } ?? app.scrollViews.firstMatch
      var viewport = page.exists ? page.frame.intersection(app.frame) : app.frame
      let tabBar = app.tabBars.firstMatch
      if tabBar.exists && tabBar.isHittable && viewport.intersects(tabBar.frame) {
        viewport.size.height = max(0, tabBar.frame.minY - viewport.minY)
      }
      let keyboard = app.keyboards.firstMatch
      if keyboard.exists && viewport.intersects(keyboard.frame) {
        viewport.size.height = max(0, keyboard.frame.minY - viewport.minY)
      }
      let frame = element.exists ? element.frame : CGRect.null
      let located = !frame.isNull && !frame.isInfinite && frame.width > 0 && frame.height > 0
      let center = CGPoint(x: frame.midX, y: frame.midY)
      let fits = frame.width <= viewport.width && frame.height <= viewport.height
      let visible = fits ? viewport.contains(frame) : viewport.contains(center)
      if located && element.isHittable && visible { return true }
      if attempt == 12 { break }
      if page.exists && page.frame.height > 0 && !viewport.isEmpty {
        // Clipped React Native elements can have an infinite AX frame. Search
        // toward the top first, then the bottom until a usable frame appears.
        let down = located ? frame.midY < viewport.midY : attempt < 6
        // Fixed flicks can skip a tall row in both directions at accessibility
        // sizes. Aim for the visible area's center and stop before releasing.
        let limit = viewport.height * 0.6
        let distance = located ? min(max(abs(frame.midY - viewport.midY), 16), limit) : limit
        let startY = viewport.midY + (down ? -distance / 2 : distance / 2)
        let origin = app.coordinate(withNormalizedOffset: .zero)
        let start = origin.withOffset(CGVector(dx: viewport.minX + viewport.width * 0.02, dy: startY))
        let finish = start.withOffset(CGVector(dx: 0, dy: down ? distance : -distance))
        start.press(forDuration: 0.1, thenDragTo: finish, withVelocity: .slow, thenHoldForDuration: 0.2)
      } else if (located ? frame.midY < app.frame.midY : attempt < 6) { app.swipeDown() } else { app.swipeUp() }
    }
    diagnose("unreachable-\(identifier)"); XCTFail("Cannot reveal element: \(identifier)"); return false
  }
  func press(_ identifier: String, allowScroll: Bool = true) {
    let button = app.descendants(matching: .any)[identifier].firstMatch
    let exists = button.waitForExistence(timeout: 15)
    guard exists || allowScroll else {
      diagnose("missing-\(identifier)"); XCTFail("Missing action: \(identifier)"); return
    }
    if allowScroll && !reveal(button, identifier: identifier) { return }
    let enabled = expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: button)
    guard XCTWaiter.wait(for: [enabled], timeout: 15) == .completed else {
      diagnose("disabled-\(identifier)"); XCTFail("Disabled action: \(identifier)"); return
    }
    let reachable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true"), object: button)
    guard XCTWaiter.wait(for: [reachable], timeout: 5) == .completed else {
      diagnose("unreachable-\(identifier)"); XCTFail("Unreachable action: \(identifier)"); return
    }
    button.tap()
  }
  func tab(_ label: String) {
    if label == "Ajustes" {
      if app.descendants(matching: .any)["app.preferences"].firstMatch.exists { return }
      press("workspace.menu"); press("menu.settings"); return
    }
    if app.descendants(matching: .any)["app.preferences"].firstMatch.exists { press("Fechar") }
    let button = app.tabBars.buttons[label].firstMatch
    XCTAssertTrue(button.waitForExistence(timeout: 20), "Missing tab: \(label)")
    let introduction = app.otherElements["UIContinuousPathIntroductionView"].firstMatch
    if introduction.exists {
      capture("system-keyboard-introduction")
      let proceed = introduction.buttons["Continue"].firstMatch
      let ready = proceed.waitForExistence(timeout: 5)
      if introduction.exists {
        // The system can remove this overlay between AX queries. Do not ask
        // XCTest for a hit point on a stale Continue element.
        let frame = ready ? (try? proceed.snapshot())?.frame : nil
        if introduction.exists {
          guard let frame, !frame.isNull, !frame.isInfinite,
                frame.width > 0, frame.height > 0, app.frame.contains(frame) else {
            diagnose("keyboard-introduction-blocked"); XCTFail("Cannot finish the system keyboard introduction"); return
          }
          app.coordinate(withNormalizedOffset: .zero).withOffset(
            CGVector(dx: frame.midX - app.frame.minX, dy: frame.midY - app.frame.minY)).tap()
        }
      }
      let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: introduction)
      guard XCTWaiter.wait(for: [closed], timeout: 5) == .completed else {
        diagnose("keyboard-introduction-remains"); XCTFail("System keyboard introduction is still visible"); return
      }
    }
    let keyboard = app.keyboards.firstMatch
    if keyboard.exists {
      let keyboardPage = app.descendants(matching: .any)["app.keyboard-page"].firstMatch.scrollViews.firstMatch
      let accountPage = app.scrollViews["app.account"].firstMatch
      let page = keyboardPage.exists ? keyboardPage : accountPage
      guard page.exists && page.frame.intersects(app.frame) else {
        diagnose("keyboard-dismissal-page-missing"); XCTFail("Cannot reach the page to dismiss the keyboard"); return
      }
      // KeyboardPage uses handled taps. Its empty gutter is outside child controls.
      // Tap there to finish editing without leaving an interactive drag in progress.
      page.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.5)).tap()
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
    guard button.waitForExistence(timeout: 15) else {
      diagnose("missing-keyboard-action-\(identifier)")
      XCTFail("Missing action with the keyboard open: \(identifier)")
      return
    }
    let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: button)
    guard XCTWaiter.wait(for: [enabled], timeout: 15) == .completed else {
      diagnose("disabled-keyboard-action-\(identifier)")
      XCTFail("Action stayed disabled with the keyboard open: \(identifier)")
      return
    }
    // During keyboard layout, XCTest can report a button as hittable before
    // its frame settles. Check the visible viewport on every submission.
    guard reveal(button, identifier: identifier) else { return }
    XCTAssertTrue(keyboard.exists && keyboard.isHittable, "Scrolling must keep the keyboard open")
    XCTAssertTrue(field.isHittable, "Keep the input visible beside its action")
    XCTAssertEqual(field.value as? String, value, "Scrolling must retain the complete input")
    button.tap()
  }
  func enter(_ value: String, in field: XCUIElement, name: String, replacing: Bool = false) {
    XCTAssertTrue(field.waitForExistence(timeout: 15))
    guard reveal(field, identifier: field.identifier.isEmpty ? field.label : field.identifier) else { return }
    field.tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10))
    if replacing { field.typeKey("a", modifierFlags: .command) }
    field.typeText(value)
    // Keep the first observation; event synthesis can finish before UIKit input delivery.
    let firstRead = field.value as? String
    print("APP_UI_INPUT_FIRST_READ \(name) expected=\(String(reflecting: value)) actual=\(String(reflecting: firstRead))")
    let complete = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: field)
    let received = firstRead == value || XCTWaiter.wait(for: [complete], timeout: 10) == .completed
    let actual = field.value as? String
    guard received && actual == value else {
      print("APP_UI_INPUT_FAILURE \(name) expected=\(String(reflecting: value)) actual=\(String(reflecting: actual)) frame=\(field.frame) hittable=\(field.isHittable)")
      diagnose("typing-\(name)")
      XCTFail("Input did not retain the typed characters: \(name); expected \(String(reflecting: value)), actual \(String(reflecting: actual))")
      return
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
  func refreshActions() {
    press("actions.choose")
    press("actions.refresh")
    press("Fechar")
  }
  func chooseRewrite() {
    press("actions.choose")
    press("actions.option.saved:rewrite:1")
  }
  func waitForCatalogDiscovery() {
    let progress = app.staticTexts.matching(NSPredicate(format: "identifier BEGINSWITH 'actions.operation.' AND identifier != 'actions.operation.starting'")).firstMatch
    XCTAssertTrue(progress.waitForExistence(timeout: 10), "Accepted UUID must arrive before discovery completes")
    XCTAssertNotNil(UUID(uuidString: progress.identifier.replacingOccurrences(of: "actions.operation.", with: "")))
    // Automatic account refresh also loads this catalog. The barrier proves
    // discovery is pending; its request count is not an operation count.
    XCTAssertGreaterThanOrEqual(fixture("/__fixture/wait-catalog")["held"] as? Int ?? 0, 1)
  }
  func verifyActions() {
    tab("Ações")
    let text = app.textViews["actions.text"]
    enter("cancel", in: text, name: "composer")
    capture("actions-draft-keyboard")
    chooseRewrite()
    tab("Dicionário"); tab("Ações")
    XCTAssertEqual(text.value as? String, "cancel", "Tab navigation keeps the mounted draft")
    refreshActions()
    XCTAssertEqual(text.value as? String, "cancel")
    press("actions.choose"); press("Fechar")
    XCTAssertEqual(text.value as? String, "cancel", "Sheet dismissal keeps the draft")
    let previousPosts = (fixture("/__fixture/state")["processing"] as? [Any])?.count
    _ = fixture("/__fixture/control", values: ["catalog": "slow"])
    press("actions.run")
    waitForCatalogDiscovery()
    XCTAssertFalse(app.buttons["actions.copy"].exists)
    capture("actions-slow-catalog-accepted")
    press("actions.cancel")
    absent(app.buttons["actions.cancel"])
    _ = fixture("/__fixture/control", values: ["release": true])
    XCTAssertEqual((fixture("/__fixture/state")["processing"] as? [Any])?.count, previousPosts)
    XCTAssertEqual(text.value as? String, "cancel")
    XCTAssertFalse(app.buttons["actions.copy"].exists)
    // Reload the interrupted catalog before starting the next independent case.
    refreshActions(); chooseRewrite()
    XCTAssertEqual(text.value as? String, "cancel")
    enter("off", in: text, name: "deactivated-composer", replacing: true)
    _ = fixture("/__fixture/control", values: ["catalog": "slow"])
    press("actions.run")
    waitForCatalogDiscovery()
    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
      CFNotificationName("com.clarify.app-flow.deactivate" as CFString), nil, nil, true)
    absent(app.buttons["actions.cancel"])
    _ = fixture("/__fixture/control", values: ["release": true])
    XCTAssertEqual((fixture("/__fixture/state")["processing"] as? [Any])?.count, previousPosts)
    XCTAssertFalse(app.buttons["actions.copy"].exists)
    capture("actions-deactivated-discovery")
    enter("cancel", in: text, name: "cancelled-composer", replacing: true)
    for mode in ["empty", "failed"] {
      _ = fixture("/__fixture/control", values: ["catalog": mode])
      refreshActions()
      let status = app.staticTexts["actions.catalog-status"]
      XCTAssertTrue(status.waitForExistence(timeout: 10))
      let expected = mode == "empty" ? "Nenhuma ação salva neste destino." : "Não foi possível carregar as ações. Atualize para tentar novamente."
      let updated = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", expected), object: status)
      XCTAssertEqual(XCTWaiter.wait(for: [updated], timeout: 15), .completed)
      XCTAssertFalse(app.buttons["actions.run"].isEnabled)
      XCTAssertEqual(text.value as? String, "cancel")
      capture("actions-catalog-\(mode)")
    }
    _ = fixture("/__fixture/control", values: ["catalog": "ready"])
    refreshActions(); chooseRewrite()
    enter("done", in: text, name: "successful-composer", replacing: true)
    press("actions.run")
    XCTAssertTrue(app.staticTexts["actions.result"].waitForExistence(timeout: 15))
    XCTAssertEqual(app.staticTexts["actions.result"].label, "Fixture result: done")
    press("actions.copy")
    XCTAssertTrue(app.staticTexts["Texto copiado."].waitForExistence(timeout: 10))
    let completedPosts = fixture("/__fixture/state")["processing"] as? [[String: Any]] ?? []
    XCTAssertEqual(completedPosts.count, (previousPosts ?? 0) + 1)
    let firstRequest = completedPosts.last?["value"] as? [String: Any]
    XCTAssertEqual(firstRequest?["language"] as? String, "de")
    XCTAssertEqual(firstRequest?["writing_style"] as? String, "casual")
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
    XCTAssertEqual(posted?.count, (previousPosts ?? 0) + 2)
    let translation = posted?.last?["value"] as? [String: Any]
    XCTAssertEqual(translation?["language"] as? String, "ru")
    capture("actions-translation-russian")
    _ = fixture("/__fixture/control", values: ["revision": 2])
    refreshActions()
    XCTAssertTrue(app.staticTexts["actions.catalog-status"].waitForExistence(timeout: 10))
    let stale = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == false"), object: app.buttons["actions.run"])
    XCTAssertEqual(XCTWaiter.wait(for: [stale], timeout: 15), .completed)
    capture("actions-stale-choice")
  }
  func signIn(checkPersistence: Bool) {
    app.launch()
    XCTAssertTrue(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.waitForExistence(timeout: 30))
    capture("onboarding-first-open")
    press("onboarding.skip")
    XCTAssertTrue(app.descendants(matching: .any)["app.keyboard-page"].firstMatch.waitForExistence(timeout: 30))
    XCTAssertFalse(app.textFields["account.email"].exists)
    XCTAssertFalse(app.tabBars.firstMatch.exists)
    if checkPersistence {
      app.terminate(); app.launch()
      XCTAssertTrue(app.buttons["computer.scan"].waitForExistence(timeout: 20))
      XCTAssertFalse(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.exists)
    }
    capture("computer-pairing-required")
    press("computer.scan")
    // The generated scanner supplies a synthetic invitation. Pairing, Keychain,
    // readiness and the protected route all use the actual native contract.
    tab("Início")
    XCTAssertEqual(app.tabBars.buttons.count, 5)
    verifyLibraryIsolation()
    tab("Ajustes"); press("settings.account")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    for provider in ["google", "microsoft", "github"] {
      XCTAssertFalse(app.buttons["account.social.\(provider)"].exists, "The HTTP fixture supports email sign-in only")
    }
    enter("clarify-e2e@example.test", in: app.textFields["account.email"], name: "email")
    XCTAssertEqual(app.textFields["account.email"].value as? String, "clarify-e2e@example.test")
    capture("login-email-keyboard-visible")
    pressWithKeyboard("account.requestCode", field: app.textFields["account.email"], value: "clarify-e2e@example.test")
    guard app.textFields["account.code"].waitForExistence(timeout: 15) else {
      diagnose("login-code-missing"); XCTFail("Login did not show the code field. Inspect the HTTP journal and app alert."); return
    }
    if checkPersistence {
      press("account.backToEmail")
      let email = app.textFields["account.email"]
      XCTAssertTrue(email.waitForExistence(timeout: 15))
      XCTAssertEqual(email.value as? String, "clarify-e2e@example.test", "Returning from the code step retains the email draft")
      capture("login-email-restored")
      email.tap()
      XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10))
      email.typeText("\n")
      XCTAssertTrue(app.textFields["account.code"].waitForExistence(timeout: 15), "Return submits the native field's complete email")
      enter("000000", in: app.textFields["account.code"], name: "invalid-code")
      pressWithKeyboard("account.verifyCode", field: app.textFields["account.code"], value: "000000")
      let alert = app.alerts["Clarify"].firstMatch
      XCTAssertTrue(alert.waitForExistence(timeout: 15))
      alert.buttons.firstMatch.tap()
      XCTAssertFalse(app.buttons["account.verifyCode"].isEnabled, "A rejected attempt clears the submitted code")
      capture("login-code-reset-after-rejection")
    }
    // Enter without replacing so a stale native code also fails the first read.
    enter("123456", in: app.textFields["account.code"], name: "code")
    capture("login-code-keyboard-visible")
    pressWithKeyboard("account.verifyCode", field: app.textFields["account.code"], value: "123456")
    back(); tab("Início")
    XCTAssertEqual(app.tabBars.buttons.count, 5)
  }
  func verifyLibraryIsolation() {
    for label in ["Dicionário", "Snippets"] {
      tab(label)
      XCTAssertTrue(app.staticTexts["Use o dicionário e os snippets configurados no computador."].firstMatch.waitForExistence(timeout: 15))
      XCTAssertFalse(app.buttons["Adicionar palavra"].exists)
      XCTAssertFalse(app.buttons["Adicionar snippet"].exists)
      capture("computer-library-\(label)")
    }
  }
  func signOutKeepingComputer() {
    press("account.logout")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    back(); tab("Início")
    XCTAssertEqual(app.tabBars.buttons.count, 5, "Account logout must keep LAN pairing")
    app.terminate(); app.launch()
    tab("Início")
    XCTAssertFalse(app.descendants(matching: .any)["onboarding.welcome"].firstMatch.exists)
    verifyLibraryIsolation()
    tab("Ajustes"); press("settings.account")
    XCTAssertTrue(app.textFields["account.email"].waitForExistence(timeout: 15))
    capture("account-logout-keeps-computer")
    back(); press("settings.processing")
    XCTAssertTrue(app.staticTexts["computer.status"].waitForExistence(timeout: 15))
    press("computer.manage"); press("computer.disconnect")
    let alert = app.alerts.firstMatch
    XCTAssertTrue(alert.waitForExistence(timeout: 15)); alert.buttons["Desconectar"].tap()
    XCTAssertTrue(app.buttons["computer.scan"].waitForExistence(timeout: 15))
    XCTAssertFalse(app.tabBars.firstMatch.exists, "Disconnect closes the protected workspace")
  }
  func testFirstPresentationAccountNavigationAndExplicitReplay() {
    signIn(checkPersistence: true)
    XCTAssertFalse(app.buttons["home.account"].exists)
    capture("dictation")
    verifyLibraryIsolation()
    tab("Ajustes"); capture("settings")
    press("settings.account")
    XCTAssertTrue(app.descendants(matching: .any)["app.account"].firstMatch.waitForExistence(timeout: 15))
    XCTAssertTrue(app.staticTexts["clarify-e2e@example.test"].firstMatch.waitForExistence(timeout: 15))
    XCTAssertFalse(app.staticTexts["Uso nesta semana"].exists)
    capture("account"); back()
    XCTAssertTrue(app.descendants(matching: .any)["app.preferences"].firstMatch.exists)
    press("settings.processing"); capture("processing"); back()
    press("settings.output")
    press("output.policy.clarity"); press("output.style.casual"); press("output.more"); press("output.language.de")
    capture("output-preferences")
    press("output.close")
    press("settings.output"); press("output.more")
    let german = app.descendants(matching: .any)["output.language.de"].firstMatch
    XCTAssertTrue(german.waitForExistence(timeout: 15))
    XCTAssertTrue(german.isSelected)
    press("output.close")
    press("settings.microphone"); capture("microphone-keyboard"); back()
    press("settings.privacy"); capture("privacy"); back()
    press("settings.guide")
    XCTAssertTrue(app.descendants(matching: .any)["onboarding.keyboard"].firstMatch.waitForExistence(timeout: 15))
    capture("guide-keyboard"); press("onboarding.back")
    XCTAssertTrue(app.descendants(matching: .any)["app.preferences"].firstMatch.exists)
    verifyActions()
    tab("Ajustes"); press("settings.output"); press("output.more")
    let sharedLanguage = app.descendants(matching: .any)["output.language.ru"].firstMatch
    XCTAssertTrue(sharedLanguage.waitForExistence(timeout: 15))
    XCTAssertTrue(sharedLanguage.isSelected, "Text actions and dictation use the same output language")
    press("output.close"); press("settings.account")
    signOutKeepingComputer()
  }
  func testCompactKeyboardAndActionLayout() {
    signIn(checkPersistence: false)
    capture("compact-dictation")
    verifyLibraryIsolation()
    tab("Ajustes"); capture("compact-settings")
    press("settings.account")
    XCTAssertTrue(app.staticTexts["clarify-e2e@example.test"].firstMatch.waitForExistence(timeout: 15))
    XCTAssertFalse(app.staticTexts["Uso nesta semana"].exists)
    capture("compact-account"); back()
    press("settings.output")
    press("output.policy.clarity"); press("output.style.casual"); press("output.more"); press("output.language.de")
    capture("compact-output"); press("output.close")
    tab("Ações")
    let text = app.textViews["actions.text"], draft = "a\nb\nc"
    enter(draft, in: text, name: "compact-composer")
    chooseRewrite()
    tab("Dicionário"); tab("Ações")
    XCTAssertEqual(text.value as? String, draft)
    let previousPosts = (fixture("/__fixture/state")["processing"] as? [Any])?.count
    _ = fixture("/__fixture/control", values: ["catalog": "slow"])
    press("actions.run")
    waitForCatalogDiscovery()
    capture("compact-cancel-ready")
    press("actions.cancel", allowScroll: false)
    let cancel = app.buttons["actions.cancel"]
    let cancelled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: cancel)
    guard XCTWaiter.wait(for: [cancelled], timeout: 15) == .completed else {
      diagnose("compact-cancel-remains"); XCTFail("Cancel did not end the action"); return
    }
    _ = fixture("/__fixture/control", values: ["release": true])
    XCTAssertEqual((fixture("/__fixture/state")["processing"] as? [Any])?.count, previousPosts)
    XCTAssertEqual(text.value as? String, draft)
    refreshActions()
    absent(app.staticTexts["actions.catalog-status"])
    enter("ok", in: text, name: "compact-result", replacing: true)
    press("actions.choose"); capture("compact-action-sheet")
    press("actions.option.saved:translation:1"); press("actions.language")
    capture("compact-language-sheet"); press("actions.target.ru")
    press("actions.run")
    XCTAssertTrue(app.staticTexts["actions.result"].waitForExistence(timeout: 15))
    XCTAssertEqual((fixture("/__fixture/state")["processing"] as? [Any])?.count, (previousPosts ?? 0) + 1)
    XCTAssertEqual(app.staticTexts["actions.result"].label, "Fixture result: ok")
    press("actions.copy")
    XCTAssertTrue(app.staticTexts["Texto copiado."].waitForExistence(timeout: 10))
    capture("compact-copied-result")
    tab("Ajustes"); press("settings.account"); signOutKeepingComputer()
  }
}

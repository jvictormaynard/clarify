import XCTest

final class KeyboardExtensionTests: XCTestCase {
  private var fixtureRoot: URL {
    URL(fileURLWithPath: Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyFixtureDirectory") as! String)
  }
  private func acceptSystemOpenPrompt() {
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    let open = springboard.alerts.buttons["Open"]
    if open.waitForExistence(timeout: 5) { open.tap() }
  }
  func testActivationContainerReceivesOpenURL() throws {
    continueAfterFailure = false
    let app = XCUIApplication(); app.launch()
    app.buttons["Open activation fixture"].tap()
    acceptSystemOpenPrompt()
    let receipt = fixtureRoot.appendingPathComponent("return-trace.json")
    let delivered = expectation(for: NSPredicate { _, _ in FileManager.default.fileExists(atPath: receipt.path) }, evaluatedWith: nil)
    wait(for: [delivered], timeout: 10)
    try FileManager.default.copyItem(at: receipt, to: fixtureRoot.appendingPathComponent("container-preflight.json"))
    try FileManager.default.removeItem(at: receipt)
    app.activate()
  }
  private func open(_ title: String, in app: XCUIApplication) {
    // Keep a live query. Binding the row's snapshot identity can fail when
    // Settings rebuilds its SwiftUI list between finding a row and tapping it.
    // The keyboard settings page and its first row can both be titled
    // "Keyboards". Restrict the query to actionable rows, excluding headers.
    let row = app.cells.matching(NSPredicate(format: "label BEGINSWITH %@", title)).firstMatch
    let button = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@ OR identifier == %@", title, title)).firstMatch
    // Settings can finish its tap event before publishing the next list.
    // Wait for its rows before scrolling; an early swipe can dismiss the sheet.
    if !row.waitForExistence(timeout: 3) { _ = button.waitForExistence(timeout: 3) }
    for _ in 0..<8 {
      let item = row.exists ? row : button
      if item.exists && item.isHittable {
        item.tap()
        if ["General", "Keyboard", "Keyboards"].contains(title) {
          let titles = title == "Keyboard" ? ["Keyboard", "Keyboards"] : [title]
          let header = app.navigationBars.matching(NSPredicate(format: "identifier IN %@ OR label IN %@", titles, titles)).firstMatch
          XCTAssertTrue(header.waitForExistence(timeout: 10), "Settings navigation did not complete: \(title)")
        }
        return
      }
      app.swipeUp()
    }
    XCTFail("Settings item unavailable: \(title). \(app.debugDescription)")
  }
  private func checkTrace(in app: XCUIApplication, opening: String, strict: Bool = true, monotonic: Bool = false) throws {
    let raw = try XCTUnwrap(app.staticTexts["keyboard-frames"].value as? String)
    let values = try JSONDecoder().decode([String: [Double]].self, from: Data(raw.utf8))
    let heights = values.values.flatMap { $0 }
    XCTAssertFalse(heights.isEmpty)
    let trace = XCTAttachment(string: "\(opening): \(raw)"); trace.name = opening
    trace.lifetime = .keepAlways; add(trace)
    continueAfterFailure = true
    defer { continueAfterFailure = false }
    if strict {
      XCTAssertTrue(heights.allSatisfy { $0 < 400 }, "\(opening): \(values)")
      if monotonic {
        let visible = values["visibleFrames"] ?? []
        XCTAssertFalse(visible.isEmpty, "Opening must include presentation samples")
        var peak = -Double.infinity, retreat = 0.0
        for height in visible {
          peak = max(peak, height); retreat = max(retreat, peak - height)
        }
        XCTAssertLessThanOrEqual(retreat, 3, "The opening must not reverse during its animation: \(values)")
      }
    }
    // Publication may defer the known transient overshoot, but must still
    // reject a keyboard that stays oversized or covers the bottom row.
    XCTAssertLessThan(values["displayFrames"]?.last ?? .infinity, 400, "The keyboard must settle at its usable height")
    XCTAssertGreaterThanOrEqual(values["displayFrames"]?.last ?? 0, 278, "The keyboard must remain fully visible")
  }
  private func expectText(_ text: String, in app: XCUIApplication) {
    let inserted = expectation(for: NSPredicate { _, _ in
      app.textFields["composer"].value as? String == text
    }, evaluatedWith: nil)
    wait(for: [inserted], timeout: 3)
  }
  private func captureKeyboardReference(_ name: String, uppercase: Bool, in app: XCUIApplication) throws {
    let expected = uppercase ? "Q" : "q"
    let firstLetter = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", expected)).firstMatch
    XCTAssertTrue(firstLetter.waitForExistence(timeout: 5), "Reference case did not settle: \(name)")
    captureKeyboardAppearance(name, in: app)
    var keys: [[String: Any]] = []
    for letter in "qwertyuiopasdfghjklzxcvbnm" {
      let lower = String(letter), upper = lower.uppercased()
      let key = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", lower, upper)).firstMatch
      XCTAssertTrue(key.exists, "Missing reference letter \(lower): \(name)")
      let frame = key.frame
      keys.append(["letter": lower, "label": key.label, "x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height])
    }
    let data = try JSONSerialization.data(withJSONObject: ["name": name, "uppercase": uppercase, "keys": keys,
      "inputLanguage": app.staticTexts["input-language"].value as? String ?? "unavailable",
      "os": ProcessInfo.processInfo.operatingSystemVersionString,
      "coordinateMeaning": "Accessibility frames in screen points; not visible bounds or adaptive touch targets"], options: [.sortedKeys])
    let geometry = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
    geometry.name = "\(name)-geometry"; geometry.lifetime = .keepAlways; add(geometry)
  }
  private func captureKeyboardAppearance(_ name: String, in app: XCUIApplication) {
    let language = app.staticTexts["input-language"].value as? String ?? "unavailable"
    let inputMode = XCTAttachment(string: language)
    inputMode.name = "\(name)-input-language"; inputMode.lifetime = .keepAlways; add(inputMode)
    let screen = XCTAttachment(screenshot: app.screenshot())
    screen.name = name; screen.lifetime = .keepAlways; add(screen)
    // AX frames are reference coordinates, not visible shapes or adaptive targets.
    let tree = XCTAttachment(string: app.debugDescription)
    tree.name = "\(name)-accessibility"; tree.lifetime = .keepAlways; add(tree)
  }
  private func selectClarifyKeyboard(in app: XCUIApplication) {
    let keyboard = app.buttons["clarify.keyboard.record"]
    let globe = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", "next keyboard")).firstMatch
    // The first keyboard can still be loading after Settings changes its list.
    // Wait for either input view before deciding whether a switch is needed.
    let inputReady = expectation(for: NSPredicate { _, _ in keyboard.exists || globe.exists }, evaluatedWith: nil)
    wait(for: [inputReady], timeout: 30)
    if !keyboard.exists {
      XCTAssertTrue(globe.exists, app.debugDescription)
      globe.press(forDuration: 1)
      let clarify = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Clarify")).firstMatch
      XCTAssertTrue(clarify.waitForExistence(timeout: 5), app.debugDescription); clarify.tap()
    }
    XCTAssertTrue(keyboard.waitForExistence(timeout: 30), app.debugDescription)
  }
  private func checkNumberSlide(_ name: String, in app: XCUIApplication) throws {
    let field = app.textFields["composer"]
    XCTAssertTrue(["", "Type here"].contains(field.value as? String ?? ""), "The gesture needs a fresh draft")
    let numbers = app.descendants(matching: .any).matching(NSPredicate(format: "identifier == %@ OR label == %@", "more", "123")).firstMatch
    let letter = app.keys.matching(NSPredicate(format: "label IN %@", ["q", "Q"])).firstMatch
    XCTAssertTrue(numbers.waitForExistence(timeout: 5), app.debugDescription)
    XCTAssertTrue(letter.waitForExistence(timeout: 5), app.debugDescription)
    let source = numbers.frame, destination = letter.frame
    let window = app.windows.firstMatch, windowFrame = window.frame
    XCTAssertTrue(!source.isEmpty && !destination.isEmpty && windowFrame.contains(source) && windowFrame.contains(destination))
    let origin = window.coordinate(withNormalizedOffset: .zero)
    let start = origin.withOffset(CGVector(dx: source.midX - windowFrame.minX, dy: source.midY - windowFrame.minY))
    let finish = origin.withOffset(CGVector(dx: destination.midX - windowFrame.minX, dy: destination.midY - windowFrame.minY))
    captureKeyboardAppearance("\(name)-before", in: app)
    let started = Date().timeIntervalSince1970, startedUptime = ProcessInfo.processInfo.systemUptime
    // Q and 1 share the measured first-row position. The page changes while held.
    // Anchor both coordinates to the window: Q disappears when 123 is pressed.
    start.press(forDuration: 0.1, thenDragTo: finish)
    let ended = Date().timeIntervalSince1970, endedUptime = ProcessInfo.processInfo.systemUptime
    captureKeyboardAppearance("\(name)-after", in: app)
    func rect(_ value: CGRect) -> [String: CGFloat] {
      ["x": value.minX, "y": value.minY, "width": value.width, "height": value.height]
    }
    let data = try JSONSerialization.data(withJSONObject: ["name": name, "startedUTC": started, "endedUTC": ended,
      "startedUptime": startedUptime, "endedUptime": endedUptime, "sourceAXFrame": rect(source), "destinationAXFrame": rect(destination),
      "syntheticResult": field.value as? String ?? "", "timingScope": "XCTest action API bounds, not actual touch delivery or physical latency"], options: [.sortedKeys])
    let trace = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
    trace.name = "\(name)-action-trace"; trace.lifetime = .keepAlways; add(trace)
    expectText("1", in: app)
    XCTAssertTrue(app.keys.matching(NSPredicate(format: "label IN %@", ["q", "Q"])).firstMatch.waitForExistence(timeout: 5),
                  "Releasing the number slide must return to letters")
  }
  private func captureNativeLanguage(_ language: String, names: [String], group: String) throws {
    let app = XCUIApplication(); app.terminate()
    let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
    settings.terminate(); settings.launch()
    open("General", in: settings); open("Keyboard", in: settings); open("Keyboards", in: settings)
    func row(_ names: [String], exact: Bool = false) -> XCUIElement {
      let predicates = names.map { NSPredicate(format: exact ? "label == %@" : "label BEGINSWITH %@", $0) }
      return settings.cells.matching(NSCompoundPredicate(orPredicateWithSubpredicates: predicates)).firstMatch
    }
    if !row(names).exists {
      let add = settings.cells["AddNewKeyboard"]
      XCTAssertTrue(add.waitForExistence(timeout: 5), settings.debugDescription); add.tap()
      // The regional row can be far below the initial viewport in this list.
      let search = settings.searchFields["Search"]
      XCTAssertTrue(search.waitForExistence(timeout: 5), settings.debugDescription)
      search.tap(); search.typeText(group)
      // iOS can list regional choices directly or group them under a language.
      let choices = row(names), grouped = row([group], exact: true)
      var selected = false
      for _ in 0..<8 {
        if choices.exists && choices.isHittable { choices.tap(); selected = true; break }
        if grouped.exists && grouped.isHittable {
          grouped.tap()
          XCTAssertTrue(choices.waitForExistence(timeout: 5), settings.debugDescription)
          choices.tap(); selected = true; break
        }
        settings.swipeUp()
      }
      XCTAssertTrue(selected, "Exact native keyboard unavailable: \(language). \(settings.debugDescription)")
      // iOS can default to adding this language to an existing bilingual keyboard.
      let regionalSetup = settings.navigationBars.matching(NSPredicate(format: "identifier IN %@ OR label IN %@", names, names)).firstMatch
      let separate = settings.cells.matching(NSPredicate(format: "label == %@", "Add New Keyboard")).firstMatch
      if regionalSetup.exists && separate.waitForExistence(timeout: 2) {
        separate.tap()
        let layout = settings.cells.matching(NSPredicate(format: "label == %@", "QWERTY")).firstMatch
        XCTAssertTrue(layout.waitForExistence(timeout: 5), settings.debugDescription); layout.tap()
      }
      let done = settings.navigationBars.buttons["Done"]
      if done.waitForExistence(timeout: 2) {
        let ready = expectation(for: NSPredicate { _, _ in done.isEnabled && done.isHittable }, evaluatedWith: nil)
        wait(for: [ready], timeout: 5)
        done.tap()
      }
      XCTAssertTrue(row(names).waitForExistence(timeout: 5), "Keyboard was not added: \(language). \(settings.debugDescription)")
    }
    app.launchArguments = ["--native-keyboard-reference"]; app.launch()
    app.textFields["composer"].tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10), app.debugDescription)
    let observed = app.staticTexts["input-language"]
    if observed.value as? String != language {
      let globe = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", "next keyboard")).firstMatch
      XCTAssertTrue(globe.waitForExistence(timeout: 5), app.debugDescription); globe.press(forDuration: 1)
      let choices = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", names)).firstMatch
      XCTAssertTrue(choices.waitForExistence(timeout: 5), app.debugDescription); choices.tap()
    }
    let exactLanguage = expectation(for: NSPredicate(format: "value == %@", language), evaluatedWith: observed)
    wait(for: [exactLanguage], timeout: 10)
    XCTAssertFalse(app.buttons["clarify.keyboard.record"].exists, "The language reference must use Apple's keyboard")
    try captureKeyboardReference("apple-\(language)-uppercase", uppercase: true, in: app)
    app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Q")).firstMatch.tap()
    expectText("Q", in: app)
    try captureKeyboardReference("apple-\(language)-lowercase", uppercase: false, in: app)
    try capturePagesAndDarkAppearance("apple-\(language)", in: app)
    XCTAssertEqual(observed.value as? String, language, "The language must remain selected through all pages")
    app.terminate()
    app.launch(); app.textFields["composer"].tap()
    let sameLanguage = expectation(for: NSPredicate(format: "value == %@", language), evaluatedWith: app.staticTexts["input-language"])
    wait(for: [sameLanguage], timeout: 10)
    try checkNumberSlide("apple-\(language)-number-slide", in: app)
    app.terminate()
  }
  private func capturePagesAndDarkAppearance(_ prefix: String, in app: XCUIApplication) throws {
    func control(_ labels: [String], identifier: String = "") -> XCUIElement {
      app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@ OR (identifier != '' AND identifier == %@)", labels, identifier)).firstMatch
    }
    func pages(_ suffix: String) {
      let numbers = control(["numbers", "123"], identifier: "more")
      XCTAssertTrue(numbers.waitForExistence(timeout: 5), app.debugDescription); numbers.tap()
      XCTAssertTrue(control(["1"]).waitForExistence(timeout: 5), app.debugDescription)
      captureKeyboardAppearance("\(prefix)-\(suffix)-numbers", in: app)
      let symbols = control(["symbols", "#+="], identifier: "shift")
      XCTAssertTrue(symbols.waitForExistence(timeout: 5), app.debugDescription); symbols.tap()
      XCTAssertTrue(control(["["]).waitForExistence(timeout: 5), app.debugDescription)
      captureKeyboardAppearance("\(prefix)-\(suffix)-symbols", in: app)
      let letters = control(["letters", "ABC"], identifier: "more")
      XCTAssertTrue(letters.waitForExistence(timeout: 5), app.debugDescription); letters.tap()
      XCTAssertTrue(control(["q"]).waitForExistence(timeout: 5), app.debugDescription)
    }
    pages("default")
    app.buttons["Toggle appearance"].tap()
    try captureKeyboardReference("\(prefix)-dark-lowercase", uppercase: false, in: app)
    pages("dark")
    app.buttons["Toggle backdrop"].tap()
    try captureKeyboardReference("\(prefix)-dark-blue-lowercase", uppercase: false, in: app)
    app.buttons["Toggle backdrop"].tap()
    app.buttons["Toggle appearance"].tap()
    XCTAssertTrue(control(["q"]).waitForExistence(timeout: 5), app.debugDescription)
  }
  private func activateHost(_ app: XCUIApplication) {
    app.activate()
    // Settings can return before SpringBoard finishes scaling the host window.
    // A tap computed from that transient frame misses the final composer frame.
    // Observe two stable snapshots before calculating the first input event.
    var previousWindow: CGRect?
    var previousField: CGRect?
    let settled = expectation(for: NSPredicate { _, _ in
      let window = app.windows.firstMatch
      let field = app.textFields["composer"]
      guard app.state == .runningForeground, window.exists, field.exists, field.isHittable else {
        previousWindow = nil; previousField = nil
        return false
      }
      let windowFrame = window.frame, fieldFrame = field.frame
      let stable = previousWindow == windowFrame && previousField == fieldFrame
      previousWindow = windowFrame; previousField = fieldFrame
      return stable && !windowFrame.isEmpty && windowFrame.contains(fieldFrame)
    }, evaluatedWith: nil)
    wait(for: [settled], timeout: 10)
  }
  // Run the measured native control before selecting the installed extension.
  // This initializes the system keyboard without warming the Clarify process
  // or discarding any measured Clarify opening.
  func test00NativeSystemKeyboardDoesNotReserveAnOversizedFrame() throws {
    continueAfterFailure = false
    let app = XCUIApplication(); app.launchArguments = ["--system-keyboard"]; app.launch()
    app.secureTextFields["composer"].tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
    try checkTrace(in: app, opening: "Native keyboard initial opening")
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.secureTextFields["composer"].tap()
      XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
      try checkTrace(in: app, opening: "Native keyboard opening \(index)", monotonic: true)
    }
    app.terminate()
    app.launchArguments = ["--native-keyboard-reference"]; app.launch()
    app.textFields["composer"].tap()
    XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), app.debugDescription)
    XCTAssertFalse(app.buttons["clarify.keyboard.record"].exists, "The reference must use Apple's keyboard")
    try captureKeyboardReference("apple-default-uppercase", uppercase: true, in: app)
    app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "q", "Q")).firstMatch.tap()
    expectText("Q", in: app)
    try captureKeyboardReference("apple-default-lowercase", uppercase: false, in: app)
    try capturePagesAndDarkAppearance("apple", in: app)
  }
  func testInstalledKeyboardTypingAndActivation() throws {
    continueAfterFailure = false
    executionTimeAllowance = 300
    let strictHeight = Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyStrictOpeningHeight") as? Bool ?? true
    let testFullAccess = true
    let app = XCUIApplication(); app.launch()
    let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
    settings.launch()
    open("General", in: settings)
    open("Keyboard", in: settings)
    open("Keyboards", in: settings)
    if !settings.cells.matching(NSPredicate(format: "label BEGINSWITH %@", "Clarify")).firstMatch.exists {
      let addKeyboard = settings.cells["AddNewKeyboard"]
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
      // The Settings switch can keep a stale AX value after its alert closes.
      // Verify the permission in the extension below, where it affects Start.
    }
    activateHost(app)
    app.textFields["composer"].tap()
    let keyboard = app.buttons["clarify.keyboard.record"]
    selectClarifyKeyboard(in: app)
    XCTAssertTrue(app.buttons["clarify.keyboard.start"].waitForExistence(timeout: 5),
                  "The installed extension must receive Full Access before testing activation")
    try checkTrace(in: app, opening: "Switching to the extension", strict: strictHeight)
    try captureKeyboardReference("clarify-default-uppercase", uppercase: true, in: app)
    let letter = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "q", "Q")).firstMatch
    XCTAssertTrue(letter.waitForExistence(timeout: 5), app.debugDescription); letter.tap()
    expectText("Q", in: app)
    try captureKeyboardReference("clarify-default-lowercase", uppercase: false, in: app)
    try capturePagesAndDarkAppearance("clarify", in: app)
    let space = app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["space", "espaço", "espacio"])).firstMatch
    XCTAssertTrue(space.isHittable, "The bottom keyboard row must be usable")
    space.tap()
    expectText("Q ", in: app)
    let w = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR label == %@", "w", "W")).firstMatch
    letter.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 0.03,
      thenDragTo: w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)))
    expectText("Q w", in: app)
    var sentence = "Q w"
    for punctuation in [".", "?", "!"] {
      // Letter and number controls expose keyboardKey, not the button trait.
      app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "123")).firstMatch.tap()
      app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", punctuation)).firstMatch.tap()
      app.descendants(matching: .any).matching(NSPredicate(format: "label IN %@", ["space", "espaço", "espacio"])).firstMatch.tap()
      let capital = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "A")).firstMatch
      XCTAssertTrue(capital.waitForExistence(timeout: 5), "Sentence shift must activate after \(punctuation)")
      capital.tap()
      sentence += punctuation + " A"
      expectText(sentence, in: app)
    }
    for index in 0..<4 {
      app.buttons["Dismiss"].tap(); app.buttons["Reset trace"].tap()
      app.textFields["composer"].tap()
      XCTAssertTrue(keyboard.waitForExistence(timeout: 5), app.debugDescription)
      // Querying after presentation keeps every earlier WillChangeFrame notification.
      try checkTrace(in: app, opening: "Opening \(index)", strict: strictHeight, monotonic: true)
      let capture = XCTAttachment(screenshot: app.screenshot()); capture.name = "extension-opening-\(index)"
      capture.lifetime = .keepAlways; add(capture)
    }
    let start = app.buttons["clarify.keyboard.start"]
    // The helper consumes the actual keyboard nonce and calls the production
    // bridge. A success return value alone cannot prove that the app opened.
    let container = XCUIApplication(bundleIdentifier: "com.clarify.fixture.container")
    let root = try XCTUnwrap(Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyFixtureDirectory") as? String)
    XCTAssertTrue(FileManager.default.fileExists(atPath: URL(fileURLWithPath: root).appendingPathComponent("container-ready.json").path),
                  "The isolated containing app must initialize before testing its activation URL")
    let receipt = URL(fileURLWithPath: root).appendingPathComponent("return-trace.json")
    let manualReturn = Bundle(for: Self.self).object(forInfoDictionaryKey: "ClarifyInternalManualReturn") as? Bool == true
    for attempt in 0..<2 {
      if FileManager.default.fileExists(atPath: receipt.path) { try FileManager.default.removeItem(at: receipt) }
      XCTAssertTrue(start.waitForExistence(timeout: 5), app.debugDescription)
      start.tap(); acceptSystemOpenPrompt()
      let activated = expectation(for: NSPredicate { _, _ in FileManager.default.fileExists(atPath: receipt.path) }, evaluatedWith: nil)
      // On a cold CI simulator, SpringBoard accepted the URL 16 seconds after
      // the tap and relaunched the containing app. Keep this bounded, but do
      // not time out before that system handoff can publish its receipt.
      wait(for: [activated], timeout: 30)
      let diagnostic = XCTAttachment(string: (try? String(contentsOf: receipt, encoding: .utf8)) ?? container.debugDescription)
      diagnostic.name = "activation-return-\(attempt)"; diagnostic.lifetime = .keepAlways; add(diagnostic)
      let values = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: receipt))
      XCTAssertEqual(values["nonceConsumed"], "true", "The real activation request must be consumed")
      if manualReturn && values["source"] == "unknown" {
        XCTAssertEqual(values["opened"], "false", "Only the known unavailable automatic return is deferred")
        XCTAssertEqual(values["navigationAction"], "nil")
        let visible = expectation(for: NSPredicate { _, _ in container.state == .runningForeground }, evaluatedWith: nil)
        wait(for: [visible], timeout: 5)
        let screen = XCTAttachment(screenshot: container.screenshot())
        screen.name = "internal-manual-return-\(attempt)"; screen.lifetime = .keepAlways; add(screen)
        app.activate()
      } else {
      XCTAssertEqual(values["source"], "com.clarify.fixture.host", "Resolve the current origin, not an old app")
      XCTAssertEqual(values["opened"], "true", "The production return bridge must accept the source")
      }
      let back = expectation(for: NSPredicate { _, _ in
        app.state == .runningForeground && container.state != .runningForeground
      }, evaluatedWith: nil)
      wait(for: [back], timeout: 30)
    }
    // Test this interaction only after the original typing and activation gates.
    app.terminate(); app.launch(); app.textFields["composer"].tap()
    selectClarifyKeyboard(in: app)
    try checkNumberSlide("clarify-number-slide", in: app)
  }
  // Keep the original installed acceptance first, before changing enabled languages.
  func testZ1NativeEnglishUSReference() throws {
    continueAfterFailure = false; executionTimeAllowance = 300
    try captureNativeLanguage("en-US", names: ["English (US)", "English (United States)"], group: "English")
  }
  func testZ2NativePortugueseBrazilReference() throws {
    continueAfterFailure = false; executionTimeAllowance = 300
    try captureNativeLanguage("pt-BR", names: ["Portuguese (Brazil)", "Português (Brasil)"], group: "Portuguese")
  }
}

import XCTest
import UIKit
@testable import KeyboardUI

final class KeyboardOpeningDiagnosticTests: XCTestCase {
  private func report() -> KeyboardOpeningReport {
    KeyboardOpeningReport(ios: "26.6.2", appVersion: "test", appBuild: "0",
      keyboardLabel: "Clarify", screenWidth: 402, screenHeight: 874, requestedFPS: 120)
  }
  func testExportRetainsAOneFrameOvershootEvenWhenFinalHeightIsCorrect() throws {
    var report = report()
    for (index, height) in [34.0, 598, 370, 370].enumerated() {
      XCTAssertTrue(report.append(.init(elapsed: Double(index) / 120, opening: 1,
        phase: "opening", guideHeight: height, composerHeight: height)))
    }
    report.completeOpening(1)
    report.outcome = "completed"
    let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(report)) as? [String: Any])
    let openings = try XCTUnwrap(object["openings"] as? [[String: Any]])
    XCTAssertEqual(openings.first?["peakGuideHeight"] as? Double, 598)
    XCTAssertEqual(openings.first?["settledGuideHeight"] as? Double, 370)
    XCTAssertEqual((object["frames"] as? [Any])?.count, 4)
    XCTAssertEqual(object["keyboardLabel"] as? String, "Clarify")
  }
  func testClosingFramesDoNotPolluteTheOpeningSummaryAndInvalidSamplesAreRejected() {
    var report = report()
    XCTAssertFalse(report.append(.init(elapsed: .nan, opening: 1, phase: "opening", guideHeight: 370, composerHeight: 370)))
    XCTAssertTrue(report.append(.init(elapsed: 0, opening: 1, phase: "opening", guideHeight: 370, composerHeight: 370)))
    XCTAssertTrue(report.append(.init(elapsed: 1, opening: 1, phase: "closing", guideHeight: 34, composerHeight: 34)))
    report.completeOpening(1)
    XCTAssertEqual(report.openings.first?.settledGuideHeight, 370)
  }
  func testDiagnosticScreenUsesAnOrdinaryComposerAndDoesNotStartAnAutomaticRun() async throws {
    try await MainActor.run {
      let screen = KeyboardOpeningDiagnostic(); screen.loadViewIfNeeded()
      func fields(_ view: UIView) -> [UITextField] {
        (view as? UITextField).map { [$0] } ?? view.subviews.flatMap(fields)
      }
      let field = try XCTUnwrap(fields(screen.view).first)
      XCTAssertFalse(field.isSecureTextEntry)
      XCTAssertEqual(field.keyboardType, .default)
      XCTAssertNil(screen.report, "Measurement requires an explicit user action")
      XCTAssertFalse(field.isFirstResponder, "Opening the screen must not select a keyboard")
    }
  }
  @MainActor
  func testDiagnosticCompletesTenRealPresentationsAndKeepsEachOpeningTrace() async throws {
    continueAfterFailure = false
    func stage(_ name: String) {
      NSLog("KEYBOARD_DIAGNOSTIC_STAGE %@ %.3f", name, ProcessInfo.processInfo.systemUptime)
    }
    stage("window-start")
    let window = UIWindow(frame: UIScreen.main.bounds)
    let screen = KeyboardOpeningDiagnostic()
    window.rootViewController = screen; window.makeKeyAndVisible()
    stage("window-visible")
    defer { screen.view.endEditing(true); window.isHidden = true }
    func descendants(_ view: UIView) -> [UIView] { [view] + view.subviews.flatMap(descendants) }
    let field = try XCTUnwrap(descendants(screen.view).compactMap { $0 as? UITextField }.first)
    let shown = expectation(forNotification: UIResponder.keyboardDidShowNotification, object: nil)
    stage("first-responder-start")
    XCTAssertTrue(field.becomeFirstResponder())
    stage("first-responder-returned")
    // The first system-keyboard service launch took over twenty seconds on a
    // cold CI simulator. Wait for its actual notification, without a fixed sleep.
    await fulfillment(of: [shown], timeout: 30)
    stage("keyboard-shown")
    screen.view.layoutIfNeeded()
    let run = try XCTUnwrap(descendants(screen.view).compactMap { $0 as? UIButton }.first {
      $0.title(for: .normal) == L("Testar dez aberturas")
    })
    run.sendActions(for: .touchUpInside)
    stage("ten-openings-started")
    XCTAssertNotNil(screen.report)
    let done = expectation(for: NSPredicate { _, _ in screen.report?.outcome != "running" }, evaluatedWith: nil)
    await fulfillment(of: [done], timeout: 35)
    stage("ten-openings-finished")
    let report = try XCTUnwrap(screen.report)
    // Keep the measured phase and frame timings before an assertion can stop
    // the test process. A terminal outcome alone cannot explain a timeout.
    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let attachment = XCTAttachment(data: try encoder.encode(report), uniformTypeIdentifier: "public.json")
    attachment.name = "keyboard-opening-report"; attachment.lifetime = .keepAlways; add(attachment)
    XCTAssertEqual(report.outcome, "completed", "Last sample: \(String(describing: report.frames.last))")
    XCTAssertEqual(report.openings.map(\.index), Array(1...10))
    XCTAssertTrue(report.frames.contains { $0.phase == "closing" })
    for opening in 1...10 {
      XCTAssertGreaterThan(report.frames.filter { $0.opening == opening && $0.phase == "opening" }.count, 12)
    }
    XCTAssertTrue(report.frames.allSatisfy { $0.displayElapsed != nil && $0.targetElapsed != nil })
    screen.viewWillDisappear(false)
    XCTAssertEqual(screen.report?.outcome, "completed", "Leaving the screen must preserve the completed report")
  }
}
